"""
Arquivo: tests/test_ucg_quality.py
Nome: test_ucg_quality.py
Propósito: Verificar o Quality Graph — critérios de qualidade antecipados, evidências
rastreáveis e verificações vinculadas a tarefas.
Responsabilidade: camada de testes — integração do Quality Graph com os modelos existentes
(`MemoryRecordModel`, `EvidenceModel`, `TaskModel`).
Componentes: QualityCriterion, QualityEvidence, QualityVerification, QualityGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.quality,
agent.persistence.database, agent.services.project_service, agent.services.task_service.
Observações: banco temporário em tmp_path; grava em modelos existentes.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
)
from agent.knowledge.ucg.quality import (
    QualityEvidence,
    QualityGraphService,
    QualityCriterion,
    QualityVerification,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import TaskModel
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


@pytest.fixture
def project(session, tmp_path: Path):
    """Cria um projeto."""
    return ProjectService(session).create_project(
        ProjectCreate(name="quality", root_path=str(tmp_path / "root"))
    )


def _create_task(session, project, title, objective, status="PENDING"):
    """Cria uma tarefa e devolve o modelo."""
    return TaskService(session).create_task(
        project.id,
        TaskCreate(
            title=title,
            objective=objective,
            kind="operation",
        ),
    )


def test_quality_criterion_to_graph_node_ref():
    """QualityCriterion converte para GraphNodeRef do domínio quality."""
    crit = QualityCriterion(
        criterion_id="crit-1",
        title="Login funcional",
        description="Login com credenciais válidas deve funcionar",
        importance="critico",
        verification_type="pytest",
        acceptance_criteria="Teste de login válido passa",
        task_id=str(uuid4()),
    )
    ref = crit.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.REQUIREMENT
    assert ref.domain == GraphDomain.QUALITY
    assert ref.source_system == "quality"
    assert ref.source_id == "crit-1"
    assert ref.metadata["importance"] == "critico"
    assert crit.is_approved is False


def test_quality_criterion_is_approved():
    """is_approved retorna True quando aprovado com confiança suficiente."""
    crit = QualityCriterion(
        criterion_id="crit-1",
        title="Login",
        description="Login funciona",
        status="aprovado",
        confidence=0.8,
    )
    assert crit.is_approved is True

    crit2 = QualityCriterion(
        criterion_id="crit-2",
        title="Login",
        description="Login funciona",
        status="aprovado",
        confidence=0.5,
    )
    assert crit2.is_approved is False


def test_quality_evidence_to_graph_node_ref():
    """QualityEvidence converte para GraphNodeRef do domínio quality."""
    ev = QualityEvidence(
        evidence_id="ev-1",
        criterion_id="crit-1",
        artifact="src/auth/login.py",
        verification_type="pytest",
        passed=True,
        summary="Todos os testes de login passaram",
    )
    ref = ev.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.EVIDENCE
    assert ref.domain == GraphDomain.QUALITY
    assert ref.metadata["passed"] is True
    assert ref.metadata["artifact"] == "src/auth/login.py"


def test_quality_graph_register_criterion(session, project):
    """register_criterion persiste um critério vinculado à tarefa."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = QualityGraphService(session)
    crit = service.register_criterion(
        criterion_id="crit-1",
        task_id=str(task.id),
        title="Login funcional",
        description="Login com credenciais válidas deve funcionar",
        importance="critico",
        verification_type="pytest",
        acceptance_criteria="Teste de login válido passa",
        project_id=str(proj.id),
    )
    assert crit.criterion_id == "crit-1"
    assert crit.title == "Login funcional"
    assert crit.importance == "critico"
    assert crit.status == "pendente"


def test_quality_graph_record_evidence(session, project):
    """record_evidence registra uma evidência vinculada a um critério."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = QualityGraphService(session)
    ev = service.record_evidence(
        evidence_id="ev-1",
        criterion_id="crit-1",
        artifact="src/auth/login.py",
        verification_type="pytest",
        passed=True,
        summary="Testes de login passaram",
        task_id=str(task.id),
        project_id=str(proj.id),
    )
    assert ev.evidence_id == "ev-1"
    assert ev.criterion_id == "crit-1"
    assert ev.passed is True
    assert ev.artifact == "src/auth/login.py"


def test_quality_graph_list_criteria_for_task(session, project):
    """list_criteria_for_task devolve critérios da tarefa ordenados por criação."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = QualityGraphService(session)

    service.register_criterion(
        criterion_id="crit-1",
        task_id=str(task.id),
        title="Critério 1",
        description="Descricao 1",
        project_id=str(proj.id),
    )
    service.register_criterion(
        criterion_id="crit-2",
        task_id=str(task.id),
        title="Critério 2",
        description="Descricao 2",
        project_id=str(proj.id),
    )

    criteria = service.list_criteria_for_task(task_id=str(task.id))
    assert len(criteria) == 2
    assert criteria[0].criterion_id == "crit-1"
    assert criteria[1].criterion_id == "crit-2"


def test_quality_graph_relate_criterion_to_task(session, project):
    """relate_criterion_to_task cria aresta APPLICABLE_TO."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = QualityGraphService(session)
    crit = service.register_criterion(
        criterion_id="crit-1",
        task_id=str(task.id),
        title="Critério 1",
        description="Descricao 1",
        project_id=str(proj.id),
    )
    edge = service.relate_criterion_to_task(crit, str(task.id))
    assert edge is not None
    assert edge.relation == GraphRelationKind.APPLICABLE_TO
    assert edge.source.kind == GraphNodeKind.REQUIREMENT
    assert edge.target.kind == GraphNodeKind.TASK
