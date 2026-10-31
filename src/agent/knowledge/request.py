"""
Arquivo: src/agent/knowledge/request.py
Nome: request.py
Propósito: estrutura da solicitação de conhecimento e descoberta de lacunas.
Responsabilidade: camada de aplicação — definição do contrato de solicitação e avaliação de necessidade.
Componentes: KnowledgeRequest, KnowledgeDiscovery.
Dependências: agent.knowledge.models, pydantic, uuid, datetime.
Observações: independente de modelo de inferência; usado pelo orquestrador e serviços.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeDepth(str, Enum):
    """Profundidade da aquisição desejada."""

    QUICK = "quick"           # Resposta direta, uma fonte
    STANDARD = "standard"     # Múltiplas fontes, síntese
    DEEP = "deep"             # Pesquisa exaustiva, validação rigorosa
    COMPREHENSIVE = "comprehensive"  # Múltiplas IAs, documentação, código


class KnowledgeRequestCreate(BaseModel):
    """Dados para criar uma solicitação de conhecimento."""

    project_id: uuid.UUID
    task_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    question: str = Field(min_length=1, max_length=5000)
    context: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    desired_kind: str | None = None
    depth: KnowledgeDepth = KnowledgeDepth.STANDARD
    validation_criteria: list[str] | None = None
    max_acquisition_time_sec: int = 120


class KnowledgeRequestRead(BaseModel):
    """Solicitação de conhecimento para leitura."""

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    question: str
    context: dict[str, Any] | None
    constraints: dict[str, Any] | None
    desired_kind: str | None
    depth: KnowledgeDepth
    validation_criteria: list[str] | None
    max_acquisition_time_sec: int
    status: str
    result_item_id: uuid.UUID | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class KnowledgeGap:
    """Representa uma lacuna de conhecimento identificada."""

    identifier: str
    description: str
    context: dict[str, Any]
    confidence: float
    suggested_depth: KnowledgeDepth
    suggested_sources: list[str]
    related_task_id: uuid.UUID | None = None
    related_agent_id: uuid.UUID | None = None


class KnowledgeDiscovery:
    """
    Avalia se um agente necessita adquirir conhecimento adicional.

    Critérios de acionamento:
    - Confiança insuficiente do modelo na resposta
    - Ausência de informações necessárias no contexto
    - Erros repetidos na mesma task
    - Dependência de informações atualizadas (versões, APIs)
    - Necessidade de documentação especializada
    - Complexidade incompatível com conhecimento disponível
    """

    # Limiares configuráveis
    MIN_CONFIDENCE_THRESHOLD: float = 0.6
    MAX_REPEATED_FAILURES: int = 2
    MAX_CONTEXT_AGE_HOURS: int = 24

    def __init__(
        self,
        min_confidence: float = 0.6,
        max_repeated_failures: int = 2,
        max_context_age_hours: int = 24,
    ) -> None:
        self.min_confidence = min_confidence
        self.max_repeated_failures = max_repeated_failures
        self.max_context_age_hours = max_context_age_hours

    def should_acquire(
        self,
        *,
        model_confidence: float | None,
        context_has_answer: bool,
        repeated_failures: int,
        requires_updated_info: bool,
        needs_specialized_docs: bool,
        complexity_score: float,
        available_knowledge: list[dict] | None = None,
    ) -> tuple[bool, KnowledgeGap | None]:
        """
        Determina se deve acionar aquisição de conhecimento.

        Returns:
            Tupla (deve_adquirir, lacuna_identificada)
        """
        reasons: list[str] = []
        suggested_depth = KnowledgeDepth.STANDARD
        suggested_sources: list[str] = []

        # 1. Confiança insuficiente
        if model_confidence is not None and model_confidence < self.min_confidence:
            reasons.append(f"confiança do modelo ({model_confidence:.2f}) abaixo do limiar ({self.min_confidence})")
            suggested_depth = KnowledgeDepth.DEEP
            suggested_sources.extend(["web_search", "documentation"])

        # 2. Contexto não tem a resposta
        if not context_has_answer:
            reasons.append("contexto disponível não contém a informação necessária")
            suggested_sources.extend(["web_search", "github", "documentation"])

        # 3. Falhas repetidas
        if repeated_failures >= self.max_repeated_failures:
            reasons.append(f"{repeated_failures} falhas repetidas na mesma task")
            suggested_depth = KnowledgeDepth.DEEP
            suggested_sources.extend(["ai_service", "troubleshooting"])

        # 4. Informação precisa estar atualizada
        if requires_updated_info:
            reasons.append("dependência de informação atualizada (versão, API, changelog)")
            suggested_depth = KnowledgeDepth.DEEP
            suggested_sources.extend(["documentation", "github", "web_search"])

        # 5. Documentação especializada
        if needs_specialized_docs:
            reasons.append("necessidade de documentação técnica especializada")
            suggested_sources.extend(["documentation", "github"])

        # 6. Complexidade alta
        if complexity_score > 0.7:
            reasons.append(f"complexidade alta ({complexity_score:.2f}) incompatível com conhecimento local")
            suggested_depth = KnowledgeDepth.COMPREHENSIVE
            suggested_sources.extend(["ai_service", "web_search", "documentation"])

        # 7. Verificar se já existe conhecimento relevante
        if available_knowledge:
            relevant = self._find_relevant_knowledge(available_knowledge, reasons)
            if relevant:
                # Se encontrou conhecimento relevante com boa confiança, pode não precisar adquirir
                best = max(relevant, key=lambda k: k.get("confidence", 0))
                if best.get("confidence", 0) > 0.8 and not requires_updated_info:
                    return False, None

        deve_adquirir = len(reasons) > 0

        if not deve_adquirir:
            return False, None

        # Determinar fontes únicas
        unique_sources = list(dict.fromkeys(suggested_sources))

        gap = KnowledgeGap(
            identifier=f"gap_{uuid.uuid4().hex[:8]}",
            description="; ".join(reasons),
            context={
                "model_confidence": model_confidence,
                "context_has_answer": context_has_answer,
                "repeated_failures": repeated_failures,
                "requires_updated_info": requires_updated_info,
                "needs_specialized_docs": needs_specialized_docs,
                "complexity_score": complexity_score,
            },
            confidence=min(0.9, 0.5 + len(reasons) * 0.1),
            suggested_depth=suggested_depth,
            suggested_sources=unique_sources or ["web_search"],
        )

        return True, gap

    def _find_relevant_knowledge(
        self, available: list[dict], reasons: list[str]
    ) -> list[dict]:
        """Busca conhecimento existente relevante para as razões identificadas."""
        relevant: list[dict] = []
        keywords = set()
        for reason in reasons:
            # Extrair palavras-chave das razões
            words = reason.lower().split()
            keywords.update(w for w in words if len(w) > 3)

        for item in available:
            content = (item.get("content", "") + " " + item.get("title", "") + " " + " ".join(item.get("tags", []))).lower()
            if any(kw in content for kw in keywords):
                relevant.append(item)

        return relevant

    def create_request_from_gap(
        self,
        gap: KnowledgeGap,
        project_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> KnowledgeRequestCreate:
        """Cria uma solicitação de conhecimento a partir de uma lacuna identificada."""
        return KnowledgeRequestCreate(
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            question=gap.description,
            context=gap.context,
            constraints={"max_time_sec": gap.suggested_depth.value},
            desired_kind=None,
            depth=gap.suggested_depth,
            validation_criteria=None,
            max_acquisition_time_sec=120 if gap.suggested_depth == KnowledgeDepth.QUICK else 300,
        )