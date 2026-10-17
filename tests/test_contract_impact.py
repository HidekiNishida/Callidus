# tests/test_contract_impact.py
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.services.contract_service import ContractService
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


def test_contract_change_finds_dependent_tasks(session, tmp_path: Path):
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    producer = ts.create_task(
        project.id, TaskCreate(title="Auth", objective="Definir serviço auth")
    )
    consumer = ts.create_task(
        project.id,
        TaskCreate(title="Login UI", objective="Integrar com auth.py na interface"),
    )
    cs = ContractService(session)
    out = cs.upsert_with_impact(
        producer.id,
        outputs={"type": "AuthResult", "files": ["auth.py"]},
    )
    assert str(consumer.id) in out["impacted_task_ids"]
