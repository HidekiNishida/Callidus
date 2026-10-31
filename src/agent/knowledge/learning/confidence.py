"""
Arquivo: src/agent/knowledge/learning/confidence.py
Nome: confidence.py
Propósito: scoring de confiança dinâmico baseado em evidências e uso.
Responsabilidade: camada de aplicação — calcula e atualiza confiança de itens de conhecimento.
Componentes: ConfidenceScorer, EvidenceWeighter, ConfidenceUpdater.
Dependências: agent.knowledge.models, agent.knowledge.memory, math.
Observações: confiança não é estática; evolui com validações, uso e tempo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from agent.knowledge.models import KnowledgeValidationStatus
from agent.persistence.models import KnowledgeItemModel, KnowledgeValidationModel, KnowledgeUsageModel


@dataclass
class ConfidenceFactors:
    """Fatores que influenciam a confiança."""

    base_confidence: float = 0.5
    validation_bonus: float = 0.0
    usage_bonus: float = 0.0
    source_quality: float = 0.0
    recency_factor: float = 0.0
    consensus_factor: float = 0.0
    contradiction_penalty: float = 0.0


@dataclass
class ConfidenceBreakdown:
    """Decomposição da confiança final."""

    final_confidence: float
    factors: ConfidenceFactors
    evidence_count: int
    validation_count: int
    usage_count: int
    explanation: str


class ConfidenceScorer:
    """Calcula confiança dinâmica para itens de conhecimento."""

    # Pesos dos fatores (somam 1.0)
    WEIGHTS = {
        "base": 0.20,
        "validation": 0.25,
        "usage": 0.20,
        "source": 0.15,
        "recency": 0.10,
        "consensus": 0.10,
    }

    # Limites
    MAX_VALIDATION_BONUS = 0.3
    MAX_USAGE_BONUS = 0.2
    MAX_SOURCE_QUALITY = 0.15
    MAX_RECENCY = 0.1
    MAX_CONSENSUS = 0.1
    CONTRADICTION_PENALTY = 0.3

    def __init__(self, session: Session) -> None:
        self._session = session

    def calculate(self, item: KnowledgeItemModel) -> ConfidenceBreakdown:
        """Calcula confiança completa para um item."""
        factors = ConfidenceFactors(base_confidence=item.confidence)

        # 1. Validações
        factors.validation_bonus = self._calc_validation_bonus(item)

        # 2. Uso prático
        factors.usage_bonus = self._calc_usage_bonus(item)

        # 3. Qualidade das fontes
        factors.source_quality = self._calc_source_quality(item)

        # 4. Recência
        factors.recency_factor = self._calc_recency_factor(item)

        # 5. Consenso (itens similares validados)
        factors.consensus_factor = self._calc_consensus_factor(item)

        # 6. Penalidade por contradições
        factors.contradiction_penalty = self._calc_contradiction_penalty(item)

        # Calcular final
        final = self._compute_final(factors)

        return ConfidenceBreakdown(
            final_confidence=max(0.0, min(1.0, final)),
            factors=factors,
            evidence_count=item.source_count,
            validation_count=self._count_validations(item),
            usage_count=item.usage_count,
            explanation=self._generate_explanation(factors),
        )

    def _calc_validation_bonus(self, item: KnowledgeItemModel) -> float:
        """Bonus por validações positivas."""
        validations = self._session.scalars(
            select(KnowledgeValidationModel).where(KnowledgeValidationModel.item_id == item.id)
        ).all()

        if not validations:
            return 0.0

        passed = sum(1 for v in validations if v.passed)
        failed = sum(1 for v in validations if v.passed is False)
        total = len(validations)

        if total == 0:
            return 0.0

        ratio = passed / total
        # Bonus proporcional, máximo MAX_VALIDATION_BONUS
        bonus = ratio * self.MAX_VALIDATION_BONUS
        # Penalidade por falhas
        if failed > 0:
            bonus -= (failed / total) * self.CONTRADICTION_PENALTY

        return max(0.0, bonus)

    def _calc_usage_bonus(self, item: KnowledgeItemModel) -> float:
        """Bonus por uso prático bem-sucedido."""
        if item.usage_count == 0:
            return 0.0

        # Contar usos bem-sucedidos
        successful_usage = self._session.scalar(
            select(func.count(KnowledgeUsageModel.id)).where(
                KnowledgeUsageModel.item_id == item.id,
                KnowledgeUsageModel.success.is_(True),
            )
        ) or 0

        failed_usage = self._session.scalar(
            select(func.count(KnowledgeUsageModel.id)).where(
                KnowledgeUsageModel.item_id == item.id,
                KnowledgeUsageModel.success.is_(False),
            )
        ) or 0

        total_usage = successful_usage + failed_usage
        if total_usage == 0:
            return 0.0

        success_rate = successful_usage / total_usage
        # Bonus ponderado por taxa de sucesso e volume
        volume_factor = min(math.log1p(item.usage_count) / math.log(100), 1.0)
        return success_rate * volume_factor * self.MAX_USAGE_BONUS

    def _calc_source_quality(self, item: KnowledgeItemModel) -> float:
        """Qualidade média das fontes."""
        from agent.persistence.models import KnowledgeSourceModel

        sources = self._session.scalars(
            select(KnowledgeSourceModel).where(KnowledgeSourceModel.item_id == item.id)
        ).all()

        if not sources:
            return 0.0

        avg_credibility = sum(s.credibility for s in sources) / len(sources)
        # Diversidade de fontes
        source_kinds = set(s.source_kind for s in sources)
        diversity_bonus = min(len(source_kinds) * 0.02, 0.05)

        return min(avg_credibility * 0.15 + diversity_bonus, self.MAX_SOURCE_QUALITY)

    def _calc_recency_factor(self, item: KnowledgeItemModel) -> float:
        """Fator de recência (itens mais novos podem ser mais relevantes)."""
        if not item.updated_at:
            return 0.0

        age_days = (datetime.now(UTC) - item.updated_at).days
        if age_days < 7:
            return self.MAX_RECENCY
        elif age_days < 30:
            return self.MAX_RECENCY * 0.7
        elif age_days < 90:
            return self.MAX_RECENCY * 0.4
        elif age_days < 365:
            return self.MAX_RECENCY * 0.2
        return 0.0

    def _calc_consensus_factor(self, item: KnowledgeItemModel) -> float:
        """Consenso: outros itens similares validados."""
        if not item.technology:
            return 0.0

        # Buscar itens da mesma tecnologia validados
        validated_same_tech = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.technology == item.technology,
                KnowledgeItemModel.validation_status == "validated",
                KnowledgeItemModel.id != item.id,
            )
        ) or 0

        total_same_tech = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.technology == item.technology,
                KnowledgeItemModel.id != item.id,
            )
        ) or 0

        if total_same_tech == 0:
            return 0.0

        consensus_ratio = validated_same_tech / total_same_tech
        return consensus_ratio * self.MAX_CONSENSUS

    def _calc_contradiction_penalty(self, item: KnowledgeItemModel) -> float:
        """Penalidade por contradições conhecidas."""
        # Verificar validações falhadas
        failed_validations = self._session.scalar(
            select(func.count(KnowledgeValidationModel.id)).where(
                KnowledgeValidationModel.item_id == item.id,
                KnowledgeValidationModel.passed.is_(False),
            )
        ) or 0

        # Verificar uso falhado
        failed_usage = self._session.scalar(
            select(func.count(KnowledgeUsageModel.id)).where(
                KnowledgeUsageModel.item_id == item.id,
                KnowledgeUsageModel.success.is_(False),
            )
        ) or 0

        total_issues = failed_validations + failed_usage
        if total_issues == 0:
            return 0.0

        # Penalidade logarítmica
        return min(math.log1p(total_issues) * 0.1, self.CONTRADICTION_PENALTY)

    def _compute_final(self, factors: ConfidenceFactors) -> float:
        """Combina fatores em confiança final."""
        w = self.WEIGHTS
        final = (
            factors.base_confidence * w["base"] +
            factors.validation_bonus * w["validation"] +
            factors.usage_bonus * w["usage"] +
            factors.source_quality * w["source"] +
            factors.recency_factor * w["recency"] +
            factors.consensus_factor * w["consensus"] -
            factors.contradiction_penalty
        )
        return max(0.0, min(1.0, final))

    def _count_validations(self, item: KnowledgeItemModel) -> int:
        return self._session.scalar(
            select(func.count(KnowledgeValidationModel.id)).where(
                KnowledgeValidationModel.item_id == item.id
            )
        ) or 0

    def _generate_explanation(self, factors: ConfidenceFactors) -> str:
        """Gera explicação textual dos fatores."""
        parts = [f"Base: {factors.base_confidence:.0%}"]
        if factors.validation_bonus > 0:
            parts.append(f"Validações: +{factors.validation_bonus:.0%}")
        if factors.usage_bonus > 0:
            parts.append(f"Uso: +{factors.usage_bonus:.0%}")
        if factors.source_quality > 0:
            parts.append(f"Fontes: +{factors.source_quality:.0%}")
        if factors.recency_factor > 0:
            parts.append(f"Recente: +{factors.recency_factor:.0%}")
        if factors.consensus_factor > 0:
            parts.append(f"Consenso: +{factors.consensus_factor:.0%}")
        if factors.contradiction_penalty > 0:
            parts.append(f"Contradições: -{factors.contradiction_penalty:.0%}")
        return " | ".join(parts)


class ConfidenceUpdater:
    """Atualiza confiança de itens periodicamente ou sob demanda."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._scorer = ConfidenceScorer(session)

    def update_item(self, item_id: uuid.UUID) -> ConfidenceBreakdown | None:
        """Atualiza confiança de um item específico."""
        item = self._session.get(KnowledgeItemModel, item_id)
        if not item:
            return None

        breakdown = self._scorer.calculate(item)
        item.confidence = breakdown.final_confidence
        item.updated_at = datetime.now(UTC)
        self._session.flush()
        return breakdown

    def update_all_for_project(
        self,
        project_id: uuid.UUID,
        min_usage: int = 1,
    ) -> dict[str, int]:
        """Atualiza confiança de todos os itens de um projeto."""
        items = self._session.scalars(
            select(KnowledgeItemModel).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.usage_count >= min_usage,
            )
        ).all()

        updated = 0
        increased = 0
        decreased = 0

        for item in items:
            old_confidence = item.confidence
            breakdown = self._scorer.calculate(item)
            item.confidence = breakdown.final_confidence
            item.updated_at = datetime.now(UTC)

            if breakdown.final_confidence > old_confidence:
                increased += 1
            elif breakdown.final_confidence < old_confidence:
                decreased += 1
            updated += 1

        self._session.flush()
        return {"updated": updated, "increased": increased, "decreased": decreased}


def recalculate_confidence(item: KnowledgeItemModel, session: Session) -> float:
    """Função helper para recalcular confiança de um item."""
    scorer = ConfidenceScorer(session)
    breakdown = scorer.calculate(item)
    item.confidence = breakdown.final_confidence
    item.updated_at = datetime.now(UTC)
    session.flush()
    return breakdown.final_confidence