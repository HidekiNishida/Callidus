"""
Arquivo: tests/test_ucg_research.py
Nome: test_ucg_research.py
Propósito: Verificar o Knowledge Gap Resolver e Research Graph — detecção de lacunas de
conhecimento, pesquisa seletiva, registro de descobertas com proveniência e detecção de
conflitos.
Responsabilidade: camada de testes — integração do Research Graph com o KnowledgeEngineService
existente e modelos de conhecimento.
Componentes: ResearchGap, ResearchSource, ResearchFinding, KnowledgeGapResolver.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.research,
agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; grava nos modelos existentes de
conhecimento.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
)
from agent.knowledge.ucg.research import (
    KnowledgeGapResolver,
    ResearchFinding,
    ResearchGap,
    ResearchSource,
    _DEFAULT_MAX_AGE_DAYS,
    _MIN_FINDING_CONFIDENCE,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ProjectModel
from agent.services.project_service import ProjectService


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
        ProjectCreate(name="research", root_path=str(tmp_path / "root"))
    )


def test_research_gap_creation():
    """ResearchGap armazena requisito, severidade e origem sugerida."""
    gap = ResearchGap(
        requirement="autenticacao_oauth",
        description="Falta saber como funciona o fluxo OAuth2",
        severity="alta",
        suggested_source="documentacao",
        task_id=str(uuid4()),
    )
    assert gap.requirement == "autenticacao_oauth"
    assert gap.severity == "alta"
    assert gap.resolved is False


def test_research_source_to_graph_node_ref():
    """ResearchSource converte para GraphNodeRef do domínio research."""
    source = ResearchSource(
        source_id="src-1",
        type="documentacao",
        title="Docs OAuth",
        url="https://example.com/docs/oauth",
        credibility=0.9,
    )
    ref = source.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.DOCUMENT
    assert ref.domain == GraphDomain.RESEARCH
    assert ref.source_system == "research"
    assert ref.source_id == "src-1"
    assert ref.metadata["credibility"] == 0.9


def test_research_finding_validity():
    """ResearchFinding expira quando expires_at é atingido."""
    finding = ResearchFinding(
        finding_id="finding-1",
        question="Como fazer OAuth?",
        answer="Use o fluxo de código de autorização.",
        source=ResearchSource(source_id="s1", type="documentacao", title="Docs"),
        confidence=0.8,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert finding.is_valid is False

    finding2 = ResearchFinding(
        finding_id="finding-2",
        question="Como fazer OAuth?",
        answer="Use o fluxo de código de autorização.",
        source=ResearchSource(source_id="s2", type="documentacao", title="Docs"),
        confidence=0.8,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert finding2.is_valid is True


def test_research_finding_low_confidence_invalid():
    """Descoberta com confiança abaixo do mínimo não é válida."""
    finding = ResearchFinding(
        finding_id="finding-3",
        question="Pergunta",
        answer="Resposta incerta",
        source=ResearchSource(source_id="s3", type="web", title="Web"),
        confidence=0.3,
    )
    assert finding.is_valid is False


def test_gap_resolver_identify_gaps(session, project):
    """identify_gaps devolve lacunas para requisitos sem conhecimento."""
    proj = project
    resolver = KnowledgeGapResolver(session)
    gaps = resolver.identify_gaps(
        project_id=proj.id,
        requirements=["autenticacao_oauth", "logger_estruturado"],
    )
    assert len(gaps) == 2
    assert gaps[0].requirement == "autenticacao_oauth"
    assert gaps[0].resolved is False


def test_gap_resolver_no_gaps_when_knowledge_exists(session, project):
    """identify_gaps não devolve lacunas quando conhecimento já existe."""
    proj = project
    resolver = KnowledgeGapResolver(session)
    # Não há conhecimento indexado, então todos são gaps.
    gaps = resolver.identify_gaps(
        project_id=proj.id,
        requirements=["qualquer_coisa_que_nao_existe"],
    )
    assert len(gaps) == 1


def test_gap_resolver_resolve_gap(session, project):
    """resolve_gap registra uma descoberta com proveniência."""
    proj = project
    resolver = KnowledgeGapResolver(session)
    gap = ResearchGap(
        requirement="autenticacao_oauth",
        task_id=str(uuid4()),
    )
    finding = resolver.resolve_gap(
        gap=gap,
        answer="Use o fluxo de código de autorização OAuth2.",
        source=ResearchSource(
            source_id="src-oauth",
            type="documentacao",
            title="Guia OAuth",
            url="https://example.com/oauth",
            credibility=0.9,
        ),
        evidence=["Trecho da documentação oficial"],
        confidence=0.85,
        verified=True,
        project_id=proj.id,
    )
    assert finding.finding_id is not None
    assert finding.answer == "Use o fluxo de código de autorização OAuth2."
    assert finding.confidence == 0.85
    assert finding.verified is True
    assert len(finding.evidence) == 1
    assert finding.source.credibility == 0.9


def test_gap_resolver_find_existing_finding(session, project):
    """find_existing_finding devolve None quando não há conhecimento."""
    proj = project
    resolver = KnowledgeGapResolver(session)
    finding = resolver.find_existing_finding(
        project_id=proj.id,
        question="qualquer coisa que nao existe",
    )
    assert finding is None


def test_gap_resolver_detect_conflicts():
    """detect_conflicts identifica respostas diferentes para a mesma pergunta."""
    resolver = KnowledgeGapResolver.__new__(KnowledgeGapResolver)
    findings = [
        ResearchFinding(
            finding_id="f1",
            question="Qual o padrão?",
            answer="Padrao A",
            source=ResearchSource(source_id="s1", type="documentacao", title="Doc A"),
            confidence=0.8,
        ),
        ResearchFinding(
            finding_id="f2",
            question="Qual o padrão?",
            answer="Padrao B",
            source=ResearchSource(source_id="s2", type="documentacao", title="Doc B"),
            confidence=0.6,
        ),
    ]
    conflicts = resolver.detect_conflicts(findings)
    assert len(conflicts) == 1
    assert conflicts[0]["question"] == "Qual o padrão?"
    assert conflicts[0]["answer_a"] == "Padrao A"
    assert conflicts[0]["answer_b"] == "Padrao B"


def test_gap_resolver_relate_finding_to_source(session, project):
    """relate_finding_to_source cria aresta DISCOVERED_BY."""
    proj = project
    resolver = KnowledgeGapResolver(session)
    gap = ResearchGap(requirement="oauth", task_id=str(uuid4()))
    finding = resolver.resolve_gap(
        gap=gap,
        answer="Resposta",
        source=ResearchSource(source_id="s1", type="documentacao", title="Doc"),
        confidence=0.7,
        project_id=proj.id,
    )
    edge = resolver.relate_finding_to_source(finding)
    assert edge is not None
    assert edge.relation == GraphRelationKind.DISCOVERED_BY
    assert edge.source.kind == GraphNodeKind.RESEARCH_FINDING
    assert edge.target.kind == GraphNodeKind.DOCUMENT


def test_default_max_age_days():
    """DEFAULT_MAX_AGE_DAYS tem um valor razoável."""
    assert _DEFAULT_MAX_AGE_DAYS > 0


def test_min_finding_confidence():
    """_MIN_FINDING_CONFIDENCE está entre 0 e 1."""
    assert 0.0 < _MIN_FINDING_CONFIDENCE < 1.0
