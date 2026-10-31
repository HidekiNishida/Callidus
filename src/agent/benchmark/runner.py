"""
Arquivo: src/agent/benchmark/runner.py
Nome: runner.py
Propósito: executor de benchmark reproduzível para avaliar o Callidus.
Responsabilidade: camada de aplicação — executa tarefas padronizadas, coleta métricas e gera relatórios.
Componentes: BenchmarkRunner, BenchmarkTask, BenchmarkResult, MetricsCollector.
Dependências: agent.orchestrator, agent.learning, agent.persistence, asyncio, json.
Observações: não depende de modelos específicos; usa o runtime existente.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.orchestrator.runner import RunOrchestrator

from agent.config import Settings
from agent.persistence.database import create_db_engine, init_db, session_scope
from agent.persistence.models import ExecutionRunModel, ProjectModel, TaskModel

_SCRIPT_FAILED = "Script falhou: {stderr}"


class BenchmarkCategory(str, Enum):
    """Categoria da tarefa de benchmark."""

    CODE_SEARCH = "code_search"  # Busca e entendimento de código
    BUG_FIX = "bug_fix"  # Correção de bugs
    FEATURE_ADD = "feature_add"  # Adição de funcionalidade
    REFACTOR = "refactor"  # Refatoração
    TEST_CREATION = "test_creation"  # Criação de testes
    DEBUGGING = "debugging"  # Depuração
    MULTI_FILE = "multi_file"  # Modificações em múltiplos arquivos
    FRONTEND = "frontend"  # Alterações de frontend


class BenchmarkDifficulty(str, Enum):
    """Dificuldade da tarefa."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class BenchmarkTask:
    """Definição de uma tarefa de benchmark."""

    id: str
    category: BenchmarkCategory
    difficulty: BenchmarkDifficulty
    objective: str
    acceptance_criteria: list[str]
    setup_script: str | None = None
    verification_script: str | None = None
    expected_files: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkMetrics:
    """Métricas coletadas durante a execução."""

    # Qualidade
    task_completed: bool = False
    requirements_satisfied: int = 0
    requirements_total: int = 0
    regressions_introduced: int = 0
    tests_passed: int = 0
    tests_total: int = 0
    human_interventions: int = 0

    # Eficiência
    total_tokens: int = 0
    tokens_per_requirement: float = 0.0
    inference_count: int = 0
    total_time_seconds: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    files_read: int = 0
    files_reread: int = 0
    tool_calls: int = 0
    peak_memory_mb: float = 0.0
    peak_vram_mb: float = 0.0

    # Resiliência
    recovery_count: int = 0
    failed_recoveries: int = 0
    unnecessary_retries: int = 0
    premature_blocks: int = 0
    successful_resumptions: int = 0
    completion_after_recovery_rate: float = 0.0


@dataclass
class BenchmarkResult:
    """Resultado completo de uma tarefa de benchmark."""

    task_id: str
    run_id: str
    task: BenchmarkTask
    metrics: BenchmarkMetrics
    success: bool
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Coleta métricas durante a execução de uma tarefa."""

    def __init__(self) -> None:
        self._inference_latencies: list[float] = []
        self._start_time: float = 0.0
        self._files_read: set[str] = set()
        self._file_read_counts: dict[str, int] = {}
        self._tool_calls: int = 0

    def start(self) -> None:
        """Inicia a coleta."""
        self._start_time = time.monotonic()

    def record_inference(self, latency_ms: float, _tokens: int) -> None:
        """Registra uma inferência."""
        self._inference_latencies.append(latency_ms)

    def record_file_read(self, path: str) -> None:
        """Registra leitura de arquivo."""
        self._files_read.add(path)
        self._file_read_counts[path] = self._file_read_counts.get(path, 0) + 1

    def record_tool_call(self) -> None:
        """Registra chamada de ferramenta."""
        self._tool_calls += 1

    def get_metrics(self) -> BenchmarkMetrics:
        """Obtém as métricas coletadas."""
        total_time = time.monotonic() - self._start_time
        latencies = sorted(self._inference_latencies)
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[p95_idx] if latencies else 0.0

        files_read = len(self._files_read)
        files_reread = sum(1 for count in self._file_read_counts.values() if count > 1)

        return BenchmarkMetrics(
            total_time_seconds=total_time,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            files_read=files_read,
            files_reread=files_reread,
            tool_calls=self._tool_calls,
        )


class BenchmarkRunner:
    """Executa benchmarks reproduzíveis."""

    def __init__(
        self,
        project_root: str,
        db_path: str,
        output_dir: str,
    ) -> None:
        """Inicializa o runner.

        Args:
            project_root: raiz do projeto.
            db_path: caminho do banco de dados.
            output_dir: diretório para salvar resultados.
        """
        self._project_root = Path(project_root)
        self._db_path = db_path
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Inicializa banco
        settings = Settings(data_dir=Path(db_path).parent)
        engine = create_db_engine(settings)
        init_db(engine)

    def _load_tasks(self, tasks_file: str) -> list[BenchmarkTask]:
        """Carrega tarefas de um arquivo JSON."""
        with Path(tasks_file).open(encoding="utf-8") as f:
            data = json.load(f)

        return [
            BenchmarkTask(
                id=item["id"],
                category=BenchmarkCategory(item["category"]),
                difficulty=BenchmarkDifficulty(item["difficulty"]),
                objective=item["objective"],
                acceptance_criteria=item["acceptance_criteria"],
                setup_script=item.get("setup_script"),
                verification_script=item.get("verification_script"),
                expected_files=item.get("expected_files", []),
                timeout_seconds=item.get("timeout_seconds", 300),
                metadata=item.get("metadata", {}),
            )
            for item in data.get("tasks", [])
        ]

    async def run_task(
        self,
        task: BenchmarkTask,
        orchestrator: RunOrchestrator,
    ) -> BenchmarkResult:
        """Executa uma tarefa de benchmark.

        Args:
            task: tarefa a executar.
            orchestrator: orquestrador configurado.

        Returns:
            Resultado do benchmark.
        """
        run_id = str(uuid.uuid4())
        collector = MetricsCollector()
        collector.start()

        # Executa script de setup se houver
        if task.setup_script:
            await self._run_script(task.setup_script)

        # Cria a tarefa no orquestrador
        run = await self._create_run(run_id, task)
        await self._create_task(run, task)

        try:
            # Executa a tarefa
            await orchestrator.run(run_id)

            # Aguarda conclusão
            result = await self._wait_for_completion(run_id, task.timeout_seconds)

            # Executa verificação se houver script
            if task.verification_script:
                await self._run_script(task.verification_script)

            # Avalia resultado
            metrics = collector.get_metrics()
            await self._evaluate_result(task, result, metrics)

            return BenchmarkResult(
                task_id=task.id,
                run_id=run_id,
                task=task,
                metrics=metrics,
                success=result.get("success", False),
                error=result.get("error"),
                completed_at=datetime.now(UTC).isoformat(),
            )

        except Exception as e:
            metrics = collector.get_metrics()
            return BenchmarkResult(
                task_id=task.id,
                run_id=run_id,
                task=task,
                metrics=metrics,
                success=False,
                error=str(e),
                completed_at=datetime.now(UTC).isoformat(),
            )

        finally:
            await self._cleanup_run(run_id)

    async def _create_run(self, run_id: str, task: BenchmarkTask) -> ExecutionRunModel:
        """Cria uma execução."""
        with session_scope(self._db_path) as session:
            project = session.query(ProjectModel).first()
            if not project:
                project = ProjectModel(
                    id=str(uuid.uuid4()),
                    name="benchmark",
                    root_path=str(self._project_root),
                )
                session.add(project)
                session.flush()

            run = ExecutionRunModel(
                id=uuid.UUID(run_id),
                project_id=project.id,
                config_json={"benchmark": True, "task_id": task.id},
                status="RUNNING",
            )
            session.add(run)
            session.flush()
            return run

    async def _create_task(self, run: ExecutionRunModel, task: BenchmarkTask) -> TaskModel:
        """Cria a tarefa raiz."""
        with session_scope(self._db_path) as session:
            task_model = TaskModel(
                id=uuid.uuid4(),
                project_id=run.project_id,
                parent_id=None,
                title=task.id,
                objective=task.objective,
                kind="OPERATION",
                acceptance_criteria="\n".join(task.acceptance_criteria),
                metadata_json={
                    "benchmark": True,
                    "task_id": task.id,
                    "category": task.category.value,
                    "difficulty": task.difficulty.value,
                    "expected_files": task.expected_files,
                },
                status="PENDING",
            )
            session.add(task_model)
            session.flush()
            return task_model

    async def _run_script(self, script: str) -> None:
        """Executa um script de setup/verificação."""
        # Executa em subprocesso isolado
        proc = await asyncio.create_subprocess_shell(
            script,
            cwd=self._project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(_SCRIPT_FAILED.format(stderr=stderr.decode()))

    async def _wait_for_completion(self, run_id: str, timeout: int) -> dict[str, Any]:
        """Aguarda a conclusão da execução."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            with session_scope(self._db_path) as session:
                run = session.query(ExecutionRunModel).get(uuid.UUID(run_id))
                if run and run.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                    return {"success": run.status == "COMPLETED", "error": None}
            await asyncio.sleep(1)
        return {"success": False, "error": "Timeout"}

    async def _evaluate_result(
        self,
        task: BenchmarkTask,
        result: dict[str, Any],
        metrics: BenchmarkMetrics,
    ) -> None:
        """Avalia o resultado contra os critérios de aceite."""
        # Implementação simplificada - em produção, faria verificação real
        metrics.task_completed = result.get("success", False)
        metrics.requirements_total = len(task.acceptance_criteria)
        metrics.requirements_satisfied = metrics.requirements_total if result.get("success") else 0

    async def _cleanup_run(self, run_id: str) -> None:
        """Limpa recursos da execução."""

    async def run_benchmark(
        self,
        tasks_file: str,
        orchestrator: RunOrchestrator,
        _parallel: int = 1,
    ) -> list[BenchmarkResult]:
        """Executa o benchmark completo.

        Args:
            tasks_file: arquivo com definição das tarefas.
            orchestrator: orquestrador a usar.
            parallel: número de tarefas paralelas (padrão 1).

        Returns:
            Lista de resultados.
        """
        tasks = self._load_tasks(tasks_file)
        results = []

        # Executa sequencialmente por padrão
        for task in tasks:
            print(f"Executando tarefa: {task.id} ({task.category.value})")
            result = await self.run_task(task, orchestrator)
            results.append(result)

            # Salva resultado intermediário
            self._save_result(result)

        # Gera relatório final
        self._generate_report(results)

        return results

    def _save_result(self, result: BenchmarkResult) -> None:
        """Salva resultado individual."""
        output_file = self._output_dir / f"result_{result.task_id}_{result.run_id[:8]}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2, ensure_ascii=False, default=str)

    def _generate_report(self, results: list[BenchmarkResult]) -> None:
        """Gera relatório final."""
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_tasks": len(results),
            "successful": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "by_category": {},
            "by_difficulty": {},
            "aggregate_metrics": self._aggregate_metrics(results),
            "results": [asdict(r) for r in results],
        }

        # Agrupa por categoria
        for r in results:
            cat = r.task.category.value
            if cat not in report["by_category"]:
                report["by_category"][cat] = {"total": 0, "success": 0}
            report["by_category"][cat]["total"] += 1
            if r.success:
                report["by_category"][cat]["success"] += 1

        # Agrupa por dificuldade
        for r in results:
            diff = r.task.difficulty.value
            if diff not in report["by_difficulty"]:
                report["by_difficulty"][diff] = {"total": 0, "success": 0}
            report["by_difficulty"][diff]["total"] += 1
            if r.success:
                report["by_difficulty"][diff]["success"] += 1

        output_file = self._output_dir / "benchmark_report.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"Relatório salvo em: {output_file}")

    def _aggregate_metrics(self, results: list[BenchmarkResult]) -> dict[str, Any]:
        """Agrega métricas de todos os resultados."""
        if not results:
            return {}

        successful = [r for r in results if r.success]
        [r for r in results if not r.success]

        return {
            "success_rate": len(successful) / len(results),
            "avg_tokens": sum(r.metrics.total_tokens for r in successful) / len(successful) if successful else 0,
            "avg_time_seconds": sum(r.metrics.total_time_seconds for r in successful) / len(successful)
            if successful
            else 0,
            "avg_inferences": sum(r.metrics.inference_count for r in successful) / len(successful) if successful else 0,
            "recovery_rate": sum(r.metrics.recovery_count for r in successful) / len(successful) if successful else 0,
        }


# Tarefas de exemplo para benchmark
SAMPLE_TASKS = {
    "tasks": [
        {
            "id": "bench_code_search_01",
            "category": "code_search",
            "difficulty": "easy",
            "objective": "Encontre a função que valida o token de autenticação",
            "acceptance_criteria": [
                "Identificar o arquivo correto",
                "Explicar a lógica de validação",
                "Listar dependências",
            ],
            "expected_files": ["src/auth/validator.py"],
        },
        {
            "id": "bench_bug_fix_01",
            "category": "bug_fix",
            "difficulty": "medium",
            "objective": "Corrija o vazamento de memória no cache de sessões",
            "acceptance_criteria": [
                "Identificar a causa do vazamento",
                "Implementar a correção",
                "Adicionar teste de regressão",
            ],
            "expected_files": ["src/cache/session_cache.py"],
        },
        {
            "id": "bench_feature_add_01",
            "category": "feature_add",
            "difficulty": "hard",
            "objective": "Adicione suporte a autenticação de dois fatores",
            "acceptance_criteria": [
                "Implementar modelo de dados",
                "Criar endpoints de ativação/verificação",
                "Adicionar testes de integração",
                "Atualizar documentação",
            ],
            "expected_files": ["src/auth/tfa.py", "src/api/auth_routes.py"],
        },
    ],
}


def create_benchmark_runner(
    project_root: str,
    db_path: str,
    output_dir: str,
) -> BenchmarkRunner:
    """Factory para criar o runner de benchmark.

    Args:
        project_root: raiz do projeto.
        db_path: caminho do banco de dados.
        output_dir: diretório de saída.

    Returns:
        Instância do BenchmarkRunner.
    """
    return BenchmarkRunner(project_root, db_path, output_dir)
