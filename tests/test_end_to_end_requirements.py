"""
Arquivo: tests/test_end_to_end_requirements.py
Nome: test_end_to_end_requirements.py
Propósito: Verificar, de ponta a ponta, um objetivo de múltiplos passos com um único reparo até a aceitação global.
Responsabilidade: camada de testes — requisitos derivados do objetivo, correção orientada por falha e encerramento aceito globalmente.
Componentes: objetivo de múltiplos passos que termina em aceitação global verificada.
Dependências: agent.orchestrator.runner, agent.orchestrator.requirements e agent.services.metrics_service.
Observações: o fixture sample_project é copiado para tmp_path, o banco é temporário e o modelo é determinístico.
"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.requirements import ensure_requirements
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, ExecutionRunModel
from agent.services.metrics_service import MetricsService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

BUGGY = "def add(a: int, b: int) -> int:\n    return a * b\n"
FIXED = "def add(a: int, b: int) -> int:\n    return a + b\n"


class _Developer:
    """Modelo determinístico: a primeira versão de calc.py ainda está errada; a segunda, feita com o
    motivo da falha no prompt, corrige. README e resposta final saem na primeira."""

    name = "mock"
    last_usage = None

    def __init__(self) -> None:
        """Zera a lista de prompts e o contador de tentativas de correção."""
        self.prompts: list[str] = []
        self.calc_attempts = 0

    async def chat(self, request):
        """Responde conforme o passo pedido, errando de propósito na primeira correção."""
        prompt = "\n".join(m.content for m in request.messages)
        self.prompts.append(prompt)
        if "[final]" in prompt:
            reply = "## Resultado\n\n- `calc.py` soma corretamente (testes passam).\n- `README.md` criado com o uso.\n"
        elif "[calc]" in prompt:
            self.calc_attempts += 1
            content = BUGGY if self.calc_attempts == 1 else FIXED
            reply = json.dumps({"path": "calc.py", "content": content, "summary": "pronto"})
        elif "[readme]" in prompt:
            reply = json.dumps({"path": "README.md", "content": "# Calc\n\nUse `add(a, b)`.\n", "summary": "pronto"})
        else:
            reply = "## Ok\n\n- nada a fazer.\n"

        class _R:
            """Resposta falsa que carrega a resposta montada pelo modelo falso."""
            content = reply

        return _R()


@pytest.mark.asyncio
async def test_multi_step_objective_with_one_fix_ends_in_verified_global_acceptance(tmp_path: Path, monkeypatch):
    """O objetivo com dois requisitos só é aceito globalmente depois que a falha da primeira tentativa orienta a correção."""
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(
            title="Pedido",
            objective="- corrigir a soma em calc.py\n- criar README.md com o uso",
            metadata={"global_verification": {"type": "pytest", "path": "tests"}},
        ),
    )
    root.status = TaskStatus.PLANNING.value
    reqs = ensure_requirements(session, root)
    calc = tasks.create_task(
        project.id,
        TaskCreate(
            title="Corrigir calc.py",
            objective="[calc] Corrigir a soma em calc.py",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True, "covers": ["R1"], "verification": {"type": "pytest", "path": "tests"}},
        ),
    )
    readme = tasks.create_task(
        project.id,
        TaskCreate(
            title="Criar README",
            objective="[readme] Criar README.md com o uso",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True, "covers": ["R2"]},
        ),
    )
    final = tasks.create_task(
        project.id,
        TaskCreate(title="Responder", objective="[final] Resumir o que foi feito", parent_id=root.id, metadata={"final_answer": True, "covers": []}),
    )
    for dep in (calc, readme):
        tasks.add_dependency(final.id, TaskDependencyCreate(depends_on_task_id=dep.id))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    session.commit()
    provider = _Developer()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=60)
    session.commit()
    actions = [x["action"] for x in log]

    assert [r["id"] for r in reqs] == ["R1", "R2"]
    assert actions[-1] == "run_completed", actions
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.COMPLETED.value
    assert "verify_failed" in actions and provider.calc_attempts == 2
    assert (workspace / "calc.py").read_text() == FIXED

    calc_evidence = session.scalars(
        select(EvidenceModel).where(EvidenceModel.task_id == calc.id).order_by(EvidenceModel.created_at, EvidenceModel.id)
    ).all()
    assert [e.detail_json["state"] for e in calc_evidence] == ["reprovado", "aprovado"]
    retry_prompt = [p for p in provider.prompts if "[calc]" in p][1]
    assert "verification_failed" in retry_prompt

    report = tasks.get_task(root.id).consolidated_result_json
    assert [(r["id"], r["label"]) for r in report["requirements"]] == [("R1", "comprovado"), ("R2", "comprovado")]
    global_step = next(t for t in tasks.list_tasks(project.id) if (t.metadata_json or {}).get("global_verification_step"))
    assert global_step.status == TaskStatus.COMPLETED.value and global_step.metadata_json["covers"] == ["R1", "R2"]
    assert tasks.get_task(readme.id).metadata_json["implicit_verification"]["syntax"] is True

    metrics = MetricsService(session).run_metrics(run.id)
    assert metrics["requirements"] == {"total": 2, "satisfied": 2, "unmet": [], "by_status": {"satisfied": 2}}
    assert metrics["evidence"]["failed"] == 1 and metrics["evidence"]["stale"] == 0
    assert metrics["stagnation"]["detected"] == 0 and metrics["pauses"] == []
    assert "README.md" in metrics["artifacts_validated"]
    session.close()
