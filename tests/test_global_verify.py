"""
Arquivo: tests/test_global_verify.py
Nome: test_global_verify.py
Propósito: Verificar a verificação global do objetivo.
Responsabilidade: camada de testes — recusa de conclusão sem evidência e aceitação com evidência de verificação.
Componentes: verificação concluída sem evidência e verificação concluída com evidência aprovada.
Dependências: agent.orchestrator.global_verify e agent.services.task_service.
Observações: banco temporário por teste.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.global_verify import evaluate_global_acceptance, reopen_verification_gaps
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_global_rejects_completed_verify_without_evidence(session, tmp_path: Path):
    """Verificação concluída sem evidência não é aceita e volta para nova tentativa."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    root = ts.create_task(project.id, TaskCreate(title="R", objective="obj"))
    verify = ts.create_task(
        project.id,
        TaskCreate(
            title="V",
            objective="pytest",
            parent_id=root.id,
            metadata={"verification": {"type": "pytest", "path": "."}},
        ),
    )
    verify.status = TaskStatus.COMPLETED.value
    root.status = TaskStatus.COMPLETED.value
    session.flush()
    ok, _ = evaluate_global_acceptance(session, root.id)
    assert not ok
    reopened = reopen_verification_gaps(session, root.id)
    assert verify.id in reopened
    assert TaskStatus(ts.get_task(verify.id).status) == TaskStatus.RETRY_PENDING


def test_global_accepts_with_evidence(session, tmp_path: Path):
    """Com evidência de verificação aprovada, o objetivo é aceito globalmente."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    root = ts.create_task(project.id, TaskCreate(title="R", objective="obj"))
    verify = ts.create_task(
        project.id,
        TaskCreate(
            title="V",
            objective="pytest",
            parent_id=root.id,
            metadata={"verification": {"type": "pytest", "path": "."}},
        ),
    )
    verify.status = TaskStatus.COMPLETED.value
    root.status = TaskStatus.COMPLETED.value
    session.add(
        EvidenceModel(task_id=verify.id, verifier="pytest", passed=True, summary="ok")
    )
    session.flush()
    ok, reason = evaluate_global_acceptance(session, root.id)
    assert ok, reason
