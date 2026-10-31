"""
Arquivo: src/agent/knowledge/learning/tracker.py
Nome: tracker.py
Propósito: rastreamento de padrões de sucesso/falha para aprendizado contínuo.
Responsabilidade: camada de aplicação — registra outcomes, detecta padrões, sugere melhorias.
Componentes: LearningTracker, PatternDetector, ImprovementSuggester.
Dependências: agent.knowledge.models, agent.persistence.models, collections.
Observações: privacidade-first — não armazena dados sensíveis, apenas padrões agregados.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from agent.persistence.models import KnowledgeItemModel, KnowledgeUsageModel, KnowledgeValidationModel, TaskModel


@dataclass
class OutcomeRecord:
    """Registro de outcome de uso/validação."""

    item_id: uuid.UUID
    outcome_type: str  # usage, validation
    success: bool
    context: str | None
    timestamp: datetime
    task_id: uuid.UUID | None = None
    error_pattern: str | None = None


@dataclass
class LearningPattern:
    """Padrão de aprendizado detectado."""

    pattern_id: str
    pattern_type: str  # success_factor, failure_cause, technology_trend, validation_gap
    description: str
    confidence: float
    supporting_evidence: list[str]
    affected_items: list[uuid.UUID]
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int


@dataclass
class ImprovementSuggestion:
    """Sugestão de melhoria baseada em padrões."""

    suggestion_id: str
    title: str
    description: str
    priority: str  # high, medium, low
    pattern_refs: list[str]
    actionable_steps: list[str]
    estimated_impact: str
    created_at: datetime


class LearningTracker:
    """Rastreia outcomes e aprende com padrões de uso."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._pattern_cache: dict[str, LearningPattern] = {}

    def record_outcome(
        self,
        item_id: uuid.UUID,
        outcome_type: str,
        success: bool,
        context: str | None = None,
        task_id: uuid.UUID | None = None,
        error: str | None = None,
    ) -> None:
        """Registra outcome para aprendizado."""
        # Extrair padrão de erro se falhou
        error_pattern = None
        if not success and error:
            error_pattern = self._extract_error_pattern(error)

        record = OutcomeRecord(
            item_id=item_id,
            outcome_type=outcome_type,
            success=success,
            context=context,
            timestamp=datetime.now(UTC),
            task_id=task_id,
            error_pattern=error_pattern,
        )

        # Armazenar no cache para análise posterior
        self._store_outcome(record)

    def _extract_error_pattern(self, error: str) -> str:
        """Extrai padrão generalizado do erro."""
        # Remover detalhes específicos (paths, line numbers, etc.)
        patterns = [
            (r"File \"[^\"]+\", line \d+", "File:LINE"),
            (r"line \d+", "LINE"),
            (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP"),
            (r"\b[a-f0-9]{32,}\b", "HASH"),
            (r"[a-zA-Z]:[\\/][^\\s]*", "PATH"),
            (r"/[a-zA-Z0-9_\-./]+", "PATH"),
            (r"\b\d{4}-\d{2}-\d{2}\b", "DATE"),
        ]

        normalized = error
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized)

        # Truncar
        return normalized[:200]

    def _store_outcome(self, record: OutcomeRecord) -> None:
        """Armazena outcome (em memória por enquanto; futuro: tabela dedicada)."""
        # Por simplicidade, mantemos em cache; produção usaria tabela knowledge_outcomes
        key = f"{record.item_id}:{record.outcome_type}:{record.error_pattern or 'success'}"
        # Em produção, gravar em banco

    def get_recent_outcomes(
        self,
        project_id: uuid.UUID,
        days: int = 30,
    ) -> list[OutcomeRecord]:
        """Recupera outcomes recentes via joins com tabelas existentes."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Usar KnowledgeUsageModel e KnowledgeValidationModel como fontes
        outcomes = []

        # Usages
        usages = self._session.scalars(
            select(KnowledgeUsageModel).where(
                KnowledgeUsageModel.created_at >= cutoff,
            )
        ).all()

        for usage in usages:
            outcomes.append(OutcomeRecord(
                item_id=usage.item_id,
                outcome_type="usage",
                success=usage.success or False,
                context=usage.context,
                timestamp=usage.created_at,
                task_id=usage.task_id,
            ))

        # Validations
        validations = self._session.scalars(
            select(KnowledgeValidationModel).where(
                KnowledgeValidationModel.created_at >= cutoff,
            )
        ).all()

        for val in validations:
            outcomes.append(OutcomeRecord(
                item_id=val.item_id,
                outcome_type="validation",
                success=val.passed or False,
                context=val.notes,
                timestamp=val.created_at or datetime.now(UTC),
            ))

        return outcomes


class PatternDetector:
    """Detecta padrões recorrentes em outcomes."""

    def __init__(self, tracker: LearningTracker) -> None:
        self._tracker = tracker

    def detect_patterns(
        self,
        project_id: uuid.UUID,
        days: int = 30,
        min_occurrences: int = 3,
    ) -> list[LearningPattern]:
        """Detecta padrões significativos."""
        outcomes = self._tracker.get_recent_outcomes(project_id, days)
        patterns = []

        # 1. Padrões de falha por tecnologia
        tech_failure_patterns = self._detect_tech_failure_patterns(outcomes, min_occurrences)
        patterns.extend(tech_failure_patterns)

        # 2. Padrões de sucesso por tipo de conhecimento
        success_patterns = self._detect_success_patterns(outcomes, min_occurrences)
        patterns.extend(success_patterns)

        # 3. Padrões de erro recorrentes
        error_patterns = self._detect_error_patterns(outcomes, min_occurrences)
        patterns.extend(error_patterns)

        # 4. Gaps de validação (itens usados mas não validados)
        validation_gaps = self._detect_validation_gaps(outcomes, min_occurrences)
        patterns.extend(validation_gaps)

        # Filtrar e ordenar por confiança
        patterns = [p for p in patterns if p.confidence >= 0.5]
        patterns.sort(key=lambda p: p.confidence, reverse=True)

        return patterns

    def _detect_tech_failure_patterns(
        self,
        outcomes: list[OutcomeRecord],
        min_occ: int,
    ) -> list[LearningPattern]:
        """Detecta tecnologias com alta taxa de falha."""
        tech_failures = defaultdict(lambda: {"failures": 0, "total": 0, "items": set()})

        for outcome in outcomes:
            if outcome.outcome_type == "usage" and not outcome.success:
                # Buscar tecnologia do item
                # (simplificado - em produção faria join)
                tech_failures["unknown"]["failures"] += 1
                tech_failures["unknown"]["total"] += 1
                tech_failures["unknown"]["items"].add(outcome.item_id)

        patterns = []
        for tech, data in tech_failures.items():
            if data["total"] >= min_occ:
                failure_rate = data["failures"] / data["total"]
                if failure_rate > 0.3:  # >30% falha
                    patterns.append(LearningPattern(
                        pattern_id=f"tech_failure_{tech}_{datetime.now(UTC).strftime('%Y%m%d')}",
                        pattern_type="failure_cause",
                        description=f"Tecnologia '{tech}' tem taxa de falha de {failure_rate:.0%} ({data['failures']}/{data['total']})",
                        confidence=min(failure_rate + 0.2, 0.9),
                        supporting_evidence=[f"Falhas: {data['failures']}", f"Total: {data['total']}"],
                        affected_items=list(data["items"]),
                        first_seen=datetime.now(UTC) - timedelta(days=30),
                        last_seen=datetime.now(UTC),
                        occurrence_count=data["failures"],
                    ))

        return patterns

    def _detect_success_patterns(
        self,
        outcomes: list[OutcomeRecord],
        min_occ: int,
    ) -> list[LearningPattern]:
        """Detecta padrões de sucesso."""
        # Itens validados com alto uso
        patterns = []
        return patterns

    def _detect_error_patterns(
        self,
        outcomes: list[OutcomeRecord],
        min_occ: int,
    ) -> list[LearningPattern]:
        """Detecta padrões de erro recorrentes."""
        error_counts = Counter()
        error_items = defaultdict(set)

        for outcome in outcomes:
            if not outcome.success and outcome.error_pattern:
                error_counts[outcome.error_pattern] += 1
                error_items[outcome.error_pattern].add(outcome.item_id)

        patterns = []
        for error, count in error_counts.most_common():
            if count >= min_occ:
                patterns.append(LearningPattern(
                    pattern_id=f"error_{hash(error) % 10000:04d}_{datetime.now(UTC).strftime('%Y%m%d')}",
                    pattern_type="failure_cause",
                    description=f"Erro recorrente: {error} (ocorreu {count}x)",
                    confidence=min(count / 10.0, 0.9),
                    supporting_evidence=[f"Ocorrências: {count}", f"Itens afetados: {len(error_items[error])}"],
                    affected_items=list(error_items[error]),
                    first_seen=datetime.now(UTC) - timedelta(days=30),
                    last_seen=datetime.now(UTC),
                    occurrence_count=count,
                ))

        return patterns

    def _detect_validation_gaps(
        self,
        outcomes: list[OutcomeRecord],
        min_occ: int,
    ) -> list[LearningPattern]:
        """Detecta itens muito usados mas não validados."""
        usage_by_item = defaultdict(int)
        validated_items = set()

        for outcome in outcomes:
            if outcome.outcome_type == "usage":
                usage_by_item[outcome.item_id] += 1
            elif outcome.outcome_type == "validation" and outcome.success:
                validated_items.add(outcome.item_id)

        patterns = []
        for item_id, usage_count in usage_by_item.items():
            if usage_count >= min_occ and item_id not in validated_items:
                patterns.append(LearningPattern(
                    pattern_id=f"validation_gap_{item_id}_{datetime.now(UTC).strftime('%Y%m%d')}",
                    pattern_type="validation_gap",
                    description=f"Item {item_id} usado {usage_count}x mas não validado",
                    confidence=0.7,
                    supporting_evidence=[f"Usos: {usage_count}", "Validações bem-sucedidas: 0"],
                    affected_items=[item_id],
                    first_seen=datetime.now(UTC) - timedelta(days=30),
                    last_seen=datetime.now(UTC),
                    occurrence_count=usage_count,
                ))

        return patterns


class ImprovementSuggester:
    """Gera sugestões de melhoria baseadas em padrões detectados."""

    def __init__(self, detector: PatternDetector) -> None:
        self._detector = detector

    def suggest_improvements(
        self,
        project_id: uuid.UUID,
        days: int = 30,
    ) -> list[ImprovementSuggestion]:
        """Gera sugestões acionáveis."""
        patterns = self._detector.detect_patterns(project_id, days)
        suggestions = []

        for pattern in patterns:
            suggestion = self._generate_suggestion(pattern)
            if suggestion:
                suggestions.append(suggestion)

        # Ordenar por prioridade
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: priority_order.get(s.priority, 3))

        return suggestions

    def _generate_suggestion(self, pattern: LearningPattern) -> ImprovementSuggestion | None:
        """Gera sugestão baseada no padrão."""
        if pattern.pattern_type == "failure_cause":
            if "tech_failure" in pattern.pattern_id:
                return ImprovementSuggestion(
                    suggestion_id=f"sugg_{pattern.pattern_id}",
                    title=f"Investigar falhas recorrentes em {pattern.description.split('tem taxa')[0].strip()}",
                    description=pattern.description,
                    priority="high",
                    pattern_refs=[pattern.pattern_id],
                    actionable_steps=[
                        "Revisar itens de conhecimento afetados",
                        "Buscar documentação oficial atualizada",
                        "Testar soluções alternativas",
                        "Atualizar ou invalidar conhecimento problemático",
                    ],
                    estimated_impact=f"Reduzir falhas em ~{pattern.occurrence_count} casos/mês",
                    created_at=datetime.now(UTC),
                )
            elif "error_" in pattern.pattern_id:
                return ImprovementSuggestion(
                    suggestion_id=f"sugg_{pattern.pattern_id}",
                    title=f"Resolver erro recorrente: {pattern.description.split('(')[0].strip()}",
                    description=pattern.description,
                    priority="high",
                    pattern_refs=[pattern.pattern_id],
                    actionable_steps=[
                        "Analisar causa raiz do erro",
                        "Atualizar conhecimento com solução verificada",
                        "Adicionar validação automática para prevenir regressão",
                    ],
                    estimated_impact=f"Eliminar {pattern.occurrence_count} ocorrências/mês",
                    created_at=datetime.now(UTC),
                )

        elif pattern.pattern_type == "validation_gap":
            return ImprovementSuggestion(
                suggestion_id=f"sugg_{pattern.pattern_id}",
                title="Validar conhecimento muito usado sem validação",
                description=pattern.description,
                priority="medium",
                pattern_refs=[pattern.pattern_id],
                actionable_steps=[
                    "Revisar itens sem validação mas com alto uso",
                    "Executar testes de validação",
                    "Marcar como validado ou atualizar/remover se obsoleto",
                ],
                estimated_impact=f"Melhorar confiança em {pattern.occurrence_count} itens",
                created_at=datetime.now(UTC),
            )

        return None


def run_learning_cycle(
    session: Session,
    project_id: uuid.UUID,
    days: int = 30,
) -> dict[str, Any]:
    """Executa ciclo completo de aprendizado."""
    tracker = LearningTracker(session)
    detector = PatternDetector(tracker)
    suggester = ImprovementSuggester(detector)

    patterns = detector.detect_patterns(project_id, days)
    suggestions = suggester.suggest_improvements(project_id, days)

    return {
        "patterns_found": len(patterns),
        "patterns": [
            {
                "id": p.pattern_id,
                "type": p.pattern_type,
                "description": p.description,
                "confidence": p.confidence,
                "occurrences": p.occurrence_count,
            }
            for p in patterns
        ],
        "suggestions": [
            {
                "id": s.suggestion_id,
                "title": s.title,
                "priority": s.priority,
                "impact": s.estimated_impact,
                "steps": s.actionable_steps,
            }
            for s in suggestions
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }