"""
Arquivo: tests/test_ucg_model.py
Nome: test_ucg_model.py
Propósito: Verificar o contrato de modelo do Unified Cognitive Graph — tipos de nó, relacionamentos, regras de aresta e serialização de referências.
Responsabilidade: camada de testes — integridade do vocabulário tipado do UCG sem acessar o banco.
Componentes: GraphNodeRef, GraphEdgeRef, GraphDomain, GraphNodeKind, GraphRelationKind, GraphScope, GraphStatus, relation_rule, RELATION_RULES, MANDATORY_DEPENDENCY_RELATIONS, EXPANSION_RELATIONS.
Dependências: agent.knowledge.ucg.model.
Observações: testes puros, sem banco de dados.
"""

import pytest

from agent.knowledge.ucg.model import (
    EXPANSION_RELATIONS,
    GraphDirection,
    GraphDomain,
    GraphEdgeRef,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
    InvalidRelationshipError,
    MANDATORY_DEPENDENCY_RELATIONS,
    NodeNotFoundError,
    RELATION_RULES,
    relation_rule,
)


def test_node_kinds_cover_required_types():
    """Os tipos de nó incluem todos os domínios previstos pelo UCG."""
    expected = {
        GraphNodeKind.KNOWLEDGE,
        GraphNodeKind.FILE,
        GraphNodeKind.SYMBOL,
        GraphNodeKind.DOCUMENT,
        GraphNodeKind.MEMORY,
        GraphNodeKind.SKILL,
        GraphNodeKind.MCP,
        GraphNodeKind.CAPABILITY,
        GraphNodeKind.TOOL,
        GraphNodeKind.AGENT,
        GraphNodeKind.TASK,
        GraphNodeKind.DECISION,
        GraphNodeKind.EVIDENCE,
        GraphNodeKind.RESEARCH_SOURCE,
        GraphNodeKind.RESEARCH_FINDING,
    }
    assert expected.issubset(set(GraphNodeKind))


def test_relation_rules_are_registered():
    """Todas as relações mínimas estão registradas com regras válidas."""
    for rel in GraphRelationKind:
        rule = relation_rule(rel)
        assert rule.relation is rel
        assert rule.source_kinds
        assert rule.target_kinds
        assert rule.cardinality


def test_mandatory_and_expansion_relations():
    """Relações obrigatórias e de expansão são subconjuntos das registradas."""
    assert MANDATORY_DEPENDENCY_RELATIONS <= set(RELATION_RULES)
    assert EXPANSION_RELATIONS <= set(RELATION_RULES)
    assert GraphRelationKind.DEPENDS_ON in MANDATORY_DEPENDENCY_RELATIONS
    assert GraphRelationKind.REQUIRES in MANDATORY_DEPENDENCY_RELATIONS
    assert GraphRelationKind.RELATED_TO in EXPANSION_RELATIONS


def test_relation_rule_rejects_unknown():
    """Relacionamento desconhecido levanta ValueError do StrEnum."""
    with pytest.raises((KeyError, ValueError)):
        relation_rule(GraphRelationKind("UNKNOWN_RELATION"))  # type: ignore[arg-type]


def test_validate_allows_and_disallows():
    """A regra permite arestas entre tipos compatíveis e rejeita incompatíveis."""
    rule = relation_rule(GraphRelationKind.DEPENDS_ON)
    assert rule.allows(GraphNodeKind.TASK, GraphNodeKind.TASK)
    assert not rule.allows(GraphNodeKind.FILE, GraphNodeKind.TASK)

    rule = relation_rule(GraphRelationKind.DOCUMENTS)
    assert rule.allows(GraphNodeKind.DOCUMENT, GraphNodeKind.FILE)
    assert not rule.allows(GraphNodeKind.TASK, GraphNodeKind.FILE)


def test_graph_node_ref_round_trip():
    """A serialização e desserialização de GraphNodeRef preservam todos os campos."""
    import uuid

    ref = GraphNodeRef(
        id=uuid.uuid4(),
        domain=GraphDomain.KNOWLEDGE,
        kind=GraphNodeKind.FILE,
        source_system="kg",
        source_id="src/agent/knowledge/ucg/model.py",
        project_id=uuid.uuid4(),
        scope=GraphScope.PROJECT,
        version=2,
        status=GraphStatus.ACTIVE,
        metadata={"hash": "abc123"},
    )
    data = ref.to_dict()
    restored = GraphNodeRef.from_dict(data)
    assert restored.id == ref.id
    assert restored.domain == ref.domain
    assert restored.kind == ref.kind
    assert restored.source_system == ref.source_system
    assert restored.source_id == ref.source_id
    assert restored.project_id == ref.project_id
    assert restored.scope == ref.scope
    assert restored.version == ref.version
    assert restored.status == ref.status
    assert restored.metadata == ref.metadata


def test_graph_edge_ref_round_trip():
    """A serialização de GraphEdgeRef preserva origem, destino, relação e metadados."""
    import uuid

    source = GraphNodeRef(
        id=uuid.uuid4(), domain=GraphDomain.TASK, kind=GraphNodeKind.TASK,
        source_system="task", source_id="task-1",
    )
    target = GraphNodeRef(
        id=uuid.uuid4(), domain=GraphDomain.CAPABILITY, kind=GraphNodeKind.TOOL,
        source_system="tool", source_id="tool-1",
    )
    edge = GraphEdgeRef(source, target, GraphRelationKind.REQUIRES, metadata={"ttl": 300})
    data = edge.to_dict()
    assert data["relation"] == GraphRelationKind.REQUIRES.value
    assert data["source"]["source_id"] == "task-1"
    assert data["target"]["source_id"] == "tool-1"
    assert data["metadata"]["ttl"] == 300


def test_domain_and_scope_enums():
    """Domínios, escopos e status possuem os valores esperados."""
    assert GraphDomain.KNOWLEDGE.value == "knowledge"
    assert GraphDomain.MEMORY.value == "memory"
    assert GraphScope.PROJECT.value == "project"
    assert GraphScope.TASK.value == "task"
    assert GraphStatus.ACTIVE.value == "active"
    assert GraphStatus.SUPERSEDED.value == "superseded"
    assert GraphDirection.OUTGOING.value == "outgoing"
    assert GraphDirection.UNDIRECTED.value == "undirected"


def test_node_not_found_and_invalid_relationship_are_errors():
    """Exceções de domínio são instâncias dos tipos esperados."""
    import uuid

    ref = GraphNodeRef(
        id=uuid.uuid4(), domain=GraphDomain.KNOWLEDGE, kind=GraphNodeKind.FILE,
        source_system="kg", source_id="x",
    )
    err = NodeNotFoundError(ref)
    assert isinstance(err, LookupError)
    assert "x" in str(err)

    inv = InvalidRelationshipError()
    assert isinstance(inv, ValueError)
