"""
Arquivo: src/agent/knowledge/models.py
Nome: models.py
Propósito: reexportar os modelos SQLAlchemy do Knowledge Engine a partir da persistência.
Responsabilidade: camada de infraestrutura — fachada dos modelos de conhecimento.
Componentes: KnowledgeItemModel, KnowledgeSourceModel, KnowledgeRequestModel, KnowledgeValidationModel, KnowledgeRelationModel, KnowledgeUsageModel, KnowledgeVersionModel, KnowledgeKind, KnowledgeSourceKind, KnowledgeRequestStatus, KnowledgeValidationStatus.
Dependências: agent.persistence.models, enum.
Observações: modelos definidos em agent.persistence.models para evitar duplicação e garantir migração única.
"""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from agent.persistence.models import (
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeRequestModel,
    KnowledgeValidationModel,
    KnowledgeRelationModel,
    KnowledgeUsageModel,
    KnowledgeVersionModel,
)


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class KnowledgeKind(str, enum.Enum):
    """Tipo de conhecimento armazenado."""

    FACT = "fact"
    SOLUTION = "solution"
    PATTERN = "pattern"
    DECISION = "decision"
    DOCUMENTATION = "documentation"
    CODE_EXAMPLE = "code_example"
    BEST_PRACTICE = "best_practice"
    WARNING = "warning"
    TROUBLESHOOTING = "troubleshooting"


class KnowledgeSourceKind(str, enum.Enum):
    """Origem do conhecimento."""

    WEB_SEARCH = "web_search"
    GITHUB = "github"
    DOCUMENTATION = "documentation"
    AI_SERVICE = "ai_service"
    LOCAL_ANALYSIS = "local_analysis"
    USER_INPUT = "user_input"
    VERIFICATION = "verification"


class KnowledgeRequestStatus(str, enum.Enum):
    """Estado da solicitação de conhecimento."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class KnowledgeValidationStatus(str, enum.Enum):
    """Estado da validação."""

    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    FAILED = "failed"
    OUTDATED = "outdated"