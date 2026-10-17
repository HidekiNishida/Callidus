# tests/test_persistence.py — persistência e recuperação
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.persistence.database import build_session_factory, init_db
from agent.config import Settings
from agent.services.project_service import ProjectService
from agent.services.task_service import DependencyError, TaskService


@pytest.fixture
def session(tmp_path: Path) -> Session:
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


def test_project_and_task_tree_survives_reopen(tmp_path: Path, session: Session):
    ps = ProjectService(session)
    project = ps.create_project(
        ProjectCreate(name="demo", root_path=str(tmp_path), description="test")
    )
    ts = TaskService(session)
    root = ts.create_task(
        project.id,
        TaskCreate(title="Objetivo", objective="Fazer X", kind="objective"),
    )
    child = ts.create_task(
        project.id,
        TaskCreate(title="Op", objective="Passo 1", parent_id=root.id, kind="operation"),
    )
    session.commit()
    project_id = project.id
    root_id = root.id
    child_id = child.id

    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess2 = factory()
    tasks = TaskService(sess2).list_tasks(project_id)
    assert len(tasks) == 2
    assert {t.id for t in tasks} == {root_id, child_id}
    sess2.close()


def test_invalid_transition_rejected(session: Session):
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective="o")
    )
    with pytest.raises(Exception):
        TaskService(session).update_status(
            task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED)
        )


def test_dependency_cycle_blocked(session: Session):
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts = TaskService(session)
    a = ts.create_task(project.id, TaskCreate(title="A", objective="a"))
    b = ts.create_task(project.id, TaskCreate(title="B", objective="b"))
    ts.add_dependency(b.id, TaskDependencyCreate(depends_on_task_id=a.id))
    with pytest.raises(DependencyError):
        ts.add_dependency(a.id, TaskDependencyCreate(depends_on_task_id=b.id))


def test_happy_path_to_completed(session: Session):
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts = TaskService(session)
    task = ts.create_task(project.id, TaskCreate(title="t", objective="o"))
    for status in [
        TaskStatus.PLANNING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.VERIFYING,
        TaskStatus.COMPLETED,
    ]:
        ts.update_status(task.id, TaskStatusUpdate(status=status))
    final = ts.get_task(task.id)
    assert final.status == TaskStatus.COMPLETED.value
    assert final.completed_at is not None
