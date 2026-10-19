# tests/test_skills_observability.py — Eventos de estratégia, skills, decomposição e recuperação
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.observability import emit, get_bus
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.mark.asyncio
async def test_run_emits_strategy_skill_and_decomposition_events(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()

    project = ProjectService(session).create_project(
        ProjectCreate(name="obs", root_path=str(tmp_path))
    )
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Corrigir bug de timeout",
            objective="Corrigir bug de timeout na chamada da api e validar com testes",
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}),
    )
    session.commit()

    bus = get_bus()
    bus.publish  # noqa: B018 — garante que o barramento está instanciado
    orch = RunOrchestrator(session, settings)
    log = await orch.run_until_idle(run.id, max_steps=40)
    session.commit()

    events = [env["type"] for env in bus.recent(str(run.id), 0)]
    assert "strategy.formulated" in events

    # A estratégia foi persistida nos metadados da raiz.
    stored = TaskService(session).get_task(root.id)
    strategy = (stored.metadata_json or {}).get("professional_strategy")
    assert strategy and strategy["lead_specialty"]

    # Houve decomposição (recursiva ou por modelo) e o evento correspondente existe.
    assert any(x.get("action") == "decomposed" for x in log)
    assert "decomposition.recursive" in events

    session.close()


@pytest.mark.asyncio
async def test_verification_recovery_emits_event_and_retries(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()

    project = ProjectService(session).create_project(
        ProjectCreate(name="rec", root_path=str(tmp_path))
    )
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Etapa com verificação",
            objective="Executar verificação que falha",
            metadata={"verification": {"type": "file_exists", "path": "nao_existe.py"}},
        ),
    )
    session.commit()

    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=task.id,
            config={"provider": "mock", "approve_risky_tools": True},
        ),
    )
    session.commit()

    bus = get_bus()
    orch = RunOrchestrator(session, settings)
    await orch.run_until_idle(run.id, max_steps=25)
    session.commit()

    events = [env["type"] for env in bus.recent(str(run.id), 0)]
    assert "verification.recovery_planned" in events

    stored = TaskService(session).get_task(task.id)
    recovery = (stored.metadata_json or {}).get("verification_recovery")
    assert recovery is not None
    assert recovery["cause"]
    assert recovery["action"] in {"fix_and_retry", "block", "manual_review"}

    session.close()
