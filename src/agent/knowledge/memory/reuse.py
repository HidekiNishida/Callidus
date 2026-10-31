"""
Arquivo: src/agent/knowledge/memory/reuse.py
Nome: reuse.py
Propósito: recuperação contextual e reutilização de conhecimento em execuções de agentes.
Responsabilidade: camada de aplicação — injeta conhecimento relevante no orçamento de contexto do agente.
Componentes: KnowledgeReuser, ContextualRetriever, BudgetAwareInjector.
Dependências: agent.knowledge.memory.store, agent.context.budget, agent.orchestrator.runner.
Observações: prioriza conhecimento validado, controla orçamento de tokens, evita duplicação no contexto.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.knowledge.memory.store import KnowledgeMemoryStore
from agent.knowledge.models import KnowledgeValidationStatus


@dataclass
class RetrievedKnowledge:
    """Conhecimento recuperado pronto para injeção no contexto."""

    item_id: uuid.UUID
    title: str
    summary: str
    key_content: str
    technology: str | None
    confidence: float
    validation_status: str
    usage_count: int
    citation: str  # Formato: "Fonte: título (URL)"
    tokens_estimate: int


@dataclass
class RetrievalResult:
    """Resultado da recuperação contextual."""

    query: str
    knowledge_items: list[RetrievedKnowledge]
    total_tokens: int
    budget_used: float  # 0.0 - 1.0
    sources_consulted: int
    retrieval_time_ms: float
    metadata: dict = None


class ContextualRetriever:
    """Recupera conhecimento relevante para um contexto específico."""

    def __init__(self, store: KnowledgeMemoryStore) -> None:
        self._store = store

    def retrieve_for_task(
        self,
        project_id: uuid.UUID,
        task_objective: str,
        task_technology: str | None = None,
        task_kind: str | None = None,
        max_items: int = 5,
        min_confidence: float = 0.5,
        prefer_validated: bool = True,
    ) -> list[RetrievedKnowledge]:
        """
        Recupera conhecimento relevante para uma task.

        Estratégia:
        1. Busca por tecnologia da task
        2. Busca textual pelo objetivo
        3. Busca por tags de contexto
        4. Prioriza validados e alta confiança
        5. Remove duplicatas
        """
        all_items: list = []

        # 1. Busca por tecnologia
        if task_technology:
            tech_items = self._store.search(
                project_id=project_id,  # type: ignore
                query="",
                technology=task_technology,
                min_confidence=0.3,
                limit=20,
            )
            all_items.extend(tech_items)

        # 2. Busca textual pelo objetivo
        text_items = self._store.search(
            project_id=project_id,  # type: ignore
            query=task_objective,
            min_confidence=0.3,
            limit=20,
        )
        all_items.extend(text_items)

        # 3. Itens recentes (últimos 30 dias)
        recent = self._store.get_recent(project_id=project_id, days=30, limit=10)  # type: ignore
        all_items.extend(recent)

        # 4. Itens mais usados
        popular = self._store.get_most_used(project_id=project_id, limit=10)  # type: ignore
        all_items.extend(popular)

        # Deduplicar por ID
        seen = set()
        unique_items = []
        for item in all_items:
            if item.id not in seen:
                seen.add(item.id)
                unique_items.append(item)

        # Filtrar e pontuar
        scored = self._score_items(
            unique_items,
            task_objective,
            task_technology,
            prefer_validated,
        )

        # Filtrar por confiança mínima
        filtered = [item for item, score in scored if item.confidence >= min_confidence]

        # Ordenar por score final - criar dict para lookup rápido
        score_map = {item.id: score for item, score in scored}
        filtered.sort(key=lambda x: score_map.get(x.id, 0), reverse=True)

        # Converter para RetrievedKnowledge
        return [self._to_retrieved(item) for item in filtered[:max_items]]

    def _score_items(
        self,
        items: list,
        objective: str,
        technology: str | None,
        prefer_validated: bool,
    ) -> list[tuple]:
        """Pontua itens por relevância."""
        scored = []
        obj_lower = objective.lower()
        obj_words = set(re.findall(r"\w{3,}", obj_lower))

        for item in items:
            score = 0.0

            # Score base: confiança
            score += item.confidence * 0.3

            # Bonus: validado
            if item.validation_status == "validated":
                score += 0.2
            elif item.validation_status == "failed":
                score -= 0.3

            # Match tecnologia
            if technology and item.technology and technology.lower() in item.technology.lower():
                score += 0.2

            # Match palavras do objetivo no título/summary
            item_text = (item.title + " " + (item.summary or "") + " " + (item.content or "")).lower()
            item_words = set(re.findall(r"\w{3,}", item_text))
            word_overlap = len(obj_words & item_words) / max(len(obj_words), 1)
            score += word_overlap * 0.3

            # Uso prévio (confiabilidade prática)
            if item.usage_count > 0:
                score += min(item.usage_count * 0.02, 0.1)

            # Recência (itens mais novos são ligeiramente preferidos)
            age_days = 999
            if item.updated_at:
                item_updated = item.updated_at
                if item_updated.tzinfo is None:
                    item_updated = item_updated.replace(tzinfo=UTC)
                age_days = (datetime.now(UTC) - item_updated).days
            if age_days < 30:
                score += 0.05

            scored.append((item, score))

        # Ordenar por score decrescente
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _to_retrieved(self, item) -> RetrievedKnowledge:
        """Converte item do store para RetrievedKnowledge."""
        key_content = item.summary or item.content or item.title
        if len(key_content) > 500:
            key_content = key_content[:500] + "..."

        return RetrievedKnowledge(
            item_id=item.id,
            title=item.title,
            summary=item.summary or "",
            key_content=key_content,
            technology=item.technology,
            confidence=item.confidence,
            validation_status=item.validation_status,
            usage_count=item.usage_count,
            citation=f"Fonte: {item.title} ({item.technology or 'geral'})",
            tokens_estimate=len(key_content) // 4 + 50,  # Estimativa grosseira
        )


class BudgetAwareInjector:
    """Injeta conhecimento no contexto respeitando orçamento de tokens."""

    def __init__(self, max_tokens: int = 2000, reserve_ratio: float = 0.1) -> None:
        self.max_tokens = max_tokens
        self.reserve = int(max_tokens * reserve_ratio)
        self.available = max_tokens - self.reserve

    def inject(
        self,
        knowledge: list[RetrievedKnowledge],
        current_context_tokens: int = 0,
    ) -> tuple[list[RetrievedKnowledge], str]:
        """
        Injeta conhecimento no contexto.

        Returns:
            Tupla (itens_injetados, texto_formatado)
        """
        budget = self.available - current_context_tokens
        if budget <= 0:
            return [], ""

        injected = []
        total_tokens = 0
        parts = []

        for item in knowledge:
            item_tokens = item.tokens_estimate
            if total_tokens + item_tokens > budget:
                break

            injected.append(item)
            total_tokens += item_tokens

            # Formatar para injeção
            part = f"## Conhecimento: {item.title}\n"
            part += f"**Validação**: {item.validation_status} | **Confiança**: {item.confidence:.0%}\n"
            part += f"**Tecnologia**: {item.technology or 'geral'}\n"
            part += f"{item.key_content}\n"
            part += f"*{item.citation}*\n"
            parts.append(part)

        return injected, "\n---\n".join(parts)

    def get_budget_status(self, used_tokens: int) -> dict:
        """Retorna status do orçamento."""
        return {
            "max_tokens": self.max_tokens,
            "reserve": self.reserve,
            "available": self.available,
            "used": used_tokens,
            "remaining": max(0, self.available - used_tokens),
            "usage_ratio": used_tokens / self.available if self.available > 0 else 1.0,
        }


class KnowledgeReuser:
    """Orquestra recuperação e injeção de conhecimento para agentes."""

    def __init__(
        self,
        store: KnowledgeMemoryStore,
        max_context_tokens: int = 2000,
    ) -> None:
        self._store = store
        self._retriever = ContextualRetriever(store)
        self._injector = BudgetAwareInjector(max_tokens=max_context_tokens)

    def prepare_context_for_task(
        self,
        project_id: uuid.UUID,
        task_objective: str,
        task_technology: str | None = None,
        task_kind: str | None = None,
        current_context_tokens: int = 0,
        max_items: int = 5,
        min_confidence: float = 0.5,
    ) -> RetrievalResult:
        """
        Prepara conhecimento para injeção no contexto de uma task.
        """
        start = datetime.now(UTC)

        # Recuperar conhecimento relevante
        knowledge = self._retriever.retrieve_for_task(
            project_id=project_id,
            task_objective=task_objective,
            task_technology=task_technology,
            max_items=max_items,
            min_confidence=0.4,
        )

        # Injetar no orçamento
        injected, formatted = self._injector.inject(knowledge, current_context_tokens)

        elapsed = (datetime.now(UTC) - start).total_seconds() * 1000

        return RetrievalResult(
            query=task_objective,
            knowledge_items=injected,
            total_tokens=sum(k.tokens_estimate for k in injected),
            budget_used=sum(k.tokens_estimate for k in injected) / self._injector.available,
            sources_consulted=len(knowledge),
            retrieval_time_ms=elapsed,
            metadata={
                "project_id": str(project_id),
                "technology": task_technology,
                "injector_budget": self._injector.max_tokens,
            },
        )

    def format_for_prompt(self, result: RetrievalResult) -> str:
        """Formata resultado para inclusão no prompt do modelo."""
        if not result.knowledge_items:
            return ""

        parts = ["\n=== CONHECIMENTO RELEVANTE (injetado automaticamente) ==="]

        for item in result.knowledge_items:
            part = f"\n--- {item.title} ---"
            part += f"\nValidação: {item.validation_status} | Confiança: {item.confidence:.0%}"
            if item.technology:
                part += f" | Tech: {item.technology}"
            part += f"\n{item.key_content}"
            part += f"\nCitação: {item.citation}"
            parts.append(part)

        parts.append("\n=== FIM DO CONHECIMENTO INJETADO ===")
        return "\n".join(parts)