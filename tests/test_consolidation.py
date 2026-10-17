# tests/test_consolidation.py
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import consolidate_parent
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_parent_not_completed_without_verification_evidence(session, tmp_path: Path):
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    parent = ts.create_task(project.id, TaskCreate(title="P", objective="obj"))
    child = ts.create_task(
        project.id,
        TaskCreate(
            title="V",
            objective="verificar",
            parent_id=parent.id,
            metadata={"verification": {"type": "pytest", "path": "."}},
        ),
    )
    child.status = TaskStatus.COMPLETED.value
    parent.status = TaskStatus.VERIFYING.value
    session.flush()
    report = consolidate_parent(session, parent.id)
    assert report is not None
    assert report["achieved"] is False
    assert TaskStatus(ts.get_task(parent.id).status) == TaskStatus.PLANNING
    assert TaskStatus(ts.get_task(child.id).status) == TaskStatus.RETRY_PENDING


def test_parent_completed_when_evidence_present(session, tmp_path: Path):
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    parent = ts.create_task(project.id, TaskCreate(title="P", objective="obj"))
    child = ts.create_task(
        project.id,
        TaskCreate(
            title="V",
            objective="verificar",
            parent_id=parent.id,
            metadata={"verification": {"type": "pytest", "path": "."}},
        ),
    )
    child.status = TaskStatus.COMPLETED.value
    parent.status = TaskStatus.VERIFYING.value
    session.add(
        EvidenceModel(task_id=child.id, verifier="pytest", passed=True, summary="ok")
    )
    session.flush()
    report = consolidate_parent(session, parent.id)
    assert report["achieved"] is True
    assert TaskStatus(ts.get_task(parent.id).status) == TaskStatus.COMPLETED
