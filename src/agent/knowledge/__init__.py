"""
Arquivo: src/agent/knowledge/__init__.py
Nome: __init__.py
Propósito: exportar a API pública do Knowledge Engine.
Responsabilidade: camada de aplicação — fachada do subsistema de conhecimento.
Componentes: KnowledgeEngineService, KnowledgeDiscovery, KnowledgeRequestCreate, KnowledgeDepth, KnowledgeGap.
Dependências: agent.knowledge.service, agent.knowledge.request, agent.knowledge.models.
Observações: ponto de entrada para integração com orquestrador e serviços.
"""
from agent.knowledge.models import (
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeRequestModel,
    KnowledgeValidationModel,
    KnowledgeRelationModel,
    KnowledgeUsageModel,
    KnowledgeVersionModel,
    KnowledgeKind,
    KnowledgeSourceKind,
    KnowledgeRequestStatus,
    KnowledgeValidationStatus,
)
from agent.knowledge.request import (
    KnowledgeDiscovery,
    KnowledgeRequestCreate,
    KnowledgeDepth,
    KnowledgeGap,
)
from agent.knowledge.service import KnowledgeEngineService

__all__ = [
    # Models
    "KnowledgeItemModel",
    "KnowledgeSourceModel",
    "KnowledgeRequestModel",
    "KnowledgeValidationModel",
    "KnowledgeRelationModel",
    "KnowledgeUsageModel",
    "KnowledgeVersionModel",
    "KnowledgeKind",
    "KnowledgeSourceKind",
    "KnowledgeRequestStatus",
    "KnowledgeValidationStatus",
    # Request
    "KnowledgeDiscovery",
    "KnowledgeRequestCreate",
    "KnowledgeDepth",
    "KnowledgeGap",
    # Service
    "KnowledgeEngineService",
]