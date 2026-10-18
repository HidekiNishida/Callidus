# tests/test_progress_metrics.py — progresso verificável, métricas do run e cenários ponta a ponta
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.progress import made_progress
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ExecutionRunModel
from agent.services.metrics_service import MetricsService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _start(session, root_path: Path, objective: str, config: dict | None = None):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(root_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Pedido", objective=objective))
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config=config or {"provider": "mock"})
    )
    session.commit()
    return project, root, run


def test_progress_is_verified_work_not_activity():
    assert made_progress(None, {"verified": 1, "pending": 3})
    assert not made_progress(None, {"verified": 0, "pending": 3})
    assert made_progress({"verified": 1, "pending": 3}, {"verified": 2, "pending": 3})
    assert made_progress({"verified": 1, "pending": 3}, {"verified": 1, "pending": 2})
    assert not made_progress({"verified": 1, "pending": 3}, {"verified": 1, "pending": 5})
    assert not made_progress({"verified": 2, "pending": 3}, {"verified": 1, "pending": 1})


@pytest.mark.asyncio
async def test_simple_question_is_not_over_decomposed(session, tmp_path):
    _, _, run = _start(session, tmp_path, "Que dia é hoje?")

    log = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=12)
    session.commit()

    assert log[-1]["action"] == "run_completed"
    metrics = MetricsService(session).run_metrics(run.id)
    assert metrics["tree"]["tasks"] <= 3
    assert metrics["tree"]["max_depth"] == 1
    assert metrics["decompositions"] == 1


@pytest.mark.asyncio
async def test_multi_step_objective_end_to_end_with_metrics(tmp_path: Path):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    _, root, run = _start(
        session, workspace, "e2e corrigir calc.py e validar", {"provider": "mock", "approve_risky_tools": True}
    )

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=80)
    session.commit()

    assert log[-1]["action"] == "run_completed"
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.COMPLETED.value
    metrics = MetricsService(session).run_metrics(run.id)
    assert metrics["tree"]["tasks"] >= 3
    assert metrics["decompositions"] >= 1
    assert metrics["evidence"]["passed"] >= 1
    assert metrics["evidence"]["stale"] == 0
    assert metrics["progress"]["state"]["pending"] == 0
    assert metrics["progress"]["state"]["verified"] == metrics["tree"]["by_status"]["COMPLETED"]
    assert metrics["progress"]["steps_since_progress"] <= 1
    assert metrics["time"]["elapsed_sec"] >= 0

    from agent.api.main import app
    from agent.api import deps

    app.dependency_overrides[deps.db_session] = lambda: session
    try:
        body = TestClient(app).get(f"/runs/{run.id}/metrics").json()
    finally:
        app.dependency_overrides.clear()
    assert body["decompositions"] == metrics["decompositions"]
    session.close()


def _plan(session, tmp_path: Path):
    project, root, run = _start(session, tmp_path, "Três etapas")
    tasks = TaskService(session)
    root.status = TaskStatus.PLANNING.value
    stuck = tasks.create_task(project.id, TaskCreate(title="Etapa anterior", objective="x", parent_id=root.id))
    dependent = tasks.create_task(
        project.id,
        TaskCreate(
            title="Depende da anterior",
            objective="y",
            parent_id=root.id,
            metadata={"tool": "list_dir", "tool_args": {"path": "."}},
        ),
    )
    dependent.status = TaskStatus.READY.value
    tasks.add_dependency(dependent.id, TaskDependencyCreate(depends_on_task_id=stuck.id))
    independent = tasks.create_task(
        project.id,
        TaskCreate(
            title="Independente",
            objective="z",
            parent_id=root.id,
            metadata={"tool": "list_dir", "tool_args": {"path": "."}},
        ),
    )
    independent.status = TaskStatus.READY.value
    session.commit()
    return run, dependent, independent


@pytest.mark.asyncio
async def test_independent_sibling_runs_while_dependent_waits(session, tmp_path):
    run, dependent, independent = _plan(session, tmp_path)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["task_id"] == str(independent.id)
    assert TaskService(session).get_task(dependent.id).status == TaskStatus.READY.value


class _Garbage:
    name = "mock"
    last_usage = None

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request):
        self.calls += 1

        class _R:
            content = f"não é JSON {self.calls}"

        return _R()


@pytest.mark.asyncio
async def test_more_model_calls_without_verified_work_is_not_progress(session, tmp_path, monkeypatch):
    project, root, run = _start(session, tmp_path, "Objetivo")
    root.status = TaskStatus.PLANNING.value
    change = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Escrever a.txt",
            objective="Escreva a.txt",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    session.commit()
    provider = _Garbage()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=6)
    session.commit()

    metrics = MetricsService(session).run_metrics(run.id)
    assert provider.calls >= 2
    assert metrics["progress"]["model_calls_since_progress"] == provider.calls
    assert metrics["progress"]["state"]["verified"] == 0
    assert metrics["errors_by_category"]
