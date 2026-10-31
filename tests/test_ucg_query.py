"""
Arquivo: tests/test_ucg_query.py
Nome: test_ucg_query.py
Propósito: Verificar o Graph Query Engine — consulta seletiva com limites de profundidade,
nós, relações, escopo, orçamento e provedor de proveniência.
Responsabilidade: camada de testes — integração do mecanismo de consulta com SQLite isolado.
Componentes: GraphQuery, GraphQueryEngine, GraphQueryResult, GraphQueryLimit.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.graph_service,
agent.knowledge.ucg.query, agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; não toca data/agent.db real.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.knowledge.ucg.model import GraphDirection, GraphNodeKind, GraphRelationKind
from agent.knowledge.ucg.query import GraphQuery, GraphQueryEngine
from agent.persistence.database import build_session_factory, init_db
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
    """Cria um projeto com módulos Python indexados no grafo de conhecimento."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def hello():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "other.py").write_text(
        "def world():\n    return 2\n", encoding="utf-8"
    )
    project = ProjectService(session).create_project(
        ProjectCreate(name="ucg-query", root_path=str(tmp_path))
    )
    KnowledgeGraphService(session).reindex(project.id, project.root_path)
    session.flush()
    return project


def test_execute_returns_facts_and_files(session, project):
    """A consulta retorna fatos conhecidos e arquivos relevantes para o objetivo."""
    engine = GraphQueryEngine(session)
    query = GraphQuery(
        intent="implement_feature",
        objective="mod",
        project_id=project.id,
        requirements=["hello"],
        max_nodes=50,
    )
    result = engine.execute(query)

    assert result.query_id is not None
    assert result.project_id == project.id
    assert result.intent == "implement_feature"
    assert isinstance(result.known_facts, list)
    assert isinstance(result.relevant_files, list)
    assert any("mod.py" in f for f in result.relevant_files)
    assert result.coverage["score"] >= 0
    assert result.nodes_visited >= 1
    assert result.executed_at is not None


def test_execute_respects_max_nodes(session, project):
    """A consulta respeita o limite máximo de nós visitados."""
    engine = GraphQueryEngine(session)
    result = engine.execute(
        GraphQuery(
            intent="implement_feature",
            objective="hello",
            project_id=project.id,
            max_nodes=1,
        )
    )
    assert result.nodes_visited <= 1
    assert result.truncated is True or result.nodes_visited == 1


def test_execute_detects_research_gap(session, project):
    """Requisitos sem cobertura nos fatos conhecidos geram lacuna de pesquisa."""
    engine = GraphQueryEngine(session)
    result = engine.execute(
        GraphQuery(
            intent="implement_feature",
            objective="hello",
            project_id=project.id,
            requirements=["autenticacao_oauth_inexistente"],
        )
    )
    assert len(result.research_gaps) >= 1
    assert result.research_gaps[0]["requirement"] == "autenticacao_oauth_inexistente"


def test_execute_isolated_by_project(session, tmp_path: Path):
    """Consultas não vazam dados de outro projeto (isolamento de escopo)."""
    other = ProjectService(session).create_project(
        ProjectCreate(name="outro", root_path=str(tmp_path / "outro"))
    )
    engine = GraphQueryEngine(session)
    result = engine.execute(
        GraphQuery(
            intent="implement_feature",
            objective="hello",
            project_id=other.id,
        )
    )
    assert result.project_id == other.id
    # Sem nós indexados no outro projeto: nenhum fato.
    assert result.known_facts == []
    assert result.relevant_files == []


def test_empty_objective_returns_low_confidence(session, project):
    """Objetivo vazio resulta em resultado sem fato e confiança baixa."""
    engine = GraphQueryEngine(session)
    result = engine.execute(
        GraphQuery(intent="vazio", objective="   ", project_id=project.id)
    )
    assert result.known_facts == []
    assert result.confidence["level"] == "baixa"


def test_unknown_project_returns_empty(session):
    """Consulta para projeto sem nós indexados retorna resultado vazio."""
    engine = GraphQueryEngine(session)
    result = engine.execute(
        GraphQuery(intent="x", objective="qualquer coisa", project_id=uuid4())
    )
    assert result.known_facts == []
    assert result.nodes_visited == 0


def test_known_relation_kinds_are_expansive():
    """Relações de expansão padrão incluem as esperadas."""
    from agent.knowledge.ucg.model import EXPANSION_RELATIONS, relation_rule

    assert GraphRelationKind.RELATED_TO in EXPANSION_RELATIONS
    assert relation_rule(GraphRelationKind.DEFINES).expansion is True
