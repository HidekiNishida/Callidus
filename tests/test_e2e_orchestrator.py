# tests/test_e2e_orchestrator.py — fluxo reproduzível ponta a ponta (mock)
import shutil
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.mark.asyncio
async def test_e2e_fix_calc_with_verification(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "sample_project"
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)

    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    session = factory()

    project = ProjectService(session).create_project(
        ProjectCreate(name="e2e", root_path=str(workspace))
    )
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Objetivo E2E", objective="e2e corrigir calc.py e validar"),
    )
    run = __import__("agent.services.run_service", fromlist=["RunService"]).RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root.id,
            config={"provider": "mock", "approve_risky_tools": True},
        ),
    )
    session.commit()

    orch = RunOrchestrator(session, settings)
    log = await orch.run_until_idle(run.id, max_steps=80)
    session.commit()

    assert any(x.get("action") == "decomposed" for x in log)
    final_root = TaskService(session).get_task(root.id)
    assert final_root.status == TaskStatus.COMPLETED.value

    calc = (workspace / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in calc
    assert "run_completed" in [x.get("action") for x in log] or final_root.status == TaskStatus.COMPLETED.value

    session.close()
