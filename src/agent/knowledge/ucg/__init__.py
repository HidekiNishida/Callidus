"""
Arquivo: src/agent/knowledge/ucg/__init__.py
Nome: __init__.py
Propósito: exportar a API pública do Unified Cognitive Graph.
Responsabilidade: camada de aplicação — ponto de entrada para integração do UCG com orquestrador e serviços.
Componentes: GraphRepository, UnifiedGraphService, GraphNodeRef, GraphEdgeRef, GraphDomain, GraphNodeKind, GraphRelationKind, GraphScope, GraphStatus.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.knowledge.ucg.capability.
Observações: nenhum acesso ao banco ocorre na importação.
"""

from agent.knowledge.ucg.agent import (
    AgentGraphService,
    AgentHandoff,
    AgentProfile,
    AgentSelection,
)
from agent.knowledge.ucg.capability import (
    CapabilityCache,
    CapabilityCacheEntry,
    CapabilityGraphService,
    CapabilityRef,
    CapabilityResolver,
    DEFAULT_AVAILABILITY_TTL_SECONDS,
    DEFAULT_DISCOVERY_LIMIT,
)
from agent.knowledge.ucg.graph import (
    GraphRepository,
    InvalidRelationshipError,
    NodeNotFoundError,
    UnifiedGraphService,
)
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphEdgeRef,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
    relation_rule,
    to_relation_kind,
)
from agent.knowledge.ucg.research import (
    KnowledgeGapResolver,
    ResearchFinding,
    ResearchGap,
    ResearchSource,
)
from agent.knowledge.ucg.decision import (
    Alternative,
    DecisionGraphService,
    DecisionRecord,
    Hypothesis,
)
from agent.knowledge.ucg.quality import (
    QualityEvidence,
    QualityGraphService,
    QualityVerification,
    QualityCriterion,
)
from agent.knowledge.ucg.strategy import (
    Strategy,
    StrategyGraphService,
    StrategyResult,
)
from agent.knowledge.ucg.execution import (
    CycleError,
    ExecutionEdge,
    ExecutionGraphService,
    ExecutionNode,
)
from agent.knowledge.ucg.memory import (
    DEFAULT_MAX_AGE_DAYS,
    MemoryConflict,
    MemoryGraphService,
    MemoryNodeRef,
    MemoryValidity,
    PROMOTION_MIN_CONFIDENCE,
)
from agent.knowledge.ucg.query import (
    GraphQuery,
    GraphQueryEngine,
    GraphQueryLimit,
    GraphQueryResult,
)
from agent.knowledge.ucg.reduction import (
    ContextReduction,
    FileSelection,
    ProgressiveContextReducer,
)

__all__ = [
    "GraphRepository",
    "UnifiedGraphService",
    "NodeNotFoundError",
    "InvalidRelationshipError",
    "GraphNodeRef",
    "GraphEdgeRef",
    "GraphDomain",
    "GraphNodeKind",
    "GraphRelationKind",
    "GraphDirection",
    "GraphScope",
    "GraphStatus",
    "relation_rule",
    "to_relation_kind",
    "GraphQuery",
    "GraphQueryResult",
    "GraphQueryLimit",
    "GraphQueryEngine",
    "ContextReduction",
    "FileSelection",
    "ProgressiveContextReducer",
    "CapabilityRef",
    "CapabilityCacheEntry",
    "CapabilityCache",
    "CapabilityResolver",
    "CapabilityGraphService",
    "DEFAULT_AVAILABILITY_TTL_SECONDS",
    "DEFAULT_DISCOVERY_LIMIT",
    "DEFAULT_MAX_AGE_DAYS",
    "MemoryConflict",
    "MemoryGraphService",
    "MemoryNodeRef",
    "MemoryValidity",
    "PROMOTION_MIN_CONFIDENCE",
    "CycleError",
    "ExecutionEdge",
    "ExecutionGraphService",
    "ExecutionNode",
    "AgentGraphService",
    "AgentHandoff",
    "AgentProfile",
    "AgentSelection",
    "KnowledgeGapResolver",
    "ResearchFinding",
    "ResearchGap",
    "ResearchSource",
    "Alternative",
    "DecisionGraphService",
    "DecisionRecord",
    "Hypothesis",
    "QualityCriterion",
    "QualityEvidence",
    "QualityGraphService",
    "QualityVerification",
    "Strategy",
    "StrategyGraphService",
    "StrategyResult",
]
