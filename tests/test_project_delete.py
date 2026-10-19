# tests/test_project_delete.py — remoção de projeto em cascata
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings
from agent.domain.schemas import ConversationCreate, ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    ConversationModel,
    EvidenceModel,
    EventLogModel,
    ExecutionRunModel,
    KgNodeModel,
    MemoryRecordModel,
    OperationAttemptModel,
    ProjectModel,
    TaskModel,
)
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def env(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(
        ProjectCreate(name="proj", root_path=str(tmp_path)), origin="chosen"
    )
    conversation = ConversationService(session).create_conversation(
        project.id, ConversationCreate(title="c")
    )
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="root", objective="o", conversation_id=conversation.id)
    )
    child = TaskService(session).create_task(
        project.id,
        TaskCreate(title="child", objective="o", conversation_id=conversation.id, parent_id=root.id),
    )
    RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={}))
    session.add(KgNodeModel(project_id=project.id, kind="file", ref="a.py", label="a.py"))
    session.commit()
    return session, project, conversation, child


def test_delete_project_removes_everything_owned_by_it(env):
    session, project, conversation, child = env
    result = ProjectService(session).delete_project(project.id)
    session.commit()

    assert result["deleted"] is True
    assert result["conversations"] == 1
    assert session.get(ProjectModel, project.id) is None
    assert session.get(ConversationModel, conversation.id) is None
    assert session.get(TaskModel, child.id) is None
    assert session.query(MemoryRecordModel).filter(MemoryRecordModel.project_id == project.id).count() == 0
    assert session.query(KgNodeModel).filter(KgNodeModel.project_id == project.id).count() == 0
    assert session.query(EventLogModel).filter(EventLogModel.project_id == project.id).count() == 0


def test_delete_project_with_attempts_and_evidence_does_not_break_foreign_keys(env):
    """Regressão: `evidences` aponta para `operation_attempts`; apagar a tentativa antes da
    evidência viola a FOREIGN KEY e a remoção do projeto falhava com 500."""
    session, project, _conversation, child = env
    run = session.query(ExecutionRunModel).filter(ExecutionRunModel.project_id == project.id).one()
    attempt = OperationAttemptModel(run_id=run.id, task_id=child.id, kind="tool_call", success=True)
    session.add(attempt)
    session.flush()
    session.add(
        EvidenceModel(
            task_id=child.id,
            attempt_id=attempt.id,
            verifier="run_tests",
            passed=True,
            summary="ok",
        )
    )
    session.commit()

    ProjectService(session).delete_project(project.id)
    session.commit()

    assert session.query(EvidenceModel).filter(EvidenceModel.task_id == child.id).count() == 0
    assert session.query(OperationAttemptModel).filter(OperationAttemptModel.task_id == child.id).count() == 0
    assert session.get(ProjectModel, project.id) is None


def test_delete_project_keeps_the_files_on_disk(env, tmp_path: Path):
    session, project, _conversation, _child = env
    marker = tmp_path / "importante.txt"
    marker.write_text("não pode sumir", encoding="utf-8")

    ProjectService(session).delete_project(project.id)
    session.commit()

    assert marker.is_file()


def test_delete_project_api(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as client:
        created = client.post("/projects", json={"name": "pra apagar", "root_path": str(tmp_path)})
        assert created.status_code == 200
        project_id = created.json()["id"]
        removed = client.delete(f"/projects/{project_id}")
        assert removed.status_code == 200
        assert removed.json()["deleted"] is True
        assert client.get(f"/projects/{project_id}").status_code == 404
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def test_delete_unknown_project_is_404(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as client:
        assert client.delete("/projects/00000000-0000-0000-0000-000000000000").status_code == 404
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None
