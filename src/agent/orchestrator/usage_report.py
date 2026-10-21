"""
Arquivo: src/agent/orchestrator/usage_report.py
Nome: usage_report.py
Propósito: montar o demonstrativo de contexto e de consumo a partir dos registros persistidos.
Responsabilidade: camada de aplicação — leitura do livro-razão e do snapshot; não estima o que não foi gravado.
Componentes: task_usage_view, run_usage_view.
Dependências: agent.orchestrator.budget_gate, agent.orchestrator.inference_usage, agent.orchestrator.ledger, agent.persistence.models.
Observações: estimativa de janela e uso informado pelo provedor saem em campos diferentes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.orchestrator.budget_gate import active_settings, policy_ratios
from agent.orchestrator.inference_usage import fold_usage
from agent.orchestrator.ledger import consistency_report, records_for
from agent.orchestrator.stagnation import limits_for, resume_count
from agent.persistence.models import ContextSnapshotModel, ExecutionRunModel, InferenceRecordModel, TaskModel

CATEGORY_LABELS = {
    "instructions": "Instruções globais e do agente",
    "project_rules": "Regras do projeto",
    "tools": "Ferramentas e esquemas",
    "skills": "Skills",
    "memory": "Memória persistente recuperada",
    "objective": "Objetivo e critérios de aceite",
    "files": "Arquivos e trechos de código",
    "history": "Histórico",
    "summaries": "Resumos de contexto anterior",
    "tool_results": "Resultados de ferramentas",
    "other": "Conteúdo adicional",
}


def _count(value: int | None, measurement: str) -> dict[str, Any]:
    """Empacota um número com a qualidade da medição.

    Args:
        value: quantidade, ou `None` quando não há informação.
        measurement: `exact`, `estimate`, `partial` ou `unavailable`.

    Returns:
        O par valor e qualidade. `None` não vira zero.
    """
    return {"value": value, "measurement": measurement}


def _iso(value: datetime | None) -> str | None:
    """Formata um instante para a interface.

    Args:
        value: instante ou vazio.

    Returns:
        O texto ISO, ou `None`.
    """
    return value.isoformat() if value is not None else None


def _labels(categories: list[dict] | None) -> list[dict]:
    """Acrescenta o nome legível de cada categoria gravada no snapshot.

    Args:
        categories: composição persistida, ou `None` em snapshot antigo.

    Returns:
        A mesma lista com `label`. Snapshot sem composição devolve lista vazia.
    """
    labeled = []
    for item in categories or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "other")
        labeled.append({**item, "label": CATEGORY_LABELS.get(category, category)})
    return labeled


def _matches(row: InferenceRecordModel, filters: dict[str, str]) -> bool:
    """Diz se o registro passa pelos filtros pedidos na consulta.

    Args:
        row: registro de inferência.
        filters: valores opcionais de finalidade, provedor, modelo, agente e tarefa.

    Returns:
        `True` quando o registro deve aparecer.
    """
    for field, attr in (
        ("purpose", "purpose"),
        ("provider", "provider"),
        ("model", "model_id"),
        ("agent", "agent"),
    ):
        wanted = filters.get(field)
        if wanted and str(getattr(row, attr) or "") != wanted:
            return False
    task = filters.get("task_id")
    if task and str(row.task_id or "") != task:
        return False
    return True


def _window_limit(run: ExecutionRunModel | None, basis: int | None, basis_quality: str) -> dict[str, Any]:
    """Janela de contexto conhecida e a ocupação dela pela chamada.

    Args:
        run: execução da chamada, quando existe.
        basis: tokens da entrada usada na conta (estimativa, senão o informado).
        basis_quality: qualidade desse número.

    Returns:
        O limite e a ocupação. Sem base numérica, a ocupação fica indisponível.
    """
    config = run.config_json if run is not None and isinstance(run.config_json, dict) else {}
    if isinstance(config, dict) and config.get("context_limit"):
        limit = int(config["context_limit"])
        source = "configuração da execução"
    else:
        limit = int(active_settings().default_context_limit)
        source = "padrão do processo"
    occupancy = None
    quality = "unavailable"
    if limit > 0 and basis is not None:
        occupancy = int(basis) / limit
        quality = basis_quality
    return {
        "context_limit": limit or None,
        "context_limit_source": source,
        "window_occupancy": occupancy,
        "window_occupancy_measurement": quality,
    }


def _window(session: Session, task_id: uuid.UUID | None) -> dict[str, Any]:
    """Janela da última chamada da tarefa, a partir do snapshot gravado.

    Args:
        session: sessão do banco.
        task_id: tarefa consultada.

    Returns:
        A estimativa de ocupação e as categorias. Sem snapshot, os números ficam ausentes.
    """
    if task_id is None:
        return {"available": False}
    snap = session.scalar(
        select(ContextSnapshotModel)
        .where(ContextSnapshotModel.task_id == task_id)
        .order_by(ContextSnapshotModel.created_at.desc())
        .limit(1)
    )
    if snap is None:
        return {"available": False, "measurement": "unavailable"}
    return {
        "available": True,
        "snapshot_id": str(snap.id),
        "estimated_input_tokens": _count(int(snap.estimated_tokens or 0), "estimate"),
        "categories": _labels(snap.categories_json),
        "dropped": list(snap.refs_json or []),
        "notes": list(snap.strategy_notes_json or []),
        "created_at": _iso(snap.created_at),
        "method": "estimativa local de cerca de 4 caracteres por token",
    }


def _record_view(row: InferenceRecordModel, index: int) -> dict[str, Any]:
    """Uma linha do demonstrativo, sem o texto do prompt.

    Args:
        row: registro persistido.
        index: posição na execução, começando em 1.

    Returns:
        Os identificadores, as contagens e a qualidade de cada uma.
    """
    return {
        "id": str(row.id),
        "index": index,
        "task_id": str(row.task_id) if row.task_id else None,
        "agent": row.agent,
        "purpose": row.purpose,
        "provider": row.provider,
        "model": row.model_id,
        "status": row.status,
        "measurement": row.measurement,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "reasoning_tokens": row.reasoning_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_write_tokens": row.cache_write_tokens,
        "estimated_prompt_tokens": row.estimated_prompt_tokens,
        "estimated_completion_tokens": row.estimated_completion_tokens,
        "duration_ms": row.duration_ms,
        "cost_usd": row.cost_usd,
        "failure_reason": row.failure_reason,
        "snapshot_id": str(row.context_snapshot_id) if row.context_snapshot_id else None,
        "created_at": _iso(row.created_at),
    }


def _group(rows: list[InferenceRecordModel], attr: str) -> list[dict[str, Any]]:
    """Soma o gasto considerado por um atributo do registro.

    Args:
        rows: registros já filtrados.
        attr: nome do campo usado como chave.

    Returns:
        Grupos com chamadas e gasto. Gasto indisponível não vira zero.
    """
    from agent.orchestrator.inference_usage import spend_of

    groups: dict[str, list[InferenceRecordModel]] = {}
    for row in rows:
        key = str(getattr(row, attr) or "(não informado)")
        groups.setdefault(key, []).append(row)
    listed = []
    for key, items in groups.items():
        amounts = []
        notes = []
        for item in items:
            amount, quality = spend_of(item)
            if quality == "unavailable":
                continue
            amounts.append(amount)
            notes.append(quality)
        if not amounts:
            measurement = "unavailable"
            value = None
        elif all(note == "exact" for note in notes) and len(amounts) == len(items):
            measurement = "exact"
            value = sum(amounts)
        elif all(note == "estimate" for note in notes):
            measurement = "estimate"
            value = sum(amounts)
        else:
            measurement = "partial"
            value = sum(amounts)
        listed.append({"key": key, "calls": len(items), "spend": _count(value, measurement)})
    listed.sort(key=lambda item: item["calls"], reverse=True)
    return listed


def _budget_block(session: Session, run: ExecutionRunModel | None, folded: dict[str, Any]) -> dict[str, Any]:
    """Teto, reserva, saldo e faixa, a partir da configuração gravada.

    Args:
        session: sessão do banco.
        run: execução, quando a consulta tem uma.
        folded: totais já calculados.

    Returns:
        O orçamento. Sem teto, o saldo fica indisponível em vez de infinito.
    """
    from agent.orchestrator.budget_gate import active_settings

    config = dict((run.config_json if run else None) or {})
    settings = active_settings()
    limits = limits_for(settings, config)
    ratios = policy_ratios(settings, config)
    authorized = int(limits.get("tokens") or 0)
    reserve = int(authorized * ratios["reserve"]) if authorized else 0
    ceiling = max(0, authorized - reserve) if authorized else 0
    spent = folded["spend"]["value"]
    balance = None if not authorized or spent is None else authorized - int(spent)
    ratio = None
    level = "unavailable"
    if authorized and spent is not None:
        ratio = int(spent) / authorized
        if ratio >= ratios["stop"]:
            level = "stop"
        elif ratio >= ratios["reduce"]:
            level = "reduce"
        elif ratio >= ratios["warn"]:
            level = "elevated"
        else:
            level = "normal"
    return {
        "authorized_tokens": authorized or None,
        "reserve_tokens": reserve if authorized else None,
        "operational_ceiling": ceiling if authorized else None,
        "spent": _count(spent, folded["spend"]["measurement"]),
        "balance_tokens": balance,
        "occupancy": ratio,
        "level": level,
        "resumes": resume_count(session, run) if run is not None else 0,
        "grants": list(config.get("budget_grants") or []),
        "ratios": ratios,
    }


def build_usage_view(
    session: Session,
    *,
    run_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    filters: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Demonstrativo da chamada mais recente e do consumo acumulado.

    Args:
        session: sessão do banco.
        run_id: execução, quando a consulta é do run.
        task_id: tarefa, quando a consulta é da tarefa. O acumulado continua sendo o do run dela.
        filters: finalidade, provedor, modelo, agente ou tarefa.

    Returns:
        O demonstrativo, ou `None` quando a tarefa ou a execução não existe.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    run = session.get(ExecutionRunModel, run_id) if run_id else None
    task = session.get(TaskModel, task_id) if task_id else None
    if task_id and task is None:
        return None
    if run_id and run is None:
        return None
    if run is None and task is not None:
        run = session.scalar(
            select(ExecutionRunModel)
            .where(ExecutionRunModel.root_task_id == task.id)
            .order_by(ExecutionRunModel.created_at.desc())
            .limit(1)
        )
        if run is None and task.parent_id:
            # A subtarefa não é a raiz: o run mais recente do projeto que a contém
            # é descoberto pelos próprios registros.
            sample = session.scalar(
                select(InferenceRecordModel)
                .where(InferenceRecordModel.task_id == task.id)
                .order_by(InferenceRecordModel.created_at.desc())
                .limit(1)
            )
            if sample is not None and sample.run_id:
                run = session.get(ExecutionRunModel, sample.run_id)
    scope_run = run.id if run is not None else None
    rows = records_for(session, run_id=scope_run, task_id=None if scope_run else task_id)
    if task_id and scope_run is None:
        rows = records_for(session, task_id=task_id)
    selected = [row for row in rows if _matches(row, filters)]
    folded = fold_usage(selected)
    latest = None
    if task_id:
        own = [row for row in selected if row.task_id == task_id]
        latest = own[-1] if own else None
    elif selected:
        latest = selected[-1]
    reported_prompt = latest.prompt_tokens if latest is not None else None
    reported_completion = latest.completion_tokens if latest is not None else None
    window = _window(session, task_id or (latest.task_id if latest is not None else None))
    estimated = (window.get("estimated_input_tokens") or {}).get("value") if window.get("available") else None
    delta = None
    if reported_prompt is not None and estimated is not None:
        delta = int(reported_prompt) - int(estimated)
    call = {
        "available": latest is not None or bool(window.get("available")),
        "provider": latest.provider if latest is not None else None,
        "model": latest.model_id if latest is not None else None,
        "purpose": latest.purpose if latest is not None else None,
        "status": latest.status if latest is not None else None,
        "measurement": latest.measurement if latest is not None else window.get("measurement", "unavailable"),
        "estimated_input_tokens": window.get("estimated_input_tokens"),
        "reported_input_tokens": _count(reported_prompt, latest.measurement if latest else "unavailable"),
        "reported_output_tokens": _count(reported_completion, latest.measurement if latest else "unavailable"),
        "output_reserve_tokens": latest.estimated_completion_tokens if latest is not None else None,
        "delta_input_tokens": delta,
        "categories": window.get("categories") or [],
        "dropped": window.get("dropped") or [],
        "notes": window.get("notes") or [],
        "method": window.get("method"),
        "snapshot_id": window.get("snapshot_id"),
        **_window_limit(run, estimated if estimated is not None else reported_prompt, "estimate" if estimated is not None else (latest.measurement if latest else "unavailable")),
    }
    cost_values = [float(row.cost_usd) for row in selected if row.cost_usd is not None]
    if not cost_values:
        cost = _count(None, "unavailable")
    elif len(cost_values) == len(selected):
        cost = _count(round(sum(cost_values), 8), "exact")
    else:
        cost = _count(round(sum(cost_values), 8), "partial")
    timeline = [
        {
            "at": _iso(row.created_at),
            "purpose": row.purpose,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "estimated_prompt_tokens": row.estimated_prompt_tokens,
            "measurement": row.measurement,
            "status": row.status,
        }
        for row in selected[-40:]
    ]
    return {
        "run_id": str(run.id) if run is not None else None,
        "task_id": str(task_id) if task_id else None,
        "call": call,
        "accumulated": {
            "prompt_tokens": folded["prompt"],
            "completion_tokens": folded["completion"],
            "reasoning_tokens": folded["reasoning"],
            "cache_read_tokens": folded["cache_read"],
            "cache_write_tokens": folded["cache_write"],
            "calls": folded["calls"],
            "failed": folded["failed"],
            "duration_ms": folded["duration_ms"],
            "spend": folded["spend"],
            "cost_usd": cost,
            "by_purpose": _group(selected, "purpose"),
            "by_task": _group(selected, "task_id"),
            "by_agent": _group(selected, "agent"),
            "by_provider": _group(selected, "provider"),
            "by_model": _group(selected, "model_id"),
            "timeline": timeline,
        },
        "budget": _budget_block(session, run, folded),
        "consistency": consistency_report(session, run.id) if run is not None else None,
        "records": [_record_view(row, index) for index, row in enumerate(selected[-50:], start=max(1, len(selected) - 49))],
    }
