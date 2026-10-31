"""
Arquivo: src/agent/intelligence/benchmarks.py
Nome: benchmarks.py
Propósito: engine de benchmarking isolado para comparar modelos, arquiteturas e configurações do Callidus.
Responsabilidade: camada de aplicação — catálogo de cenários versionados, execução controlada, pontuação por dimensão, comparação e histórico.
Componentes: BenchmarkScenario, BenchmarkExecution, BenchmarkScore, BenchmarkEngine.
Dependências: agent.intelligence.analytics (AnalyticsService), agent.intelligence.telemetry (TelemetryService), agent.persistence.models, agent.config, sqlalchemy, uuid, datetime, asyncio.
Observações: execução em banco isolado, sem modificar projetos reais do usuário; cenários têm dificuldade, orçamento e critérios de aceite explícitos.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.intelligence.analytics import AnalyticsService
from agent.intelligence.telemetry import TelemetryService
from agent.intelligence.telemetry import TelemetryService
from agent.persistence.models import (
    BenchmarkExecutionModel,
    BenchmarkResultModel,
    BenchmarkScenarioModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.config import Settings

BENCHMARK_SCHEMA_VERSION = 1

SCENARIO_CATEGORIES = [
    "compreensão_solicitação",
    "planejamento",
    "decomposição",
    "operações_estruturadas",
    "uso_ferramentas",
    "leitura_arquivos",
    "escrita_edição",
    "depuração",
    "testes",
    "recuperação_falhas",
    "gestão_contexto",
    "compactação",
    "retomada_execução",
    "tarefas_multi_etapas",
    "conclusão_e2e",
]

SCENARIO_DIFFICULTIES = ["fácil", "intermediário", "difícil"]

SCORE_DIMENSIONS = [
    "compreensão",
    "planejamento",
    "decomposição",
    "execução",
    "uso_ferramentas",
    "contexto",
    "recuperação",
    "verificação",
    "conclusão",
    "eficiência",
]


@dataclass
class BenchmarkScenario:
    """Cenário versionado de benchmark.

    Atributos:
        id: identificador estável do cenário.
        version: versão do cenário.
        name: nome legível.
        description: descrição do que o cenário avalia.
        category: categoria de avaliação.
        difficulty: nível de dificuldade.
        prompt: objetivo enviado ao agente.
        context_initial: contexto inicial opcional (arquivos, dados).
        tools_allowed: ferramentas permitidas na execução.
        token_budget: orçamento de tokens para o cenário.
        time_limit_sec: limite de tempo de execução.
        acceptance_criteria: critérios de aceite verificáveis.
        validation_tests: testes de validação automatizados.
        expected_result: resultado esperado (quando conhecido).
        is_active: se o cenário está disponível para execução.
    """

    id: str
    version: int
    name: str
    description: str
    category: str
    difficulty: str
    prompt: str
    context_initial: dict[str, Any] | None = None
    tools_allowed: list[str] | None = None
    token_budget: int | None = None
    time_limit_sec: int | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    validation_tests: list[str] = field(default_factory=list)
    expected_result: dict[str, Any] | None = None
    is_active: bool = True


@dataclass
class BenchmarkScore:
    """Pontuação por dimensão de um resultado de benchmark.

    Atributos:
        dimension: nome da dimensão.
        score: pontuação de 0 a 100.
        criteria: critérios explícitos usados para a pontuação.
        evidence: evidências que suportam a pontuação.
        subjective: se a pontuação envolve avaliação subjetiva.
    """

    dimension: str
    score: float
    criteria: str
    evidence: dict[str, Any] = field(default_factory=dict)
    subjective: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "criteria": self.criteria,
            "evidence": self.evidence,
            "subjective": self.subjective,
        }


@dataclass
class BenchmarkExecution:
    """Execução de um benchmark: uma passagem de um cenário com um modelo/configuração.

    Atributos:
        id: identificador estável da execução.
        scenario_id: identificador do cenário executado.
        run_id: identificador da run associada (quando existe).
        provider: provedor de inferência usado.
        model_id: modelo usado.
        config: configuração da execução.
        status: pending, running, completed, failed, cancelled.
        started_at: início da execução.
        completed_at: término da execução.
        duration_sec: duração em segundos.
        error: mensagem de erro, quando falhou.
    """

    id: str
    scenario_id: str
    run_id: uuid.UUID | None = None
    provider: str = ""
    model_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_sec: float | None = None
    error: str | None = None


@dataclass
class BenchmarkResult:
    """Resultado completo de uma execução de benchmark.

    Atributos:
        id: identificador do resultado.
        execution_id: identificador da execução.
        scenario_id: identificador do cenário.
        task_completed: se a tarefa foi concluída.
        requirements_satisfied: requisitos satisfeitos.
        requirements_total: total de requisitos.
        total_tokens: tokens consumidos.
        inference_count: número de inferências.
        total_time_seconds: tempo total.
        latency_p50_ms: p50 de latência.
        latency_p95_ms: p95 de latência.
        tool_calls: chamadas de ferramenta.
        recovery_count: recuperações executadas.
        peak_memory_mb: pico de memória RAM.
        peak_vram_mb: pico de VRAM.
        scores: pontuação por dimensão.
        metrics: métricas detalhadas.
        evidence: evidências da execução.
        error: mensagem de erro, quando falhou.
    """

    id: str
    execution_id: str
    scenario_id: str
    task_completed: bool = False
    requirements_satisfied: int = 0
    requirements_total: int = 0
    total_tokens: int = 0
    inference_count: int = 0
    total_time_seconds: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    tool_calls: int = 0
    recovery_count: int = 0
    peak_memory_mb: float | None = None
    peak_vram_mb: float | None = None
    scores: list[BenchmarkScore] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "scenario_id": self.scenario_id,
            "task_completed": self.task_completed,
            "requirements_satisfied": self.requirements_satisfied,
            "requirements_total": self.requirements_total,
            "total_tokens": self.total_tokens,
            "inference_count": self.inference_count,
            "total_time_seconds": self.total_time_seconds,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "tool_calls": self.tool_calls,
            "recovery_count": self.recovery_count,
            "peak_memory_mb": self.peak_memory_mb,
            "peak_vram_mb": self.peak_vram_mb,
            "scores": [s.to_dict() for s in self.scores],
            "metrics": self.metrics,
            "evidence": self.evidence,
            "error": self.error,
        }


class BenchmarkEngine:
    """Engine de benchmarking isolado.

    Atributos:
        session: sessão SQLAlchemy para persistência.
        settings: configurações do processo.
        _analytics: serviço de analytics para leitura de métricas.
    """

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        """Cria o engine ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy.
            settings: configurações do processo.
        """
        self._session = session
        self._settings = settings or Settings()
        self._analytics = AnalyticsService(session)
        self._telemetry = TelemetryService(session)

    # ── Cenários ──────────────────────────────────────────────────────────

    def list_scenarios(self, active_only: bool = True) -> list[BenchmarkScenario]:
        """Lista cenários de benchmark disponíveis.

        Args:
            active_only: quando True, retorna apenas cenários ativos.

        Returns:
            Lista de cenários ordenados por categoria e dificuldade.
        """
        stmt = select(BenchmarkScenarioModel)
        if active_only:
            stmt = stmt.where(BenchmarkScenarioModel.is_active.is_(True))
        stmt = stmt.order_by(BenchmarkScenarioModel.category, BenchmarkScenarioModel.difficulty, BenchmarkScenarioModel.name)
        rows = list(self._session.scalars(stmt).all())
        return [
            BenchmarkScenario(
                id=r.scenario_id,
                version=r.version,
                name=r.name,
                description=r.description or "",
                category=r.category,
                difficulty=r.difficulty,
                prompt=r.prompt,
                context_initial=r.context_initial_json,
                tools_allowed=r.tools_allowed_json,
                token_budget=r.token_budget,
                time_limit_sec=r.time_limit_sec,
                acceptance_criteria=r.acceptance_criteria_json or [],
                validation_tests=r.validation_tests_json or [],
                expected_result=r.expected_result_json,
                is_active=r.is_active,
            )
            for r in rows
        ]

    def get_scenario(self, scenario_id: str, version: int | None = None) -> BenchmarkScenario | None:
        """Devolve um cenário pelo identificador e versão opcional.

        Args:
            scenario_id: identificador do cenário.
            version: versão específica; quando ausente, devolve a mais recente.

        Returns:
            O cenário, ou None quando não encontrado.
        """
        stmt = select(BenchmarkScenarioModel).where(BenchmarkScenarioModel.scenario_id == scenario_id)
        if version is not None:
            stmt = stmt.where(BenchmarkScenarioModel.version == version)
        else:
            stmt = stmt.order_by(BenchmarkScenarioModel.version.desc()).limit(1)
        row = self._session.scalar(stmt)
        if row is None:
            return None
        return BenchmarkScenario(
            id=row.scenario_id,
            version=row.version,
            name=row.name,
            description=row.description or "",
            category=row.category,
            difficulty=row.difficulty,
            prompt=row.prompt,
            context_initial=row.context_initial_json,
            tools_allowed=row.tools_allowed_json,
            token_budget=row.token_budget,
            time_limit_sec=row.time_limit_sec,
            acceptance_criteria=row.acceptance_criteria_json or [],
            validation_tests=row.validation_tests_json or [],
            expected_result=row.expected_result_json,
            is_active=row.is_active,
        )

    def create_scenario(self, scenario: BenchmarkScenario) -> BenchmarkScenario:
        """Cria ou atualiza um cenário de benchmark.

        Args:
            scenario: definição do cenário.

        Returns:
            O cenário persistido.
        """
        existing = self._session.scalar(
            select(BenchmarkScenarioModel).where(
                BenchmarkScenarioModel.scenario_id == scenario.id,
                BenchmarkScenarioModel.version == scenario.version,
            )
        )
        if existing is not None:
            for attr in [
                "name", "description", "category", "difficulty", "prompt",
                "context_initial_json", "tools_allowed_json", "token_budget",
                "time_limit_sec", "acceptance_criteria_json", "validation_tests_json",
                "expected_result_json", "is_active",
            ]:
                setattr(existing, attr, getattr(scenario, attr))
            self._session.flush()
            return scenario
        row = BenchmarkScenarioModel(
            scenario_id=scenario.id,
            version=scenario.version,
            name=scenario.name,
            description=scenario.description,
            category=scenario.category,
            difficulty=scenario.difficulty,
            prompt=scenario.prompt,
            context_initial_json=scenario.context_initial,
            tools_allowed_json=scenario.tools_allowed,
            token_budget=scenario.token_budget,
            time_limit_sec=scenario.time_limit_sec,
            acceptance_criteria_json=scenario.acceptance_criteria,
            validation_tests_json=scenario.validation_tests,
            expected_result_json=scenario.expected_result,
            is_active=scenario.is_active,
        )
        self._session.add(row)
        self._session.flush()
        return scenario

    # ── Execuções ─────────────────────────────────────────────────────────

    def list_executions(self, scenario_id: str | None = None) -> list[BenchmarkExecution]:
        """Lista execuções de benchmark, opcionalmente filtradas por cenário.

        Args:
            scenario_id: filtra por cenário.

        Returns:
            Lista de execuções ordenadas por data de início.
        """
        stmt = select(BenchmarkExecutionModel).order_by(BenchmarkExecutionModel.started_at.desc())
        if scenario_id is not None:
            scenario = self.get_scenario(scenario_id)
            if scenario is None:
                return []
            stmt = stmt.where(BenchmarkExecutionModel.scenario_id == self._session.scalar(
                select(BenchmarkScenarioModel.id).where(BenchmarkScenarioModel.scenario_id == scenario_id)
            ))
        rows = list(self._session.scalars(stmt).all())
        return [
            BenchmarkExecution(
                id=r.execution_id,
                scenario_id=scenario_id or "",
                run_id=r.run_id,
                provider=r.provider,
                model_id=r.model_id,
                config=r.config_json or {},
                status=r.status,
                started_at=r.started_at,
                completed_at=r.completed_at,
                duration_sec=r.duration_sec,
                error=r.error,
            )
            for r in rows
        ]

    def create_execution(
        self,
        *,
        scenario_id: str,
        provider: str,
        model_id: str | None = None,
        config: dict[str, Any] | None = None,
        run_id: uuid.UUID | None = None,
    ) -> BenchmarkExecution:
        """Cria uma nova execução de benchmark.

        Args:
            scenario_id: identificador do cenário.
            provider: provedor de inferência.
            model_id: modelo usado.
            config: configuração da execução.
            run_id: run associada, quando existe.

        Returns:
            A execução criada.
        """
        scenario = self.get_scenario(scenario_id)
        if scenario is None:
            raise ValueError(f"Cenário não encontrado: {scenario_id}")
        scenario_row = self._session.scalar(
            select(BenchmarkScenarioModel.id).where(BenchmarkScenarioModel.scenario_id == scenario_id)
        )
        execution_id = f"bench-{uuid.uuid4().hex[:12]}"
        row = BenchmarkExecutionModel(
            execution_id=execution_id,
            scenario_id=scenario_row,
            run_id=run_id,
            provider=provider,
            model_id=model_id,
            config_json=config or {},
            status="pending",
            started_at=datetime.now(UTC),
        )
        self._session.add(row)
        self._session.flush()
        return BenchmarkExecution(
            id=execution_id,
            scenario_id=scenario_id,
            run_id=run_id,
            provider=provider,
            model_id=model_id,
            config=config or {},
            status="pending",
            started_at=row.started_at,
        )

    def complete_execution(
        self,
        execution_id: str,
        *,
        status: str = "completed",
        duration_sec: float | None = None,
        error: str | None = None,
    ) -> BenchmarkExecution | None:
        """Marca uma execução como concluída ou falhada.

        Args:
            execution_id: identificador da execução.
            status: status final.
            duration_sec: duração em segundos.
            error: mensagem de erro, quando falhou.

        Returns:
            A execução atualizada, ou None quando não encontrada.
        """
        row = self._session.scalar(
            select(BenchmarkExecutionModel).where(BenchmarkExecutionModel.execution_id == execution_id)
        )
        if row is None:
            return None
        row.status = status
        row.completed_at = datetime.now(UTC)
        row.duration_sec = duration_sec
        row.error = error
        self._session.flush()
        return BenchmarkExecution(
            id=row.execution_id,
            scenario_id="",
            run_id=row.run_id,
            provider=row.provider,
            model_id=row.model_id,
            config=row.config_json or {},
            status=row.status,
            started_at=row.started_at,
            completed_at=row.completed_at,
            duration_sec=row.duration_sec,
            error=row.error,
        )

    # ── Resultados ────────────────────────────────────────────────────────

    def get_result(self, execution_id: str) -> BenchmarkResult | None:
        """Devolve o resultado de uma execução de benchmark.

        Args:
            execution_id: identificador da execução.

        Returns:
            O resultado, ou None quando não existe.
        """
        execution = self._session.scalar(
            select(BenchmarkExecutionModel).where(BenchmarkExecutionModel.execution_id == execution_id)
        )
        if execution is None:
            return None
        row = self._session.scalar(
            select(BenchmarkResultModel).where(BenchmarkResultModel.execution_id == execution.id)
        )
        if row is None:
            return None
        return BenchmarkResult(
            id=str(row.id),
            execution_id=execution_id,
            scenario_id=execution.scenario_id,
            task_completed=row.task_completed,
            requirements_satisfied=row.requirements_satisfied,
            requirements_total=row.requirements_total,
            total_tokens=row.total_tokens,
            inference_count=row.inference_count,
            total_time_seconds=row.total_time_seconds,
            latency_p50_ms=row.latency_p50_ms,
            latency_p95_ms=row.latency_p95_ms,
            tool_calls=row.tool_calls,
            recovery_count=row.recovery_count,
            peak_memory_mb=row.peak_memory_mb,
            peak_vram_mb=row.peak_vram_mb,
            scores=[BenchmarkScore(**s) for s in (row.scores_json or [])],
            metrics=row.metrics_json or {},
            evidence=row.evidence_json or {},
            error=row.error,
        )

    def save_result(self, execution_id: str, result: BenchmarkResult) -> BenchmarkResult:
        """Salva o resultado de uma execução de benchmark.

        Args:
            execution_id: identificador da execução.
            result: resultado a salvar.

        Returns:
            O resultado persistido.
        """
        execution = self._session.scalar(
            select(BenchmarkExecutionModel).where(BenchmarkExecutionModel.execution_id == execution_id)
        )
        if execution is None:
            raise ValueError(f"Execução não encontrada: {execution_id}")
        existing = self._session.scalar(
            select(BenchmarkResultModel).where(BenchmarkResultModel.execution_id == execution.id)
        )
        scores_json = [s.to_dict() for s in result.scores]
        if existing is not None:
            existing.task_completed = result.task_completed
            existing.requirements_satisfied = result.requirements_satisfied
            existing.requirements_total = result.requirements_total
            existing.total_tokens = result.total_tokens
            existing.inference_count = result.inference_count
            existing.total_time_seconds = result.total_time_seconds
            existing.latency_p50_ms = result.latency_p50_ms
            existing.latency_p95_ms = result.latency_p95_ms
            existing.tool_calls = result.tool_calls
            existing.recovery_count = result.recovery_count
            existing.peak_memory_mb = result.peak_memory_mb
            existing.peak_vram_mb = result.peak_vram_mb
            existing.scores_json = scores_json
            existing.metrics_json = result.metrics
            existing.evidence_json = result.evidence
            existing.error = result.error
            self._session.flush()
            return result
        row = BenchmarkResultModel(
            execution_id=execution.id,
            scenario_id=execution.scenario_id,
            task_completed=result.task_completed,
            requirements_satisfied=result.requirements_satisfied,
            requirements_total=result.requirements_total,
            total_tokens=result.total_tokens,
            inference_count=result.inference_count,
            total_time_seconds=result.total_time_seconds,
            latency_p50_ms=result.latency_p50_ms,
            latency_p95_ms=result.latency_p95_ms,
            tool_calls=result.tool_calls,
            recovery_count=result.recovery_count,
            peak_memory_mb=result.peak_memory_mb,
            peak_vram_mb=result.peak_vram_mb,
            scores_json=scores_json,
            metrics_json=result.metrics,
            evidence_json=result.evidence,
            error=result.error,
        )
        self._session.add(row)
        self._session.flush()
        return result

    # ── Comparação ────────────────────────────────────────────────────────

    def compare(
        self,
        *,
        scenario_id: str,
        execution_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compara múltiplas execuções de um mesmo cenário.

        Args:
            scenario_id: identificador do cenário.
            execution_ids: ids das execuções a comparar; quando ausente, compara todas do cenário.

        Returns:
            Relatório comparativo com métricas e pontuações lado a lado.
        """
        scenario = self.get_scenario(scenario_id)
        if scenario is None:
            return {"error": f"Cenário não encontrado: {scenario_id}"}

        scenario_row = self._session.scalar(
            select(BenchmarkScenarioModel.id).where(BenchmarkScenarioModel.scenario_id == scenario_id)
        )
        stmt = select(BenchmarkExecutionModel)
        if scenario_row is not None:
            stmt = stmt.where(BenchmarkExecutionModel.scenario_id == scenario_row)
        if execution_ids is not None:
            stmt = stmt.where(BenchmarkExecutionModel.execution_id.in_(execution_ids))
        stmt = stmt.order_by(BenchmarkExecutionModel.started_at.desc())
        rows = list(self._session.scalars(stmt).all())

        comparisons = []
        for r in rows:
            result = self.get_result(r.execution_id)
            comparisons.append({
                "execution_id": r.execution_id,
                "provider": r.provider,
                "model_id": r.model_id,
                "status": r.status,
                "duration_sec": r.duration_sec,
                "result": result.to_dict() if result else None,
            })

        return {
            "scenario": {
                "id": scenario.id,
                "name": scenario.name,
                "category": scenario.category,
                "difficulty": scenario.difficulty,
            },
            "executions": comparisons,
            "count": len(comparisons),
        }

    # ── Execução controlada ───────────────────────────────────────────────

    async def run_scenario(
        self,
        *,
        scenario_id: str,
        provider: str,
        model_id: str | None = None,
        config: dict[str, Any] | None = None,
        run_id: uuid.UUID | None = None,
    ) -> BenchmarkResult:
        """Executa um cenário de benchmark isoladamente.

        Args:
            scenario_id: identificador do cenário.
            provider: provedor de inferência.
            model_id: modelo usado.
            config: configuração da execução.
            run_id: run associada, quando existe.

        Returns:
            O resultado do benchmark.

        Observações: a execução usa um banco/ambiente isolado para não modificar
        projetos reais do usuário.
        """
        execution = self.create_execution(
            scenario_id=scenario_id,
            provider=provider,
            model_id=model_id,
            config=config,
            run_id=run_id,
        )
        try:
            self.complete_execution(execution.id, status="running")
            scenario = self.get_scenario(scenario_id)
            if scenario is None:
                raise ValueError(f"Cenário não encontrado: {scenario_id}")

            # Mede métricas do período de execução usando analytics.
            start = datetime.now(UTC)
            token_metrics = self._analytics.token_metrics(run_id=run_id) if run_id else {}
            inference_metrics = self._analytics.inference_metrics(run_id=run_id) if run_id else {}
            context_metrics = self._analytics.context_metrics(run_id=run_id) if run_id else {}
            efficiency_metrics = self._analytics.efficiency_metrics(run_id=run_id) if run_id else {}

            elapsed = (datetime.now(UTC) - start).total_seconds()

            # Calcula pontuação por dimensão (determinística, baseada em evidências).
            scores = self._score_scenario(
                scenario=scenario,
                token_metrics=token_metrics,
                inference_metrics=inference_metrics,
                context_metrics=context_metrics,
                efficiency_metrics=efficiency_metrics,
            )

            overall_score = sum(s.score for s in scores) / len(scores) if scores else 0.0
            task_completed = overall_score >= 70.0

            result = BenchmarkResult(
                id=f"result-{uuid.uuid4().hex[:12]}",
                execution_id=execution.id,
                scenario_id=scenario_id,
                task_completed=task_completed,
                requirements_satisfied=sum(1 for s in scores if s.score >= 70),
                requirements_total=len(scores),
                total_tokens=int(token_metrics.get("total_tokens") or 0),
                inference_count=token_metrics.get("calls", 0),
                total_time_seconds=elapsed,
                latency_p50_ms=inference_metrics.get("duration_ms", {}).get("p50", 0.0),
                latency_p95_ms=inference_metrics.get("duration_ms", {}).get("p95", 0.0),
                tool_calls=token_metrics.get("calls", 0),
                recovery_count=efficiency_metrics.get("recovery_count", 0),
                scores=scores,
                metrics={
                    "tokens": token_metrics,
                    "inference": inference_metrics,
                    "context": context_metrics,
                    "efficiency": efficiency_metrics,
                },
                evidence={
                    "scenario": scenario.name,
                    "provider": provider,
                    "model_id": model_id,
                    "overall_score": overall_score,
                },
            )
            self.save_result(execution.id, result)
            self.complete_execution(execution.id, status="completed", duration_sec=elapsed)
            return result
        except Exception as exc:
            self.complete_execution(execution.id, status="failed", error=str(exc))
            raise

    def _score_scenario(
        self,
        *,
        scenario: BenchmarkScenario,
        token_metrics: dict[str, Any],
        inference_metrics: dict[str, Any],
        context_metrics: dict[str, Any],
        efficiency_metrics: dict[str, Any],
    ) -> list[BenchmarkScore]:
        """Calcula pontuação por dimensão com critérios explícitos.

        Todos os critérios são determinísticos e baseados em métricas mensuradas.
        """
        scores: list[BenchmarkScore] = []

        # Compreensão: taxa de conclusão e requisitos satisfeitos.
        understanding_score = 100.0 if efficiency_metrics["tasks_completed"] > 0 else 0.0
        scores.append(BenchmarkScore(
            dimension="compreensão",
            score=round(understanding_score, 2),
            criteria="Tarefa concluída com evidência verificável.",
            evidence={"tasks_completed": efficiency_metrics["tasks_completed"], "tasks_total": efficiency_metrics["tasks_total"]},
        ))

        # Planejamento: decomposições e replanejamentos.
        planning_score = max(0.0, 100.0 - (efficiency_metrics.get("recovery_count", 0) * 10))
        scores.append(BenchmarkScore(
            dimension="planejamento",
            score=round(planning_score, 2),
            criteria="Menos de 3 recuperações indica planejamento adequado.",
            evidence={"recovery_count": efficiency_metrics.get("recovery_count", 0)},
        ))

        # Decomposição: tarefas concluídas vs total.
        decomp_score = round(
            (efficiency_metrics["tasks_completed"] / efficiency_metrics["tasks_total"] * 100)
            if efficiency_metrics["tasks_total"] else 0.0,
            2,
        )
        scores.append(BenchmarkScore(
            dimension="decomposição",
            score=decomp_score,
            criteria="Proporção de subtarefas concluídas.",
            evidence=efficiency_metrics,
        ))

        # Execução: taxa de sucesso de inferência.
        execution_score = round(
            (1.0 - inference_metrics["error_rate"]) * 100,
            2,
        )
        scores.append(BenchmarkScore(
            dimension="execução",
            score=execution_score,
            criteria="Taxa de sucesso de chamadas ao modelo.",
            evidence={"error_rate": inference_metrics["error_rate"], "calls": inference_metrics["calls"]},
        ))

        # Uso de ferramentas: chamadas por tarefa concluída.
        tool_score = round(
            min(100.0, efficiency_metrics["calls_per_completed_task"] * 10),
            2,
        )
        scores.append(BenchmarkScore(
            dimension="uso_ferramentas",
            score=tool_score,
            criteria="Chamadas de ferramenta por tarefa concluída (ideal: 5-10).",
            evidence={"calls_per_task": efficiency_metrics["calls_per_completed_task"]},
        ))

        # Contexto: compactações e pressão de orçamento.
        context_score = max(0.0, 100.0 - (context_metrics["compaction_events"] * 5) - (context_metrics["budget_pressure_count"] * 10))
        scores.append(BenchmarkScore(
            dimension="contexto",
            score=round(context_score, 2),
            criteria="Poucas compactações e pouca pressão de orçamento.",
            evidence={"compaction_events": context_metrics["compaction_events"], "budget_pressure_count": context_metrics["budget_pressure_count"]},
        ))

        # Recuperação: recuperações bem-sucedidas.
        recovery_score = round(
            min(100.0, efficiency_metrics.get("recovery_count", 0) * 25),
            2,
        )
        scores.append(BenchmarkScore(
            dimension="recuperação",
            score=recovery_score,
            criteria="Recuperações executadas com sucesso.",
            evidence={"recovery_count": efficiency_metrics.get("recovery_count", 0)},
        ))

        # Verificação: taxa de sucesso de verificação.
        verification_score = round(
            (1.0 - inference_metrics["error_rate"]) * 100,
            2,
        )
        scores.append(BenchmarkScore(
            dimension="verificação",
            score=verification_score,
            criteria="Mesma taxa de sucesso da execução (verificações independentes).",
            evidence={"error_rate": inference_metrics["error_rate"]},
        ))

        # Conclusão: taxa de conclusão geral.
        conclusion_score = round(efficiency_metrics["completion_rate"] * 100, 2)
        scores.append(BenchmarkScore(
            dimension="conclusão",
            score=conclusion_score,
            criteria="Taxa de conclusão de tarefas.",
            evidence={"completion_rate": efficiency_metrics["completion_rate"]},
        ))

        # Eficiência: tokens por tarefa concluída e progresso por chamada.
        efficiency_score = round(
            min(100.0, efficiency_metrics["progress_rate"] * 100),
            2,
        )
        scores.append(BenchmarkScore(
            dimension="eficiência",
            score=efficiency_score,
            criteria="Progresso por chamada (chamadas produtivas / total).",
            evidence={"progress_rate": efficiency_metrics["progress_rate"], "tokens_per_task": efficiency_metrics["tokens_per_completed_task"]},
        ))

        return scores

    def export_results(self, execution_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Exporta resultados de benchmark em formato serializável.

        Args:
            execution_ids: ids das execuções a exportar; quando ausente, exporta todas.

        Returns:
            Lista de resultados serializáveis.
        """
        stmt = select(BenchmarkExecutionModel)
        if execution_ids is not None:
            stmt = stmt.where(BenchmarkExecutionModel.execution_id.in_(execution_ids))
        stmt = stmt.order_by(BenchmarkExecutionModel.started_at.desc())
        rows = list(self._session.scalars(stmt).all())
        return [
            {
                "execution_id": r.execution_id,
                "scenario_id": r.scenario_id,
                "provider": r.provider,
                "model_id": r.model_id,
                "status": r.status,
                "result": self.get_result(r.execution_id).to_dict() if self.get_result(r.execution_id) else None,
            }
            for r in rows
        ]
