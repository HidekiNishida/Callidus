"""
Arquivo: src/agent/intelligence/context_consumption.py
Nome: context_consumption.py
Propósito: serviço de consumo e gestão de contexto por inferência.
Responsabilidade: camada de aplicação — agrega, classifica e analisa o consumo de
contexto e tokens de cada inferência, sem estimar o que não foi gravado.
Componentes: ContextConsumptionService.
Dependências: agent.orchestrator.inference_usage, agent.persistence.models,
sqlalchemy, uuid, datetime, statistics.
Observações: valores ausentes permanecem `None` (nunca viram zero); o tamanho da
amostra é sempre exposto; estatísticas só aparecem quando há dados suficientes.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.orchestrator.inference_usage import fold_usage, spend_of
from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    ExecutionRunModel,
    InferenceRecordModel,
    TaskModel,
)


def _percentile(values: list[float], p: int) -> float | None:
    """Calcula o percentil `p` (ex.: 95) de uma lista de valores."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100) * (len(ordered) - 1)
    lower = int(rank)
    fraction = rank - lower
    if lower + 1 >= len(ordered):
        return ordered[lower]
    return ordered[lower] + fraction * (ordered[lower + 1] - ordered[lower])


def _stats(values: list[float]) -> dict[str, Any]:
    """Estatísticas descritivas com tamanho da amostra."""
    if not values:
        return {"count": 0, "measurement": "unavailable"}
    total = sum(values)
    return {
        "value": total,
        "count": len(values),
        "mean": round(total / len(values), 4),
        "median": round(median(values), 4),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99) if len(values) >= 10 else None,
        "min": min(values),
        "max": max(values),
        "measurement": "exact",
    }


def _spend(row: InferenceRecordModel) -> tuple[int | None, str]:
    """Gasto considerado de uma inferência (entrada + saída, sem cache nem raciocínio)."""
    amount, quality = spend_of(row)
    if quality == "unavailable":
        return None, "unavailable"
    return amount, quality


def _rows(
    session: Session,
    *,
    project_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    inference_type: str | None = None,
    status: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> list[InferenceRecordModel]:
    """Lista inferências filtradas, do mais antigo para o mais novo."""
    stmt = select(InferenceRecordModel)
    if project_id is not None:
        stmt = stmt.where(InferenceRecordModel.project_id == project_id)
    if run_id is not None:
        stmt = stmt.where(InferenceRecordModel.run_id == run_id)
    if task_id is not None:
        stmt = stmt.where(InferenceRecordModel.task_id == task_id)
    if agent is not None:
        stmt = stmt.where(InferenceRecordModel.agent == agent)
    if model is not None:
        stmt = stmt.where(InferenceRecordModel.model_id == model)
    if provider is not None:
        stmt = stmt.where(InferenceRecordModel.provider == provider)
    if inference_type is not None:
        stmt = stmt.where(InferenceRecordModel.inference_type == inference_type)
    if status is not None:
        stmt = stmt.where(InferenceRecordModel.status == status)
    if period_start is not None:
        stmt = stmt.where(InferenceRecordModel.created_at >= period_start)
    if period_end is not None:
        stmt = stmt.where(InferenceRecordModel.created_at <= period_end)
    stmt = stmt.order_by(InferenceRecordModel.created_at, InferenceRecordModel.id)
    return list(session.scalars(stmt).all())


def _group_key(row: InferenceRecordModel, by: str) -> str:
    """Chave de agrupamento de uma inferência."""
    if by == "inference_type":
        return str(row.inference_type or "não informado")
    if by == "provider":
        return str(row.provider or "não informado")
    if by == "model":
        return str(row.model_id or "não informado")
    if by == "agent":
        return str(row.agent or "não informado")
    if by == "task_id":
        return str(row.task_id or "não informado")
    if by == "project_id":
        return str(row.project_id or "não informado")
    if by == "status":
        return str(row.status or "não informado")
    if by == "purpose":
        return str(row.purpose or "não informado")
    return str(row.id)


class ContextConsumptionService:
    """Agrega consumo de contexto e tokens por inferência.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Visão geral ──────────────────────────────────────────────────────

    def overview(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Visão geral do consumo de contexto e tokens.

        Args:
            project_id: filtra por projeto.
            run_id: filtra por execução.

        Returns:
            Totais acumulados, médias, maior consumo, ocupação de janela,
            taxa de compactação e tokens economizados.
        """
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        folded = fold_usage(rows)
        prompt = folded["prompt"]
        completion = folded["completion"]
        spend = folded["spend"]

        # Ocupação de janela: usa o tamanho do contexto quando disponível.
        occupancies: list[float] = []
        context_sizes: list[int] = []
        for row in rows:
            if row.context_window_size and row.context_window_size > 0:
                basis = row.prompt_tokens if row.prompt_tokens is not None else row.estimated_prompt_tokens
                if basis is not None:
                    occupancies.append(basis / row.context_window_size)
                    context_sizes.append(row.context_window_size)

        # Compactação: eventos de contexto compactado e tokens removidos.
        compact_events = 0
        tokens_removed = 0
        event_stmt = select(EventLogModel).where(EventLogModel.event_type == "context.compacted")
        if run_id is not None:
            event_stmt = event_stmt.where(EventLogModel.run_id == run_id)
        if project_id is not None:
            event_stmt = event_stmt.where(EventLogModel.project_id == project_id)
        for ev in self._session.scalars(event_stmt).all():
            data = ev.payload_json or {}
            compact_events += 1
            before = int(data.get("before_tokens") or 0)
            after = int(data.get("after_tokens") or 0)
            tokens_removed += max(0, before - after)

        completed = [r for r in rows if r.status == "completed"]
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.status] = by_status.get(r.status, 0) + 1

        return {
            "samples": len(rows),
            "by_status": by_status,
            "input_tokens": {"value": prompt["value"], "measurement": prompt["measurement"], "missing": prompt["missing"]},
            "output_tokens": {"value": completion["value"], "measurement": completion["measurement"], "missing": completion["missing"]},
            "total_tokens": spend,
            "inferences_total": folded["calls"],
            "completed_inferences": len(completed),
            "avg_tokens_per_inference": _stats(
                [v for v, _ in (spend_of(r) for r in rows) if v is not None]
            ) if rows else {"count": 0, "measurement": "unavailable"},
            "avg_context_used": {
                "value": round(sum(context_sizes) / len(context_sizes), 2) if context_sizes else None,
                "count": len(context_sizes),
                "measurement": "exact" if context_sizes else "unavailable",
            },
            "max_consumption": {
                "value": max((v for v, _ in (spend_of(r) for r in rows) if v is not None), default=None),
                "measurement": "exact",
            },
            "avg_window_occupancy_pct": {
                "value": round(sum(occupancies) / len(occupancies) * 100, 2) if occupancies else None,
                "count": len(occupancies),
                "measurement": "estimate" if occupancies else "unavailable",
            },
            "compaction": {
                "events": compact_events,
                "tokens_removed_estimated": tokens_removed,
                "rate": round(compact_events / len(rows), 4) if rows else 0.0,
            },
            "tokens_saved_estimated": tokens_removed,
        }

    # ── Por tipo de inferência ──────────────────────────────────────────

    def by_inference_type(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Consumo médio, mediana e percentis por tipo de inferência."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        groups: dict[str, list[InferenceRecordModel]] = {}
        for row in rows:
            groups.setdefault(str(row.inference_type or "outro"), []).append(row)
        listed: list[dict[str, Any]] = []
        for inf_type, items in groups.items():
            spends = [v for v, _ in (spend_of(r) for r in items) if v is not None]
            prompts = [int(r.prompt_tokens) for r in items if r.prompt_tokens is not None]
            completions = [int(r.completion_tokens) for r in items if r.completion_tokens is not None]
            durations = [int(r.duration_ms) for r in items if r.duration_ms is not None]
            listed.append({
                "type": inf_type,
                "label": inf_type.replace("_", " ").title(),
                "count": len(items),
                "total_tokens": _stats(spends),
                "input_tokens": _stats([float(v) for v in prompts]),
                "output_tokens": _stats([float(v) for v in completions]),
                "duration_ms": _stats([float(v) for v in durations]),
            })
        listed.sort(key=lambda item: item["total_tokens"]["count"], reverse=True)
        return {"groups": listed}

    # ── Por componente do contexto ─────────────────────────────────────

    def by_component(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Agrega componentes do contexto por categoria (stacked bar + tabela)."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        buckets: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        total_inferences = len(rows)
        for row in rows:
            components = row.components_included_json or []
            if not isinstance(components, list):
                continue
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                category = str(comp.get("category") or "outro")
                if category not in buckets:
                    order.append(category)
                    buckets[category] = {
                        "category": category,
                        "tokens_total": 0,
                        "inferences_with_component": 0,
                        "tokens_per_inference_values": [],
                    }
                tokens = comp.get("tokens")
                if tokens is not None:
                    buckets[category]["tokens_total"] += int(tokens)
                buckets[category]["inferences_with_component"] += 1
                if tokens is not None:
                    buckets[category]["tokens_per_inference_values"].append(int(tokens))
        listed: list[dict[str, Any]] = []
        grand_total = sum(b["tokens_total"] for b in buckets.values())
        for category in order:
            b = buckets[category]
            vals = b["tokens_per_inference_values"]
            pct = round(b["tokens_total"] / grand_total * 100, 2) if grand_total else 0.0
            listed.append({
                "category": category,
                "tokens_total": b["tokens_total"],
                "avg_tokens_per_inference": round(sum(vals) / len(vals), 2) if vals else None,
                "percent_of_consumption": pct,
                "occurrences": b["inferences_with_component"],
                "sample_size": len(vals),
                "optimization_potential": sum(
                    1
                    for r in rows
                    for c in (r.components_included_json or [])
                    if isinstance(c, dict)
                    and c.get("category") == category
                    and c.get("optimization_potential")
                ),
            })
        listed.sort(key=lambda item: item["tokens_total"], reverse=True)
        return {
            "groups": listed,
            "grand_total_tokens": grand_total,
            "sample_inferences": total_inferences,
        }

    # ── Matriz tipo × componente ────────────────────────────────────────

    def matrix(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Cruza tipo de inferência com componente do contexto."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        cells: dict[str, dict[str, int]] = {}
        types: set[str] = set()
        categories: set[str] = set()
        for row in rows:
            inf_type = str(row.inference_type or "outro")
            types.add(inf_type)
            cells.setdefault(inf_type, {})
            components = row.components_included_json or []
            if not isinstance(components, list):
                continue
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                category = str(comp.get("category") or "outro")
                categories.add(category)
                tokens = int(comp.get("tokens") or 0)
                cells[inf_type][category] = cells[inf_type].get(category, 0) + tokens
        matrix_rows: list[dict[str, Any]] = []
        for inf_type in sorted(types):
            row_entry: dict[str, Any] = {"type": inf_type}
            for category in sorted(categories):
                row_entry[category] = cells[inf_type].get(category, 0)
            row_entry["total"] = sum(cells[inf_type].values())
            matrix_rows.append(row_entry)
        return {
            "types": sorted(types),
            "categories": sorted(categories),
            "matrix": matrix_rows,
        }

    # ── Comparação por agente/modelo/projeto/tarefa ─────────────────────

    def compare(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        group_by: str = "model",
    ) -> dict[str, Any]:
        """Compara consumo por uma dimensão (modelo, agente, provedor, tarefa, tipo)."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        groups: dict[str, list[InferenceRecordModel]] = {}
        for row in rows:
            groups.setdefault(_group_key(row, group_by), []).append(row)
        listed: list[dict[str, Any]] = []
        for key, items in groups.items():
            spends = [v for v, _ in (spend_of(r) for r in items) if v is not None]
            prompts = [int(r.prompt_tokens) for r in items if r.prompt_tokens is not None]
            completions = [int(r.completion_tokens) for r in items if r.completion_tokens is not None]
            listed.append({
                "key": key,
                "count": len(items),
                "total_tokens": _stats([float(v) for v in spends]),
                "input_tokens": _stats([float(v) for v in prompts]),
                "output_tokens": _stats([float(v) for v in completions]),
            })
        listed.sort(key=lambda item: item["total_tokens"]["count"], reverse=True)
        return {"group_by": group_by, "groups": listed}

    # ── Evolução temporal ──────────────────────────────────────────────

    def timeline(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        period: str = "day",
    ) -> dict[str, Any]:
        """Evolução do consumo por período (day, week, month)."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.created_at is None:
                continue
            if period == "week":
                label = row.created_at.strftime("%G-W%V")
            elif period == "month":
                label = row.created_at.strftime("%Y-%m")
            else:
                label = row.created_at.strftime("%Y-%m-%d")
            b = buckets.setdefault(label, {"spend": [], "count": 0, "input": [], "output": []})
            b["count"] += 1
            amount, _ = spend_of(row)
            if amount is not None:
                b["spend"].append(amount)
            if row.prompt_tokens is not None:
                b["input"].append(row.prompt_tokens)
            if row.completion_tokens is not None:
                b["output"].append(row.completion_tokens)
        listed: list[dict[str, Any]] = []
        for label in sorted(buckets):
            b = buckets[label]
            spends = b["spend"]
            listed.append({
                "period": label,
                "inferences": b["count"],
                "total_tokens": {
                    "value": sum(spends) if spends else None,
                    "count": len(spends),
                    "measurement": "exact" if spends else "unavailable",
                },
                "avg_tokens_per_inference": round(sum(spends) / len(spends), 2) if spends else None,
                "input_tokens": sum(b["input"]) if b["input"] else None,
                "output_tokens": sum(b["output"]) if b["output"] else None,
            })
        return {"period": period, "series": listed}

    # ── Oportunidades de otimização ─────────────────────────────────────

    def opportunities(
        self,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Identifica padrões de consumo excessivo com evidência e amostra."""
        rows = _rows(self._session, project_id=project_id, run_id=run_id)
        opportunities: list[dict[str, Any]] = []

        # Histórico crescendo excessivamente: muitas inferências com alto total.
        spends = [v for v, _ in (spend_of(r) for r in rows) if v is not None]
        if spends and len(spends) >= 5:
            avg_spend = sum(spends) / len(spends)
            high = [v for v in spends if v > avg_spend * 2]
            if high:
                opportunities.append({
                    "problem": "Inferências com consumo muito acima da média",
                    "evidence": f"{len(high)} de {len(spends)} inferências acima de 2× a média ({avg_spend:.0f} tokens)",
                    "component": "vários",
                    "frequency": len(high),
                    "estimated_impact_tokens": sum(high),
                    "recommended_strategy": "Compactar histórico e selecionar mensagens relevantes",
                    "information_loss_risk": "médio",
                    "expected_result": "Redução proporcional ao corte de contexto dispensável",
                })

        # Componentes não obrigatórios grandes (potencial de otimização).
        optional_large: dict[str, list[int]] = {}
        for row in rows:
            components = row.components_included_json or []
            if not isinstance(components, list):
                continue
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                if comp.get("required"):
                    continue
                tokens = comp.get("tokens")
                if tokens is None:
                    continue
                category = str(comp.get("category") or "outro")
                optional_large.setdefault(category, []).append(int(tokens))
        for category, vals in optional_large.items():
            if len(vals) >= 2 and sum(vals) / len(vals) > 500:
                opportunities.append({
                    "problem": f"Componente dispensável grande: {category}",
                    "evidence": f"média {sum(vals) / len(vals):.0f} tokens em {len(vals)} inferências",
                    "component": category,
                    "frequency": len(vals),
                    "estimated_impact_tokens": sum(vals),
                    "recommended_strategy": "Recuperação seletiva ou extração de trechos",
                    "information_loss_risk": "baixo",
                    "expected_result": "Redução do componente sem perda de informação crítica",
                })

        # Muitas inferências sem progresso (status repetido sem avanço).
        no_progress = [r for r in rows if r.status in {"failed", "timeout", "truncated"}]
        if no_progress:
            opportunities.append({
                "problem": "Inferências sem progresso verificável",
                "evidence": f"{len(no_progress)} inferências com status falha/timeout/truncado",
                "component": "execução",
                "frequency": len(no_progress),
                "estimated_impact_tokens": sum((v for v, _ in (spend_of(r) for r in no_progress) if v is not None)),
                "recommended_strategy": "Verificação alternativa e reparo dirigido",
                "information_loss_risk": "nenhum",
                "expected_result": "Menos chamadas desperdiçadas",
            })

        # Janela de contexto quase cheia frequentemente.
        high_window = [r for r in rows if r.context_window_size and r.prompt_tokens and r.prompt_tokens / r.context_window_size > 0.85]
        if high_window:
            opportunities.append({
                "problem": "Janela de contexto quase cheia",
                "evidence": f"{len(high_window)} inferências acima de 85% da janela",
                "component": "entrada",
                "frequency": len(high_window),
                "estimated_impact_tokens": sum((int(r.prompt_tokens) for r in high_window)),
                "recommended_strategy": "Compactação de resumos e histórico",
                "information_loss_risk": "alto",
                "expected_result": "Maior folga na janela, menos cortes",
            })

        return {
            "sample_inferences": len(rows),
            "opportunities": opportunities,
            "count": len(opportunities),
        }

    # ── Inferência individual ──────────────────────────────────────────

    def get_inference(self, inference_id: uuid.UUID) -> dict[str, Any] | None:
        """Detalhe de uma inferência individual."""
        row = self._session.get(InferenceRecordModel, inference_id)
        if row is None:
            return None
        return {
            "id": str(row.id),
            "idempotency_key": row.idempotency_key,
            "run_id": str(row.run_id) if row.run_id else None,
            "task_id": str(row.task_id) if row.task_id else None,
            "parent_task_id": str(row.parent_task_id) if row.parent_task_id else None,
            "project_id": str(row.project_id) if row.project_id else None,
            "agent": row.agent,
            "purpose": row.purpose,
            "inference_type": row.inference_type,
            "provider": row.provider,
            "model": row.model_id,
            "status": row.status,
            "failure_reason": row.failure_reason,
            "duration_ms": row.duration_ms,
            "measurement": row.measurement,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "reasoning_tokens": row.reasoning_tokens,
            "cache_read_tokens": row.cache_read_tokens,
            "cache_write_tokens": row.cache_write_tokens,
            "estimated_prompt_tokens": row.estimated_prompt_tokens,
            "estimated_completion_tokens": row.estimated_completion_tokens,
            "context_window_size": row.context_window_size,
            "tokenizer_version": row.tokenizer_version,
            "tokenizer_strategy": row.tokenizer_strategy,
            "cost_usd": row.cost_usd,
            "budget_pressure": row.budget_pressure,
            "input_budget_used": row.input_budget_used,
            "output_reserve_used": row.output_reserve_used,
            "calibration_ratio": row.calibration_ratio,
            "components": row.components_included_json,
            "tool_results_attached": row.tool_results_attached_json,
            "external_refs": row.external_refs_json,
            "compaction_events": row.compaction_events_json,
            "provider_meta": row.provider_meta_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def get_inference_components(self, inference_id: uuid.UUID) -> dict[str, Any] | None:
        """Composição do contexto de uma inferência."""
        row = self._session.get(InferenceRecordModel, inference_id)
        if row is None:
            return None
        components = row.components_included_json or []
        if not isinstance(components, list):
            components = []
        categories: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for comp in components:
            if not isinstance(comp, dict):
                continue
            category = str(comp.get("category") or "outro")
            if category not in categories:
                order.append(category)
                categories[category] = {"category": category, "tokens": 0, "components": []}
            tokens = comp.get("tokens")
            if tokens is not None:
                categories[category]["tokens"] += int(tokens)
            categories[category]["components"].append(comp)
        listed = [categories[c] for c in order]
        listed.sort(key=lambda item: item["tokens"], reverse=True)
        return {
            "inference_id": str(inference_id),
            "categories": listed,
            "total_components": len(components),
            "window_occupancy_pct": (
                round((row.prompt_tokens or 0) / row.context_window_size * 100, 2)
                if row.context_window_size and row.prompt_tokens is not None
                else None
            ),
        }
