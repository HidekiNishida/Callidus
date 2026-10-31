"""
Arquivo: src/agent/knowledge/ucg/model.py
Nome: model.py
Propósito: contrato de modelo do Unified Cognitive Graph — tipos de nó, tipos de relacionamento, regras de aresta e referências.
Responsabilidade: camada de aplicação — define o vocabulário tipado do UCG sem depender de FastAPI, SQLAlchemy ou HTTP, de modo que o domínio seja testável sozinho.
Componentes: GraphDomain, GraphNodeKind, GraphRelationKind, GraphDirection, GraphScope, GraphStatus, GraphRelationRule, GraphNodeRef, GraphEdgeRef.
Dependências: enum, datetime, typing, uuid.
Observações: não cria tabelas nem acessa o banco; é um contrato puro usado pela camada de consulta e pelos serviços de domínio. A expansão de tipos ocorre por registro controlado, sem espalhar condicionais pelo sistema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class GraphDomain(StrEnum):
    """Domínio lógico a que pertence um nó do UCG."""

    KNOWLEDGE = "knowledge"
    MEMORY = "memory"
    CAPABILITY = "capability"
    RESEARCH = "research"
    TASK = "task"
    AGENT = "agent"
    DECISION = "decision"
    EXECUTION = "execution"
    QUALITY = "quality"
    STRATEGY = "strategy"


class GraphNodeKind(StrEnum):
    """Tipo de nó permitido no UCG, registrado de forma controlada."""

    KNOWLEDGE = "KNOWLEDGE"
    CONCEPT = "CONCEPT"
    FILE = "FILE"
    SYMBOL = "SYMBOL"
    DOCUMENT = "DOCUMENT"
    MEMORY = "MEMORY"
    SKILL = "SKILL"
    MCP = "MCP"
    CAPABILITY = "CAPABILITY"
    TOOL = "TOOL"
    AGENT = "AGENT"
    MODEL = "MODEL"
    PROVIDER = "PROVIDER"
    PROJECT = "PROJECT"
    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    RESEARCH_SOURCE = "RESEARCH_SOURCE"
    RESEARCH_FINDING = "RESEARCH_FINDING"
    TASK = "TASK"
    EXECUTION = "EXECUTION"
    DECISION = "DECISION"
    HYPOTHESIS = "HYPOTHESIS"
    STRATEGY = "STRATEGY"
    REQUIREMENT = "REQUIREMENT"
    TEST = "TEST"
    EVIDENCE = "EVIDENCE"


class GraphRelationKind(StrEnum):
    """Vocabulário central de relacionamentos entre nós do UCG."""

    RELATED_TO = "RELATED_TO"
    DEPENDS_ON = "DEPENDS_ON"
    REQUIRES = "REQUIRES"
    SUPPORTS = "SUPPORTS"
    IMPLEMENTS = "IMPLEMENTS"
    DOCUMENTS = "DOCUMENTS"
    CONSUMES = "CONSUMES"
    PRODUCES = "PRODUCES"
    EXECUTED_BY = "EXECUTED_BY"
    VALIDATES = "VALIDATES"
    EVIDENCED_BY = "EVIDENCED_BY"
    DERIVED_FROM = "DERIVED_FROM"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    SIMILAR_TO = "SIMILAR_TO"
    DISCOVERED_BY = "DISCOVERED_BY"
    USED_IN = "USED_IN"
    APPLICABLE_TO = "APPLICABLE_TO"
    BLOCKED_BY = "BLOCKED_BY"
    CONTAINS = "CONTAINS"
    DEFINES = "DEFINES"
    IMPORTS = "IMPORTS"
    TESTS = "TESTS"
    CAPABILITY_USES_TOOL = "CAPABILITY_USES_TOOL"
    SKILL_USES_MCP = "SKILL_USES_MCP"
    CAPABILITY_VALIDATED_BY_TEST = "CAPABILITY_VALIDATED_BY_TEST"


class GraphDirection(StrEnum):
    """Direção de um relacionamento."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    UNDIRECTED = "undirected"


class GraphScope(StrEnum):
    """Escopo de isolamento de visibilidade de um nó."""

    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"
    TASK = "task"
    EXECUTION = "execution"
    AGENT = "agent"


class GraphStatus(StrEnum):
    """Status de validade de um nó."""

    ACTIVE = "active"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


class GraphRelationRule:
    """Regra de validade de um tipo de relacionamento.

    Atributos:
        relation: tipo do relacionamento.
        source_kinds: tipos de nó permitidos como origem.
        target_kinds: tipos de nó permitidos como destino.
        direction: direção padrão do relacionamento.
        cardinality: cardinalidade descritiva (ex.: "1:N", "N:N").
        expansion: se participa de expansão recursiva de consulta.
        mandatory_dependency: se participa de dependências obrigatórias do planejamento.
    """

    def __init__(
        self,
        relation: GraphRelationKind,
        source_kinds: set[GraphNodeKind],
        target_kinds: set[GraphNodeKind],
        direction: GraphDirection = GraphDirection.UNDIRECTED,
        cardinality: str = "N:N",
        expansion: bool = True,
        mandatory_dependency: bool = False,
    ) -> None:
        self.relation = relation
        self.source_kinds = set(source_kinds)
        self.target_kinds = set(target_kinds)
        self.direction = direction
        self.cardinality = cardinality
        self.expansion = expansion
        self.mandatory_dependency = mandatory_dependency

    def allows(self, source_kind: GraphNodeKind, target_kind: GraphNodeKind) -> bool:
        """Diz se a regra permite a aresta entre os tipos informados."""
        return source_kind in self.source_kinds and target_kind in self.target_kinds


#: Regras de relacionamento centralizadas. A entrada é indexada por tipo de relacionamento.
RELATION_RULES: dict[GraphRelationKind, GraphRelationRule] = {
    GraphRelationKind.RELATED_TO: GraphRelationRule(
        GraphRelationKind.RELATED_TO,
        set(GraphNodeKind),
        set(GraphNodeKind),
        GraphDirection.UNDIRECTED,
        expansion=True,
    ),
    GraphRelationKind.DEPENDS_ON: GraphRelationRule(
        GraphRelationKind.DEPENDS_ON,
        {GraphNodeKind.TASK},
        {GraphNodeKind.TASK},
        GraphDirection.OUTGOING,
        mandatory_dependency=True,
    ),
    GraphRelationKind.REQUIRES: GraphRelationRule(
        GraphRelationKind.REQUIRES,
        {GraphNodeKind.TASK},
        {GraphNodeKind.CAPABILITY, GraphNodeKind.TOOL, GraphNodeKind.MCP},
        GraphDirection.OUTGOING,
        expansion=True,
        mandatory_dependency=True,
    ),
    GraphRelationKind.SUPPORTS: GraphRelationRule(
        GraphRelationKind.SUPPORTS,
        {GraphNodeKind.CAPABILITY},
        {GraphNodeKind.TASK},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.IMPLEMENTS: GraphRelationRule(
        GraphRelationKind.IMPLEMENTS,
        {GraphNodeKind.CAPABILITY},
        {GraphNodeKind.REQUIREMENT},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.DOCUMENTS: GraphRelationRule(
        GraphRelationKind.DOCUMENTS,
        {GraphNodeKind.DOCUMENT},
        {GraphNodeKind.FILE, GraphNodeKind.SYMBOL},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.CONSUMES: GraphRelationRule(
        GraphRelationKind.CONSUMES,
        {GraphNodeKind.TASK},
        {GraphNodeKind.TOOL},
        GraphDirection.OUTGOING,
        mandatory_dependency=True,
    ),
    GraphRelationKind.PRODUCES: GraphRelationRule(
        GraphRelationKind.PRODUCES,
        {GraphNodeKind.TASK},
        {GraphNodeKind.EVIDENCE},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.EXECUTED_BY: GraphRelationRule(
        GraphRelationKind.EXECUTED_BY,
        {GraphNodeKind.TASK},
        {GraphNodeKind.AGENT},
        GraphDirection.OUTGOING,
        mandatory_dependency=True,
    ),
    GraphRelationKind.VALIDATES: GraphRelationRule(
        GraphRelationKind.VALIDATES,
        {GraphNodeKind.TEST},
        {GraphNodeKind.TASK, GraphNodeKind.REQUIREMENT},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.EVIDENCED_BY: GraphRelationRule(
        GraphRelationKind.EVIDENCED_BY,
        {GraphNodeKind.DECISION, GraphNodeKind.HYPOTHESIS},
        {GraphNodeKind.EVIDENCE, GraphNodeKind.HYPOTHESIS},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.DERIVED_FROM: GraphRelationRule(
        GraphRelationKind.DERIVED_FROM,
        set(GraphNodeKind),
        set(GraphNodeKind),
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.CONTRADICTS: GraphRelationRule(
        GraphRelationKind.CONTRADICTS,
        {GraphNodeKind.DECISION, GraphNodeKind.HYPOTHESIS},
        {GraphNodeKind.DECISION, GraphNodeKind.HYPOTHESIS},
        GraphDirection.UNDIRECTED,
    ),
    GraphRelationKind.SUPERSEDES: GraphRelationRule(
        GraphRelationKind.SUPERSEDES,
        {GraphNodeKind.MEMORY, GraphNodeKind.KNOWLEDGE},
        {GraphNodeKind.MEMORY, GraphNodeKind.KNOWLEDGE},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.SIMILAR_TO: GraphRelationRule(
        GraphRelationKind.SIMILAR_TO,
        set(GraphNodeKind),
        set(GraphNodeKind),
        GraphDirection.UNDIRECTED,
        expansion=True,
    ),
    GraphRelationKind.DISCOVERED_BY: GraphRelationRule(
        GraphRelationKind.DISCOVERED_BY,
        {GraphNodeKind.RESEARCH_FINDING},
        {GraphNodeKind.RESEARCH_SOURCE, GraphNodeKind.DOCUMENT},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.USED_IN: GraphRelationRule(
        GraphRelationKind.USED_IN,
        {GraphNodeKind.CAPABILITY, GraphNodeKind.MEMORY},
        {GraphNodeKind.TASK},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.APPLICABLE_TO: GraphRelationRule(
        GraphRelationKind.APPLICABLE_TO,
        {GraphNodeKind.CAPABILITY, GraphNodeKind.MEMORY, GraphNodeKind.REQUIREMENT},
        {GraphNodeKind.TASK, GraphNodeKind.REQUIREMENT},
        GraphDirection.OUTGOING,
    ),
    GraphRelationKind.BLOCKED_BY: GraphRelationRule(
        GraphRelationKind.BLOCKED_BY,
        {GraphNodeKind.TASK},
        {GraphNodeKind.TASK},
        GraphDirection.OUTGOING,
        mandatory_dependency=True,
    ),
    GraphRelationKind.CONTAINS: GraphRelationRule(
        GraphRelationKind.CONTAINS,
        {GraphNodeKind.PROJECT, GraphNodeKind.FILE, GraphNodeKind.DOCUMENT},
        {GraphNodeKind.FILE, GraphNodeKind.DOCUMENT, GraphNodeKind.MODULE if hasattr(GraphNodeKind, "MODULE") else GraphNodeKind.FILE},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.DEFINES: GraphRelationRule(
        GraphRelationKind.DEFINES,
        {GraphNodeKind.FILE, GraphNodeKind.DOCUMENT},
        {GraphNodeKind.FUNCTION, GraphNodeKind.CLASS, GraphNodeKind.SYMBOL},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.IMPORTS: GraphRelationRule(
        GraphRelationKind.IMPORTS,
        {GraphNodeKind.FILE},
        {GraphNodeKind.FILE, GraphNodeKind.MODULE if hasattr(GraphNodeKind, "MODULE") else GraphNodeKind.FILE},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.TESTS: GraphRelationRule(
        GraphRelationKind.TESTS,
        {GraphNodeKind.FILE},
        {GraphNodeKind.FILE, GraphNodeKind.MODULE if hasattr(GraphNodeKind, "MODULE") else GraphNodeKind.FILE},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.CAPABILITY_USES_TOOL: GraphRelationRule(
        GraphRelationKind.CAPABILITY_USES_TOOL,
        {GraphNodeKind.CAPABILITY, GraphNodeKind.SKILL},
        {GraphNodeKind.TOOL},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.SKILL_USES_MCP: GraphRelationRule(
        GraphRelationKind.SKILL_USES_MCP,
        {GraphNodeKind.SKILL},
        {GraphNodeKind.MCP},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
    GraphRelationKind.CAPABILITY_VALIDATED_BY_TEST: GraphRelationRule(
        GraphRelationKind.CAPABILITY_VALIDATED_BY_TEST,
        {GraphNodeKind.CAPABILITY, GraphNodeKind.SKILL},
        {GraphNodeKind.TEST, GraphNodeKind.EVIDENCE},
        GraphDirection.OUTGOING,
        expansion=True,
    ),
}


def relation_rule(relation: GraphRelationKind) -> GraphRelationRule:
    """Devolve a regra de validade de um tipo de relacionamento.

    Args:
        relation: tipo do relacionamento.

    Returns:
        A `GraphRelationRule` correspondente.

    Raises:
        KeyError: quando o tipo de relacionamento não está registrado.
    """
    if relation not in RELATION_RULES:
        raise KeyError(f"relacionamento não registrado: {relation}")
    return RELATION_RULES[relation]


#: Relações que participam de dependências obrigatórias do planejamento (DAG de execução).
MANDATORY_DEPENDENCY_RELATIONS: frozenset[GraphRelationKind] = frozenset(
    rule.relation
    for rule in RELATION_RULES.values()
    if rule.mandatory_dependency
)

#: Relações que participam de expansão recursiva de consulta.
EXPANSION_RELATIONS: frozenset[GraphRelationKind] = frozenset(
    rule.relation
    for rule in RELATION_RULES.values()
    if rule.expansion
)

#: Mapeamento de strings de relacionamento legado do indexador para o vocabulário do UCG.
#: Relacionamentos legados não mapeados são ignorados na travessia (não são relações válidas do UCG).
LEGACY_RELATION_MAP: dict[str, GraphRelationKind] = {
    "contains": GraphRelationKind.CONTAINS,
    "defines": GraphRelationKind.DEFINES,
    "imports": GraphRelationKind.IMPORTS,
    "tests": GraphRelationKind.TESTS,
    "documents": GraphRelationKind.DOCUMENTS,
    "related_to": GraphRelationKind.RELATED_TO,
}


def to_relation_kind(rel: str) -> GraphRelationKind | None:
    """Converte uma string de relacionamento (inclusive legado) para `GraphRelationKind`.

    Args:
        rel: string do relacionamento, como armazenada em `kg_edges.rel`.

    Returns:
        O `GraphRelationKind` correspondente, ou `None` quando não é uma relação válida do UCG.
    """
    try:
        return GraphRelationKind(rel)
    except ValueError:
        return LEGACY_RELATION_MAP.get(rel.lower())


class GraphNodeRef:
    """Referência tipada e isolada a um nó do UCG.

    Não é uma entidade persistida por si só: aponta para a linha de origem na
    tabela de seu domínio (ex.: `KgNodeModel`, `MemoryRecordModel`, `TaskModel`).
    """

    def __init__(
        self,
        id: UUID,
        domain: GraphDomain,
        kind: GraphNodeKind,
        source_system: str,
        source_id: str | UUID,
        project_id: UUID | None = None,
        scope: GraphScope = GraphScope.PROJECT,
        version: int = 1,
        status: GraphStatus = GraphStatus.ACTIVE,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.domain = domain
        self.kind = kind
        self.source_system = source_system
        self.source_id = str(source_id)
        self.project_id = project_id
        self.scope = scope
        self.version = version
        self.status = status
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, Any]:
        """Serializa a referência para dicionário."""
        return {
            "id": str(self.id),
            "domain": self.domain.value,
            "kind": self.kind.value,
            "source_system": self.source_system,
            "source_id": self.source_id,
            "project_id": str(self.project_id) if self.project_id else None,
            "scope": self.scope.value,
            "version": self.version,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNodeRef:
        """Reconstrói a referência a partir de um dicionário."""
        return cls(
            id=UUID(str(data["id"])),
            domain=GraphDomain(data["domain"]),
            kind=GraphNodeKind(data["kind"]),
            source_system=str(data["source_system"]),
            source_id=str(data["source_id"]),
            project_id=UUID(str(data["project_id"])) if data.get("project_id") else None,
            scope=GraphScope(data.get("scope", GraphScope.PROJECT.value)),
            version=int(data.get("version", 1)),
            status=GraphStatus(data.get("status", GraphStatus.ACTIVE.value)),
            metadata=data.get("metadata") or {},
        )


class GraphEdgeRef:
    """Referência a uma aresta do UCG entre dois nós."""

    def __init__(
        self,
        source: GraphNodeRef,
        target: GraphNodeRef,
        relation: GraphRelationKind,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.target = target
        self.relation = relation
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, Any]:
        """Serializa a aresta para dicionário."""
        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "relation": self.relation.value,
            "metadata": self.metadata,
        }


class NodeNotFoundError(LookupError):
    """Erro levantado quando um nó do UCG não é encontrado."""

    def __init__(self, node_ref: GraphNodeRef) -> None:
        self.node_ref = node_ref
        super().__init__(f"nó não encontrado: {node_ref.domain.value}:{node_ref.kind.value}:{node_ref.source_id}")


class InvalidRelationshipError(ValueError):
    """Erro levantado quando um relacionamento não é permitido entre os tipos informados."""
