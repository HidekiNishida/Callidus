# tests/test_orchestrator_recovery.py — retomada após passos parciais
import shutil
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.mark.asyncio
async def test_resume_run_after_partial_steps(tmp_path: Path):
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
        TaskCreate(title="Obj", objective="e2e corrigir calc.py"),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    orch = RunOrchestrator(session, settings)
    for _ in range(5):
        await orch.step(run.id)
    session.commit()

    session2 = factory()
    orch2 = RunOrchestrator(session2, settings)
    log = await orch2.run_until_idle(run.id, max_steps=80)
    session2.commit()

    final = TaskService(session2).get_task(root.id)
    assert final.status == TaskStatus.COMPLETED.value
    assert any(x.get("action") == "run_completed" for x in log)
    session.close()
    session2.close()


@pytest.mark.asyncio
async def test_blocked_without_contract(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    session = factory()
    (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Integrar",
            objective="Integrar módulo",
            metadata={
                "requires_contract": True,
                "tool": "read_file",
                "tool_args": {"path": "README.md"},
            },
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=task.id,
            config={"provider": "mock", "approve_risky_tools": True, "use_generic_template": False},
        ),
    )
    session.commit()
    orch = RunOrchestrator(session, settings)
    seen_block = False
    for _ in range(12):
        out = await orch.step(run.id)
        if out.get("action") == "blocked_contract":
            seen_block = True
            break
    assert seen_block
    session.close()
