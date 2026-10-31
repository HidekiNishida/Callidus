"""
Arquivo: src/agent/intelligence/diagnostics.py
Nome: diagnostics.py
Propósito: motor de diagnóstico determinístico que identifica gargalos, desperdícios e oportunidades de otimização a partir de evidências.
Responsabilidade: camada de aplicação — detecção de problemas comprovados, anomalias estatísticas, hipóteses e recomendações, sem dependência obrigatória de LLM.
Componentes: Diagnostic, DiagnosticEngine, DiagnosticCategory, DiagnosticSeverity, DiagnosticKind.
Dependências: agent.intelligence.analytics (AnalyticsService), agent.persistence.models, agent.orchestrator.stagnation (diagnose), sqlalchemy, uuid, datetime.
Observações: separa problema comprovado de anomalia estatística de hipótese de recomendação; não afirma causalidade sem evidência direta.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.intelligence.analytics import AnalyticsService
from agent.persistence.models import DiagnosticModel, EventLogModel, ExecutionRunModel, TaskModel

DIAGNOSTIC_SCHEMA_VERSION = 1

DIAGNOSTIC_CATEGORIES = [
    "gargalo_inferencia",
    "excesso_retries",
    "excesso_compactacao",
    "contexto_redundante",
    "falha_recorrente",
    "ferramenta_lenta",
    "verificacao_repetida",
    "etapa_custa_demais",
    "queda_qualidade",
    "contexto_excedido",
]

DIAGNOSTIC_SEVERITIES = ["baixa", "media", "alta", "critica"]

DIAGNOSTIC_KINDS = [
    "problema_comprovado",
    "anomalia_estatistica",
    "hipotese",
    "recomendacao",
]


@dataclass
class Diagnostic:
    """Diagnóstico gerado a partir de evidências.

    Atributos:
        id: identificador estável do diagnóstico.
        run_id: run observada, quando aplicável.
        task_id: tarefa observada, quando aplicável.
        category: categoria do problema.
        severity: severidade (baixa, media, alta, critica).
        state: estado (open, investigating, blocked, resolved).
        evidence: evidências que suportam o diagnóstico.
        metric_affected: métrica afetada.
        observed_period: período observado (início e fim).
        probable_cause: causa provável, quando há evidência direta.
        confidence_level: nível de confiança (baixo, medio, alto).
        recommendation: recomendação de ação.
        recommendation_state: estado da recomendação (pendente, aplicada, rejeitada).
        kind: tipo (problema_comprovado, anomalia_estatistica, hipotese, recomendacao).
    """

    id: str
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    category: str = ""
    severity: str = "media"
    state: str = "open"
    evidence: dict[str, Any] = field(default_factory=dict)
    metric_affected: str | None = None
    observed_period: dict[str, str] | None = None
    probable_cause: str | None = None
    confidence_level: str = "medio"
    recommendation: str | None = None
    recommendation_state: str = "pendente"
    kind: str = "hipotese"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": str(self.run_id) if self.run_id else None,
            "task_id": str(self.task_id) if self.task_id else None,
            "category": self.category,
            "severity": self.severity,
            "state": self.state,
            "evidence": self.evidence,
            "metric_affected": self.metric_affected,
            "observed_period": self.observed_period,
            "probable_cause": self.probable_cause,
            "confidence_level": self.confidence_level,
            "recommendation": self.recommendation,
            "recommendation_state": self.recommendation_state,
            "kind": self.kind,
        }


class DiagnosticEngine:
    """Motor de diagnóstico determinístico.

    Atributos:
        session: sessão SQLAlchemy.
        _analytics: serviço de analytics para leitura de métricas.
    """

    def __init__(self, session: Session) -> None:
        """Cria o motor ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy.
        """
        self._session = session
        self._analytics = AnalyticsService(session)

    def list_diagnostics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        category: str | None = None,
        severity: str | None = None,
        state: str | None = None,
    ) -> list[Diagnostic]:
        """Lista diagnósticos com filtros opcionais.

        Args:
            run_id: filtra por run.
            category: filtra por categoria.
            severity: filtra por severidade.
            state: filtra por estado.

        Returns:
            Lista de diagnósticos ordenados por severidade e data.
        """
        stmt = select(DiagnosticModel).order_by(DiagnosticModel.created_at.desc())
        if run_id is not None:
            stmt = stmt.where(DiagnosticModel.run_id == run_id)
        if category is not None:
            stmt = stmt.where(DiagnosticModel.category == category)
        if severity is not None:
            stmt = stmt.where(DiagnosticModel.severity == severity)
        if state is not None:
            stmt = stmt.where(DiagnosticModel.state == state)
        rows = list(self._session.scalars(stmt).all())
        return [
            Diagnostic(
                id=r.diagnostic_id,
                run_id=r.run_id,
                task_id=r.task_id,
                category=r.category,
                severity=r.severity,
                state=r.state,
                evidence=r.evidence_json or {},
                metric_affected=r.metric_affected,
                observed_period=r.observed_period_json,
                probable_cause=r.probable_cause,
                confidence_level=r.confidence_level,
                recommendation=r.recommendation,
                recommendation_state=r.recommendation_state,
                kind=r.kind,
            )
            for r in rows
        ]

    def get_diagnostic(self, diagnostic_id: str) -> Diagnostic | None:
        """Devolve um diagnóstico pelo identificador.

        Args:
            diagnostic_id: identificador do diagnóstico.

        Returns:
            O diagnóstico, ou None quando não encontrado.
        """
        row = self._session.scalar(
            select(DiagnosticModel).where(DiagnosticModel.diagnostic_id == diagnostic_id)
        )
        if row is None:
            return None
        return Diagnostic(
            id=row.diagnostic_id,
            run_id=row.run_id,
            task_id=row.task_id,
            category=row.category,
            severity=row.severity,
            state=row.state,
            evidence=row.evidence_json or {},
            metric_affected=row.metric_affected,
            observed_period=row.observed_period_json,
            probable_cause=row.probable_cause,
            confidence_level=row.confidence_level,
            recommendation=row.recommendation,
            recommendation_state=row.recommendation_state,
            kind=row.kind,
        )

    def create_diagnostic(self, diagnostic: Diagnostic) -> Diagnostic:
        """Cria um novo diagnóstico.

        Args:
            diagnostic: diagnóstico a criar.

        Returns:
            O diagnóstico persistido.
        """
        row = DiagnosticModel(
            diagnostic_id=diagnostic.id,
            run_id=diagnostic.run_id,
            task_id=diagnostic.task_id,
            category=diagnostic.category,
            severity=diagnostic.severity,
            state=diagnostic.state,
            evidence_json=diagnostic.evidence,
            metric_affected=diagnostic.metric_affected,
            observed_period_json=diagnostic.observed_period,
            probable_cause=diagnostic.probable_cause,
            confidence_level=diagnostic.confidence_level,
            recommendation=diagnostic.recommendation,
            recommendation_state=diagnostic.recommendation_state,
            kind=diagnostic.kind,
        )
        self._session.add(row)
        self._session.flush()
        return diagnostic

    # ── Detecção determinística ──────────────────────────────────────────

    def analyze_run(self, run_id: uuid.UUID) -> list[Diagnostic]:
        """Analisa uma run e gera diagnósticos a partir de evidências.

        Args:
            run_id: identificador da run a analisar.

        Returns:
            Lista de diagnósticos gerados (novos diagnósticos são persistidos).
        """
        diagnostics: list[Diagnostic] = []

        # 1. Gargalo de inferência: muitas chamadas com alta latência.
        inference = self._analytics.inference_metrics(run_id=run_id)
        if inference["calls"] > 10 and inference["error_rate"] > 0.3:
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="gargalo_inferencia",
                severity="alta" if inference["error_rate"] > 0.5 else "media",
                state="open",
                evidence={
                    "calls": inference["calls"],
                    "error_rate": inference["error_rate"],
                    "timeout_rate": inference["timeout_rate"],
                    "duration_p95_ms": inference["duration_ms"]["p95"],
                },
                metric_affected="inference_latency",
                observed_period={"start": "", "end": ""},
                probable_cause="Alta taxa de erro ou timeout nas chamadas ao modelo",
                confidence_level="alto",
                recommendation="Reduzir orçamento de contexto, usar modelo menor ou dividir a tarefa em etapas menores",
                recommendation_state="pendente",
                kind="problema_comprovado",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        # 2. Excesso de retries: mesma falha repetida.
        stagnation = inference  # reuse for attempt info
        if stagnation["calls"] > 5 and stagnation["failed"] > 2:
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="excesso_retries",
                severity="media",
                state="open",
                evidence={
                    "failed_calls": stagnation["failed"],
                    "total_calls": stagnation["calls"],
                    "failure_rate": round(stagnation["failed"] / stagnation["calls"], 4),
                },
                metric_affected="inference_success_rate",
                observed_period={"start": "", "end": ""},
                probable_cause="Mesma falha repetida em múltiplas tentativas",
                confidence_level="alto",
                recommendation="Revisar a abordagem da tarefa ou verificar a dependência externa",
                recommendation_state="pendente",
                kind="problema_comprovado",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        # 3. Excesso de compactação de contexto.
        context = self._analytics.context_metrics(run_id=run_id)
        if context["compaction_events"] > 3:
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="excesso_compactacao",
                severity="media",
                state="open",
                evidence={
                    "compaction_events": context["compaction_events"],
                    "budget_pressure_count": context["budget_pressure_count"],
                    "estimated_tokens_total": context["estimated_tokens_total"],
                },
                metric_affected="context_compaction_count",
                observed_period={"start": "", "end": ""},
                probable_cause="Contexto excede o orçamento e exige múltiplas compactações",
                confidence_level="alto",
                recommendation="Aumentar o orçamento de contexto ou reduzir o escopo da tarefa",
                recommendation_state="pendente",
                kind="problema_comprovado",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        # 4. Contexto redundante: muitas leituras de arquivo.
        token_metrics = self._analytics.token_metrics(run_id=run_id)
        if token_metrics["calls"] > 20 and token_metrics["total_measurement"] == "estimate":
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="contexto_redundante",
                severity="baixa",
                state="open",
                evidence={
                    "calls": token_metrics["calls"],
                    "total_tokens": token_metrics["total_tokens"],
                    "measurement": token_metrics["total_measurement"],
                },
                metric_affected="token_estimation_quality",
                observed_period={"start": "", "end": ""},
                probable_cause="Uso de estimativas locais sem contagem reportada pelo provedor",
                confidence_level="medio",
                recommendation="Configurar provedor com suporte a contagem real de tokens",
                recommendation_state="pendente",
                kind="anomalia_estatistica",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        # 5. Etapa custa demais: tempo total elevado com pouca conclusão.
        efficiency = self._analytics.efficiency_metrics(run_id=run_id)
        if efficiency["tasks_total"] > 0 and efficiency["completion_rate"] < 0.5:
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="etapa_custa_demais",
                severity="alta",
                state="open",
                evidence={
                    "completion_rate": efficiency["completion_rate"],
                    "tasks_completed": efficiency["tasks_completed"],
                    "tasks_total": efficiency["tasks_total"],
                    "calls_without_progress": efficiency["calls_without_progress"],
                },
                metric_affected="task_completion_rate",
                observed_period={"start": "", "end": ""},
                probable_cause="Baixa taxa de conclusão com muitas chamadas sem progresso",
                confidence_level="medio",
                recommendation="Revisar o plano de decomposição e os critérios de aceite das tarefas",
                recommendation_state="pendente",
                kind="problema_comprovado",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        # 6. Verificação repetida: muitas tentativas de verificação.
        attempts = self._session.scalars(
            select(EventLogModel).where(
                EventLogModel.run_id == run_id,
                EventLogModel.event_type.in_({"verification.attempt.started", "verification.attempt.completed"}),
            )
        ).all()
        if len(attempts) > 10:
            d = Diagnostic(
                id=f"diag-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                category="verificacao_repetida",
                severity="media",
                state="open",
                evidence={
                    "verification_attempts": len(attempts),
                },
                metric_affected="verification_attempt_count",
                observed_period={"start": "", "end": ""},
                probable_cause="Muitas tentativas de verificação indicam instabilidade na tarefa",
                confidence_level="medio",
                recommendation="Simplificar os critérios de verificação ou revisar a implementação da tarefa",
                recommendation_state="pendente",
                kind="anomalia_estatistica",
            )
            diagnostics.append(d)
            self.create_diagnostic(d)

        return diagnostics

    def get_summary(self, run_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Devolve um resumo dos diagnósticos por categoria e severidade.

        Args:
            run_id: filtra por run.

        Returns:
            Contagem de diagnósticos por categoria, severidade e estado.
        """
        stmt = select(DiagnosticModel)
        if run_id is not None:
            stmt = stmt.where(DiagnosticModel.run_id == run_id)
        rows = list(self._session.scalars(stmt).all())

        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_state: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for r in rows:
            by_category[r.category] = by_category.get(r.category, 0) + 1
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
            by_state[r.state] = by_state.get(r.state, 0) + 1
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1

        return {
            "total": len(rows),
            "by_category": by_category,
            "by_severity": by_severity,
            "by_state": by_state,
            "by_kind": by_kind,
            "critical": by_severity.get("critica", 0),
            "open": by_state.get("open", 0),
        }
