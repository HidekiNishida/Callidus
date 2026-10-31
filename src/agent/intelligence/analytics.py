"""
Arquivo: src/agent/intelligence/analytics.py
Nome: analytics.py
Propósito: serviço de agregação de métricas de desempenho e consumo do Callidus.
Responsabilidade: camada de aplicação — calcula métricas de tokens, contexto, inferência, recursos e eficiência a partir dos registros persistidos (InferenceRecordModel, ContextSnapshotModel, EventLogModel, OperationAttemptModel).
Componentes: AnalyticsService, PercentileCalculator.
Dependências: agent.persistence.models, agent.orchestrator.inference_usage, agent.orchestrator.ledger, sqlalchemy, uuid, datetime, statistics.
Observações: estimativas e valores reportados são mantidos separados; nenhuma métrica usa LLM para cálculo determinístico.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from statistics import median, quantiles
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.orchestrator.inference_usage import fold_usage
from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    ExecutionRunModel,
    InferenceRecordModel,
    OperationAttemptModel,
    TaskModel,
)


def _percentile(values: list[float], p: int) -> float | None:
    """Calcula o percentil `p` (ex.: 95) de uma lista de valores."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_v = sorted(values)
    return quantiles(sorted_v, n=100, method="inclusive")[p - 1]


class AnalyticsService:
    """Agrega métricas de execução a partir dos registros persistidos.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    # ── Tokens ────────────────────────────────────────────────────────────

    def token_metrics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Métricas de consumo de tokens, separando valores reportados e estimados.

        Args:
            run_id: filtra por run.
            task_id: filtra por tarefa.
            project_id: filtra por projeto.

        Returns:
            Totais de entrada, saída e total, com qualidade de medição e percentis por chamada.
        """
        stmt = select(InferenceRecordModel)
        if run_id is not None:
            stmt = stmt.where(InferenceRecordModel.run_id == run_id)
        if task_id is not None:
            stmt = stmt.where(InferenceRecordModel.task_id == task_id)
        if project_id is not None:
            stmt = stmt.where(InferenceRecordModel.project_id == project_id)
        rows = list(self._session.scalars(stmt.order_by(InferenceRecordModel.created_at)).all())

        folded = fold_usage(rows)
        prompt = folded["prompt"]
        completion = folded["completion"]
        spend = folded["spend"]

        durations = [
            int(row.duration_ms or 0)
            for row in rows
            if row.duration_ms is not None and row.status == "completed"
        ]
        tokens_per_second: list[float] = []
        for row in rows:
            if row.status != "completed" or not row.duration_ms or row.duration_ms <= 0:
                continue
            total = (row.prompt_tokens or 0) + (row.completion_tokens or 0)
            if total > 0:
                tokens_per_second.append(total / (row.duration_ms / 1000.0))

        return {
            "prompt_tokens": prompt["value"],
            "prompt_measurement": prompt["measurement"],
            "prompt_missing": prompt["missing"],
            "completion_tokens": completion["value"],
            "completion_measurement": completion["measurement"],
            "completion_missing": completion["missing"],
            "total_tokens": spend["value"],
            "total_measurement": spend["measurement"],
            "calls": folded["calls"],
            "failed_calls": folded["failed"],
            "reasoning_tokens": folded["reasoning"]["value"],
            "cache_read_tokens": folded["cache_read"]["value"],
            "cache_write_tokens": folded["cache_write"]["value"],
            "estimated_prompt_tokens": folded["estimated_prompt"]["value"],
            "estimated_completion_tokens": folded["estimated_completion"]["value"],
            "duration_ms": {
                "p50": _percentile(durations, 50),
                "p95": _percentile(durations, 95),
                "p99": _percentile(durations, 99),
                "min": min(durations) if durations else None,
                "max": max(durations) if durations else None,
                "count": len(durations),
            },
            "tokens_per_second": {
                "p50": _percentile(tokens_per_second, 50),
                "p95": _percentile(tokens_per_second, 95),
                "p99": _percentile(tokens_per_second, 99),
                "count": len(tokens_per_second),
            },
        }

    # ── Contexto ──────────────────────────────────────────────────────────

    def context_metrics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Métricas de orçamento e ocupação de contexto.

        Args:
            run_id: filtra por run.
            task_id: filtra por tarefa.
            project_id: filtra por projeto.

        Returns:
            Orçamento, ocupação, compactações, tokens removidos/preservados, pressão de orçamento.
        """
        stmt = select(ContextSnapshotModel)
        if run_id is not None:
            stmt = stmt.where(ContextSnapshotModel.run_id == run_id)
        if task_id is not None:
            stmt = stmt.where(ContextSnapshotModel.task_id == task_id)
        if project_id is not None:
            stmt = stmt.where(ContextSnapshotModel.project_id == project_id)
        snapshots = list(
            self._session.scalars(stmt.order_by(ContextSnapshotModel.created_at)).all()
        )

        total_estimated = sum(s.estimated_tokens or 0 for s in snapshots)
        # budget_pressure está em InferenceRecordModel, não em ContextSnapshotModel
        pressure_stmt = select(InferenceRecordModel).where(
            InferenceRecordModel.budget_pressure.is_(True)
        )
        if run_id is not None:
            pressure_stmt = pressure_stmt.where(InferenceRecordModel.run_id == run_id)
        if task_id is not None:
            pressure_stmt = pressure_stmt.where(InferenceRecordModel.task_id == task_id)
        if project_id is not None:
            pressure_stmt = pressure_stmt.where(InferenceRecordModel.project_id == project_id)
        pressure_count = len(list(self._session.scalars(pressure_stmt).all()))
        compaction_events = 0
        tokens_removed = 0
        tokens_preserved = 0

        # Conta eventos de compactação no histórico de eventos.
        event_stmt = select(EventLogModel).where(
            EventLogModel.event_type == "context.compacted"
        )
        if run_id is not None:
            event_stmt = event_stmt.where(EventLogModel.run_id == run_id)
        if task_id is not None:
            event_stmt = event_stmt.where(EventLogModel.task_id == task_id)
        for ev in self._session.scalars(event_stmt.order_by(EventLogModel.created_at)).all():
            data = ev.payload_json or {}
            compaction_events += 1
            tokens_removed += int(data.get("before_tokens", 0) or 0) - int(
                data.get("after_tokens", 0) or 0
            )

        return {
            "snapshots": len(snapshots),
            "estimated_tokens_total": total_estimated,
            "budget_pressure_count": pressure_count,
            "compaction_events": compaction_events,
            "tokens_removed_estimated": max(0, tokens_removed),
            "occupancy_by_snapshot": [
                {
                    "at": s.created_at.isoformat() if s.created_at else None,
                    "estimated_tokens": s.estimated_tokens,
                }
                for s in snapshots[-50:]
            ],
        }

    # ── Inferência ────────────────────────────────────────────────────────

    def inference_metrics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Métricas de inferência: latência, taxa de erro, timeout, retry, disponibilidade.

        Args:
            run_id: filtra por run.
            task_id: filtra por tarefa.
            project_id: filtra por projeto.

        Returns:
            TTFT (via duration_ms), tempo total, tokens por segundo, taxa de erro/timeout/retry.
        """
        stmt = select(InferenceRecordModel)
        if run_id is not None:
            stmt = stmt.where(InferenceRecordModel.run_id == run_id)
        if task_id is not None:
            stmt = stmt.where(InferenceRecordModel.task_id == task_id)
        if project_id is not None:
            stmt = stmt.where(InferenceRecordModel.project_id == project_id)
        rows = list(self._session.scalars(stmt.order_by(InferenceRecordModel.created_at)).all())

        total = len(rows)
        completed = sum(1 for r in rows if r.status == "completed")
        failed = sum(1 for r in rows if r.status == "failed")
        timed_out = sum(1 for r in rows if r.status == "timeout")
        truncated = sum(1 for r in rows if r.status == "truncated")

        durations = [int(r.duration_ms or 0) for r in rows if r.duration_ms is not None]
        total_duration_ms = sum(durations)

        providers: dict[str, dict[str, int]] = {}
        for r in rows:
            p = providers.setdefault(r.provider, {"calls": 0, "failed": 0, "timeout": 0})
            p["calls"] += 1
            if r.status == "failed":
                p["failed"] += 1
            if r.status == "timeout":
                p["timeout"] += 1

        return {
            "calls": total,
            "completed": completed,
            "failed": failed,
            "timed_out": timed_out,
            "truncated": truncated,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "timeout_rate": round(timed_out / total, 4) if total else 0.0,
            "total_duration_ms": total_duration_ms,
            "duration_ms": {
                "p50": _percentile(durations, 50),
                "p95": _percentile(durations, 95),
                "p99": _percentile(durations, 99),
                "min": min(durations) if durations else None,
                "max": max(durations) if durations else None,
            },
            "by_provider": {
                name: {
                    "calls": d["calls"],
                    "failed": d["failed"],
                    "timeout": d["timeout"],
                    "error_rate": round(d["failed"] / d["calls"], 4) if d["calls"] else 0.0,
                }
                for name, d in providers.items()
            },
        }

    # ── Recursos ──────────────────────────────────────────────────────────

    def resource_metrics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Métricas de consumo de recursos do hardware (CPU, RAM, VRAM).

        Args:
            run_id: filtra por run.
            project_id: filtra por projeto.

        Returns:
            Amostras de CPU, RAM e VRAM com pico e média.
        """
        stmt = select(EventLogModel).where(EventLogModel.event_type == "resources.sampled")
        if run_id is not None:
            stmt = stmt.where(EventLogModel.run_id == run_id)
        if project_id is not None:
            stmt = stmt.where(EventLogModel.project_id == project_id)
        rows = list(self._session.scalars(stmt.order_by(EventLogModel.created_at)).all())

        cpu_values = []
        ram_values = []
        vram_values = []
        for r in rows:
            data = r.payload_json or {}
            if data.get("cpu_percent") is not None:
                cpu_values.append(float(data["cpu_percent"]))
            if data.get("ram_mb") is not None:
                ram_values.append(float(data["ram_mb"]))
            if data.get("vram_mb") is not None:
                vram_values.append(float(data["vram_mb"]))

        return {
            "samples": len(rows),
            "cpu_percent": {
                "avg": round(sum(cpu_values) / len(cpu_values), 2) if cpu_values else None,
                "max": max(cpu_values) if cpu_values else None,
                "count": len(cpu_values),
            },
            "ram_mb": {
                "avg": round(sum(ram_values) / len(ram_values), 2) if ram_values else None,
                "max": max(ram_values) if ram_values else None,
                "count": len(ram_values),
            },
            "vram_mb": {
                "avg": round(sum(vram_values) / len(vram_values), 2) if vram_values else None,
                "max": max(vram_values) if vram_values else None,
                "count": len(vram_values),
            },
        }

    # ── Eficiência ────────────────────────────────────────────────────────

    def efficiency_metrics(
        self,
        *,
        run_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Métricas de eficiência: tokens por tarefa, chamadas por tarefa, tempo por tarefa,
        taxa de sucesso, progresso por chamada, chamadas sem progresso.

        Args:
            run_id: filtra por run.
            task_id: filtra por tarefa.
            project_id: filtra por projeto.

        Returns:
            Indicadores de eficiência da execução.
        """
        stmt = select(TaskModel)
        if run_id is not None:
            run = self._session.get(ExecutionRunModel, run_id)
            if run is not None:
                # Busca todas as tarefas da subárvore da run
                all_tasks = list(self._session.scalars(select(TaskModel)).all())
                subtree_ids = {run.root_task_id}
                changed = True
                while changed:
                    changed = False
                    for t in all_tasks:
                        if t.parent_id in subtree_ids and t.id not in subtree_ids:
                            subtree_ids.add(t.id)
                            changed = True
                stmt = stmt.where(TaskModel.id.in_(subtree_ids))
        if task_id is not None:
            stmt = stmt.where(TaskModel.id == task_id)
        if project_id is not None:
            stmt = stmt.where(TaskModel.project_id == project_id)
        tasks = list(self._session.scalars(stmt).all())

        completed_tasks = [t for t in tasks if t.status == "COMPLETED"]
        failed_tasks = [t for t in tasks if t.status == "FAILED"]
        blocked_tasks = [t for t in tasks if t.status == "BLOCKED"]

        total_tokens = 0
        total_calls = 0
        total_duration_ms = 0
        for t in completed_tasks:
            usage = (t.metadata_json or {}).get("usage") or {}
            total_tokens += int(usage.get("total") or 0)
            total_calls += int(usage.get("calls") or 0)

        attempts_stmt = select(OperationAttemptModel)
        if run_id is not None:
            attempts_stmt = attempts_stmt.where(OperationAttemptModel.run_id == run_id)
        if task_id is not None:
            attempts_stmt = attempts_stmt.where(OperationAttemptModel.task_id == task_id)
        attempts = list(self._session.scalars(attempts_stmt).all())

        # Chamadas sem progresso: tentativas de modelo consecutivas sem mudança de estado verificável.
        calls_without_progress = 0
        for t in tasks:
            meta = t.metadata_json or {}
            usage = meta.get("usage") or {}
            calls = int(usage.get("calls") or 0)
            if calls > 1:
                calls_without_progress += calls - 1

        return {
            "tasks_total": len(tasks),
            "tasks_completed": len(completed_tasks),
            "tasks_failed": len(failed_tasks),
            "tasks_blocked": len(blocked_tasks),
            "completion_rate": round(len(completed_tasks) / len(tasks), 4) if tasks else 0.0,
            "tokens_per_completed_task": round(total_tokens / len(completed_tasks), 2) if completed_tasks else 0.0,
            "calls_per_completed_task": round(total_calls / len(completed_tasks), 2) if completed_tasks else 0.0,
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "calls_without_progress": calls_without_progress,
            "progress_rate": round(
                (total_calls - calls_without_progress) / total_calls, 4
            )
            if total_calls
            else 0.0,
            "attempts_total": len(attempts),
            "recovery_count": sum(1 for a in attempts if a.kind == "recovery"),
        }

    # ── Visão geral ───────────────────────────────────────────────────────

    def overview(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Visão geral agregada: runs recentes, taxa de conclusão, tokens, modelos, recursos.

        Args:
            project_id: filtra por projeto.

        Returns:
            Indicadores de alto nível para o dashboard de overview.
        """
        run_stmt = select(ExecutionRunModel)
        if project_id is not None:
            run_stmt = run_stmt.where(ExecutionRunModel.project_id == project_id)
        runs = list(self._session.scalars(run_stmt.order_by(ExecutionRunModel.created_at.desc()).limit(50)).all())

        completed = [r for r in runs if r.status == "completed"]
        failed = [r for r in runs if r.status == "failed"]
        active = [r for r in runs if r.status in {"active", "paused"}]

        token_metrics = self.token_metrics(project_id=project_id)
        inference_metrics = self.inference_metrics(project_id=project_id)
        resource_metrics = self.resource_metrics(project_id=project_id)
        efficiency_metrics = self.efficiency_metrics(project_id=project_id)

        models_used: dict[str, int] = {}
        for r in runs:
            config = r.config_json or {}
            model = config.get("model_id") or "desconhecido"
            models_used[model] = models_used.get(model, 0) + 1

        providers_used: dict[str, int] = {}
        for r in runs:
            config = r.config_json or {}
            provider = config.get("provider") or "desconhecido"
            providers_used[provider] = providers_used.get(provider, 0) + 1

        return {
            "runs_total": len(runs),
            "runs_completed": len(completed),
            "runs_failed": len(failed),
            "runs_active": len(active),
            "completion_rate": round(len(completed) / len(runs), 4) if runs else 0.0,
            "models_used": models_used,
            "providers_used": providers_used,
            "tokens": token_metrics,
            "inference": inference_metrics,
            "resources": resource_metrics,
            "efficiency": efficiency_metrics,
            "recent_runs": [
                {
                    "id": str(r.id),
                    "status": r.status,
                    "provider": (r.config_json or {}).get("provider"),
                    "model": (r.config_json or {}).get("model_id"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in runs[:10]
            ],
        }
