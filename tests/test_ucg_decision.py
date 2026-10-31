"""
Arquivo: tests/test_ucg_decision.py
Nome: test_ucg_decision.py
Propósito: Verificar o Decision Graph — registros de decisão, hipóteses, alternativas e
evidências vinculados a tarefas, permitindo retomada sem reconstrução integral.
Responsabilidade: camada de testes — integração do Decision Graph com os modelos existentes
(`MemoryRecordModel`, `EvidenceModel`, `TaskModel`).
Componentes: Hypothesis, Alternative, DecisionRecord, DecisionGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.decision,
agent.persistence.database, agent.services.project_service, agent.services.task_service.
Observações: banco temporário em tmp_path; grava em modelos existentes.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.knowledge.ucg.decision import (
    Alternative,
    DecisionGraphService,
    DecisionRecord,
    Hypothesis,
)
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
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
        ProjectCreate(name="decision", root_path=str(tmp_path / "root"))
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


def test_hypothesis_to_graph_node_ref():
    """Hypothesis converte para GraphNodeRef do domínio decision."""
    hyp = Hypothesis(
        hypothesis_id="hyp-1",
        statement="Credencial expirada",
        confidence=0.8,
        status="ativa",
        created_at=datetime.now(UTC),
    )
    ref = hyp.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.HYPOTHESIS
    assert ref.domain == GraphDomain.DECISION
    assert ref.source_system == "decision"
    assert ref.source_id == "hyp-1"
    assert ref.metadata["confidence"] == 0.8


def test_alternative_to_graph_node_ref():
    """Alternative converte para GraphNodeRef do domínio decision."""
    alt = Alternative(
        alternative_id="alt-1",
        description="Renovar credencial",
        reason="Token expirado identificado",
        accepted=True,
        confidence=0.9,
    )
    ref = alt.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.DECISION
    assert ref.domain == GraphDomain.DECISION
    assert ref.metadata["accepted"] is True
    assert ref.metadata["confidence"] == 0.9


def test_decision_record_to_graph_node_ref():
    """DecisionRecord converte para GraphNodeRef do domínio decision."""
    dec = DecisionRecord(
        decision_id="dec-1",
        problem="HTTP 401 no endpoint",
        decision="Renovar credencial antes de modificar o código",
        rationale="Token expirado identificado no retorno do provedor",
        confidence=0.9,
        status="executada",
        outcome="Nova autenticação realizada com sucesso",
    )
    ref = dec.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.DECISION
    assert ref.domain == GraphDomain.DECISION
    assert ref.metadata["problem"] == "HTTP 401 no endpoint"
    assert ref.metadata["outcome"] == "Nova autenticação realizada com sucesso"


def test_decision_record_is_decided():
    """is_decided retorna True quando a decisão não está mais pendente."""
    dec_pending = DecisionRecord(
        decision_id="dec-p",
        problem="P",
        decision="D",
        status="pendente",
    )
    assert dec_pending.is_decided is False

    dec_executed = DecisionRecord(
        decision_id="dec-e",
        problem="P",
        decision="D",
        status="executada",
    )
    assert dec_executed.is_decided is True


def test_decision_graph_record_decision(session, project):
    """record_decision persiste a decisão vinculada à tarefa."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")

    service = DecisionGraphService(session)
    dec = service.record_decision(
        decision_id="dec-1",
        task_id=str(task.id),
        problem="HTTP 401 no endpoint",
        decision="Renovar credencial",
        rationale="Token expirado",
        confidence=0.9,
        project_id=str(proj.id),
    )
    assert dec.decision_id == "dec-1"
    assert dec.problem == "HTTP 401 no endpoint"
    assert dec.decision == "Renovar credencial"
    assert dec.status == "pendente"
    assert dec.task_id == str(task.id)


def test_decision_graph_record_outcome(session, project):
    """record_outcome atualiza a decisão com o resultado observado."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = DecisionGraphService(session)
    dec = service.record_decision(
        decision_id="dec-1",
        task_id=str(task.id),
        problem="HTTP 401",
        decision="Renovar credencial",
        confidence=0.9,
        project_id=str(proj.id),
    )

    updated = service.record_outcome(
        decision_id="dec-1",
        outcome="Sucesso na autenticacao",
        evidence_ids=["ev-1"],
        verified=True,
    )
    assert updated is not None
    assert updated.outcome == "Sucesso na autenticacao"
    assert updated.status == "executada"
    assert updated.verified is True
    assert "ev-1" in updated.outcome_evidence_ids


def test_decision_graph_record_outcome_not_found(session, project):
    """record_outcome retorna None quando a decisão não existe."""
    proj = project
    service = DecisionGraphService(session)
    result = service.record_outcome(
        decision_id="dec-inexistente",
        outcome="Qualquer",
        evidence_ids=None,
    )
    assert result is None


def test_decision_graph_list_decisions_for_task(session, project):
    """list_decisions_for_task devolve decisões da tarefa ordenadas por criação."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = DecisionGraphService(session)

    service.record_decision(
        decision_id="dec-1",
        task_id=str(task.id),
        problem="Problema 1",
        decision="Decisao 1",
        confidence=0.8,
        project_id=str(proj.id),
    )
    service.record_decision(
        decision_id="dec-2",
        task_id=str(task.id),
        problem="Problema 2",
        decision="Decisao 2",
        confidence=0.9,
        project_id=str(proj.id),
    )

    decisions = service.list_decisions_for_task(task_id=str(task.id))
    assert len(decisions) == 2
    assert decisions[0].decision_id == "dec-1"
    assert decisions[1].decision_id == "dec-2"


def test_decision_graph_relate_decision_to_hypothesis(session, project):
    """relate_decision_to_hypothesis cria aresta EVIDENCED_BY."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = DecisionGraphService(session)
    dec = service.record_decision(
        decision_id="dec-1",
        task_id=str(task.id),
        problem="P",
        decision="D",
        confidence=0.8,
        project_id=str(proj.id),
    )
    hyp = Hypothesis(
        hypothesis_id="hyp-1",
        statement="Credencial expirada",
        confidence=0.7,
    )
    edge = service.relate_decision_to_hypothesis(dec, hyp)
    assert edge is not None
    assert edge.relation == GraphRelationKind.EVIDENCED_BY
    assert edge.source.kind == GraphNodeKind.DECISION
    assert edge.target.kind == GraphNodeKind.HYPOTHESIS


def test_decision_graph_relate_hypothesis_to_evidence(session, project):
    """relate_hypothesis_to_evidence cria aresta EVIDENCED_BY."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")
    service = DecisionGraphService(session)
    hyp = Hypothesis(
        hypothesis_id="hyp-1",
        statement="Credencial expirada",
        confidence=0.7,
    )
    edge = service.relate_hypothesis_to_evidence(hyp, "ev-1")
    assert edge is not None
    assert edge.relation == GraphRelationKind.EVIDENCED_BY
    assert edge.source.kind == GraphNodeKind.HYPOTHESIS
    assert edge.target.kind == GraphNodeKind.EVIDENCE
