# tests/test_proportional_verification.py — escrita gera evidência; etapa sem ação não conclui à toa
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


class _Writer:
    name = "mock"
    last_usage = None

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request):
        self.calls += 1

        class _R:
            content = '{"path": "notas.txt", "content": "lista de compras"}'

        return _R()


def _leaf(session, tmp_path: Path, metadata: dict, monkeypatch):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    leaf = tasks.create_task(
        project.id,
        TaskCreate(title="Anotar", objective="Crie notas.txt", parent_id=root.id, metadata=metadata),
    )
    leaf.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    provider = _Writer()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, leaf, provider


@pytest.mark.asyncio
async def test_write_without_declared_check_gets_an_implicit_content_check(session, tmp_path, monkeypatch):
    run, leaf, _ = _leaf(session, tmp_path, {"model_operation": True}, monkeypatch)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "verified_ok"
    evidence = session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == leaf.id)).one()
    assert evidence.verifier == "file_contains"
    assert evidence.passed is True
    assert evidence.attempt_id is not None


@pytest.mark.asyncio
async def test_step_without_action_runs_instead_of_completing_silently(session, tmp_path, monkeypatch):
    run, leaf, provider = _leaf(session, tmp_path, {"atomic": True}, monkeypatch)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] != "skipped_to_verify"
    assert provider.calls == 1
    assert (tmp_path / "notas.txt").read_text(encoding="utf-8") == "lista de compras"
    assert TaskService(session).get_task(leaf.id).metadata_json["model_operation"] is True
