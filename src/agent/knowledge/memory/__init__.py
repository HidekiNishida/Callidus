"""
Arquivo: src/agent/knowledge/memory/__init__.py
Nome: __init__.py
Propósito: exportar a API de memória de conhecimento.
Responsabilidade: camada de aplicação — armazenamento, indexação, deduplicação, reutilização.
"""
"""
Arquivo: src/agent/knowledge/memory/__init__.py
Nome: __init__.py
Propósito: exporta a API de memória de conhecimento.
Responsabilidade: camada de aplicação — armazenamento, indexação, deduplicação, reutilização.
"""
from agent.knowledge.memory.store import (
    KnowledgeMemoryStore,
    KnowledgeIndexer,
    Deduplicator,
)
from agent.knowledge.memory.reuse import (
    KnowledgeReuser,
    ContextualRetriever,
    BudgetAwareInjector,
    RetrievedKnowledge,
    RetrievalResult,
)

__all__ = [
    "KnowledgeMemoryStore",
    "KnowledgeIndexer",
    "Deduplicator",
    "KnowledgeReuser",
    "ContextualRetriever",
    "BudgetAwareInjector",
    "RetrievedKnowledge",
    "RetrievalResult",
]