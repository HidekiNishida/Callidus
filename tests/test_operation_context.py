# tests/test_operation_context.py
from pathlib import Path

import pytest

from agent.config import Settings
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
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


def test_context_snapshot_persisted(session, tmp_path: Path):
    project = ProjectService(session).create_project(
        ProjectCreate(name="ctx", root_path=str(tmp_path))
    )
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective="ajustar função calc_add")
    )
    builder = OperationContextBuilder(session)
    budget, snap = builder.build_for_task(
        project_id=project.id,
        root_path=project.root_path,
        task=task,
        profile=ModelProfile(model_id="mock", context_limit=4096),
    )
    assert budget.estimated_tokens > 0
    assert snap.id is not None
    assert snap.components_json
