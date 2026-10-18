# src/agent/observability/snapshot.py — foto do estado real de uma run e páginas do histórico de eventos
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agent.domain.enums import RunStatus, TaskStatus
from agent.observability.bus import EventBus, get_bus
from agent.observability.contracts import envelope_from_row
from agent.orchestrator.progress import progress_state, subtree
from agent.persistence.models import EventLogModel, EvidenceModel, ExecutionRunModel, OperationAttemptModel, TaskModel

MAX_PAGE = 1_000
TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
_OPENERS = {
    "agent.started": ("output", "output_id"),
    "tool.started": ("tool", "call_id"),
    "command.started": ("command", "call_id"),
    "test.started": ("test", "call_id"),
}
_CLOSERS = {
    "agent.output.completed": ("output", "output_id"),
    "agent.output.failed": ("output", "output_id"),
    "tool.completed": ("tool", "call_id"),
    "tool.failed": ("tool", "call_id"),
    "command.completed": ("command", "call_id"),
    "command.failed": ("command", "call_id"),
    "test.completed": ("test", "call_id"),
    "test.failed": ("test", "call_id"),
}


def _type_filter(types: list[str]):
    clauses = []
    for raw in types:
        t = raw.strip()
        if not t:
            continue
        if t.endswith(".") or "." not in t:
            clauses.append(EventLogModel.event_type.startswith(t if t.endswith(".") else f"{t}."))
        else:
            clauses.append(EventLogModel.event_type == t)
    return or_(*clauses) if clauses else None


def last_seq(session: Session, run_id: uuid.UUID) -> int:
    return int(session.scalar(select(func.max(EventLogModel.seq)).where(EventLogModel.run_id == run_id)) or 0)


def events_page(
    session: Session,
    run_id: uuid.UUID,
    *,
    after: int = 0,
    limit: int = 200,
    types: list[str] | None = None,
    task_id: uuid.UUID | None = None,
    tail: int | None = None,
) -> dict[str, Any]:
    """Eventos persistidos em ordem de `seq`: depois de `after` (paginação para frente) ou os `tail` últimos.
    Linhas antigas sem `seq` (antes da migração) não entram."""
    limit = max(1, min(int(limit), MAX_PAGE))
    stmt = select(EventLogModel).where(EventLogModel.run_id == run_id, EventLogModel.seq.is_not(None))
    flt = _type_filter(types or [])
    if flt is not None:
        stmt = stmt.where(flt)
    if task_id is not None:
        stmt = stmt.where(EventLogModel.task_id == task_id)
    if tail:
        rows = list(session.scalars(stmt.order_by(EventLogModel.seq.desc()).limit(min(int(tail), MAX_PAGE))))
        rows.reverse()
        has_more = bool(rows) and session.scalar(
            select(func.count()).select_from(stmt.where(EventLogModel.seq < rows[0].seq).subquery())
        ) > 0
    else:
        rows = list(session.scalars(stmt.where(EventLogModel.seq > after).order_by(EventLogModel.seq).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
    events = [envelope_from_row(r) for r in rows]
    return {
        "events": events,
        "next_after": events[-1]["seq"] if events else after,
        "has_more": has_more,
        "last_seq": last_seq(session, run_id),
    }


def open_operations(session: Session, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """Chamadas ao modelo, ferramentas, comandos e testes que começaram e não têm fim gravado."""
    rows = session.scalars(
        select(EventLogModel)
        .where(EventLogModel.run_id == run_id, EventLogModel.event_type.in_([*_OPENERS, *_CLOSERS]))
        .order_by(EventLogModel.seq)
    )
    opened: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        data = r.payload_json or {}
        if r.event_type in _OPENERS:
            kind, key = _OPENERS[r.event_type]
            opened[(kind, str(data.get(key)))] = {
                "kind": kind,
                "id": str(data.get(key)),
                "task_id": None if r.task_id is None else str(r.task_id),
                "seq": r.seq,
                "ts": r.created_at.isoformat() if r.created_at else None,
                "tool": data.get("tool"),
                "command": data.get("command"),
                "provider": data.get("provider"),
                "model": data.get("model"),
            }
        else:
            kind, key = _CLOSERS[r.event_type]
            opened.pop((kind, str(data.get(key))), None)
    return list(opened.values())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def run_snapshot(session: Session, run_id: uuid.UUID, *, bus: EventBus | None = None, recent: int = 300) -> dict[str, Any]:
    """Estado lido do banco (tarefas, evidências, eventos) mais o que só existe em memória neste processo
    (texto parcial das saídas em andamento). Nada aqui vem do navegador."""
    bus = bus or get_bus()
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise LookupError(str(run_id))
    rid = str(run.id)
    tasks = subtree(session, run.root_task_id)
    ids = [t.id for t in tasks]
    evidence: dict[uuid.UUID, EvidenceModel] = {}
    for ev in session.scalars(
        select(EvidenceModel).where(EvidenceModel.task_id.in_(ids)).order_by(EvidenceModel.created_at, EvidenceModel.id)
    ):
        evidence[ev.task_id] = ev
    attempts = dict(
        session.execute(
            select(OperationAttemptModel.task_id, func.count())
            .where(OperationAttemptModel.task_id.in_(ids), OperationAttemptModel.run_id == run.id)
            .group_by(OperationAttemptModel.task_id)
        ).all()
    )

    live = bus.live(rid)
    stepping = bus.active_steps(rid)
    live_keys = {("output", o["output_id"]) for o in live["outputs"]} | {
        (op["kind"], op["call_id"]) for op in live["operations"]
    }
    interrupted_ops = [] if stepping else [op for op in open_operations(session, run.id) if (op["kind"], op["id"]) not in live_keys]
    interrupted_tasks = {op["task_id"] for op in interrupted_ops if op["task_id"]}
    if not stepping and run.status != RunStatus.ACTIVE.value:
        interrupted_tasks |= {str(t.id) for t in tasks if t.status == TaskStatus.RUNNING.value}

    if run.status in TERMINAL_RUN_STATUSES:
        mode = "replay"
    elif run.status == RunStatus.PAUSED.value:
        mode = "paused"
    elif stepping:
        mode = "live"
    elif interrupted_ops:
        mode = "interrupted"
    else:
        mode = "idle"

    resumed = session.scalars(
        select(EventLogModel.created_at)
        .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.resumed")
        .order_by(EventLogModel.created_at.desc())
        .limit(1)
    ).first()
    root = session.get(TaskModel, run.root_task_id)
    config = run.config_json or {}
    end = _aware(run.updated_at) if run.status in TERMINAL_RUN_STATUSES and run.updated_at else datetime.now(timezone.utc)
    current = next(
        (t for st in ("RUNNING", "VERIFYING", "READY", "RETRY_PENDING", "PLANNING") for t in tasks if t.status == st and t.id != run.root_task_id),
        None,
    )
    meta_of = lambda t: t.metadata_json or {}  # noqa: E731
    task_rows = []
    for t in tasks:
        ev = evidence.get(t.id)
        failure = meta_of(t).get("last_failure") or {}
        task_rows.append(
            {
                "id": str(t.id),
                "parent_id": None if t.parent_id is None else str(t.parent_id),
                "title": t.title,
                "status": t.status,
                "kind": t.kind,
                "sort_order": t.sort_order,
                "started_at": _iso(t.started_at),
                "completed_at": _iso(t.completed_at),
                "blocked_reason": meta_of(t).get("blocked_reason"),
                "last_failure": {"category": failure.get("category"), "detail": failure.get("detail")} if failure else None,
                "attempts": int(attempts.get(t.id, 0)),
                "covers": meta_of(t).get("covers"),
                "evidence": {
                    "verifier": ev.verifier,
                    "passed": ev.passed,
                    "summary": ev.summary,
                    "state": (ev.detail_json or {}).get("state"),
                    "at": _iso(ev.created_at),
                }
                if ev
                else None,
                "interrupted": str(t.id) in interrupted_tasks,
            }
        )
    page = events_page(session, run.id, tail=recent)
    return {
        "run": {
            "id": rid,
            "project_id": str(run.project_id),
            "root_task_id": str(run.root_task_id),
            "status": run.status,
            "created_at": _iso(run.created_at),
            "updated_at": _iso(run.updated_at),
            "provider": config.get("provider"),
            "model": config.get("model_id"),
            "autonomous": bool(config.get("autonomous")),
        },
        "header": {
            "objective": root.objective if root else None,
            "title": root.title if root else None,
            "status": run.status,
            "mode": mode,
            "elapsed_s": int((end - _aware(run.created_at)).total_seconds()) if run.created_at else None,
            "progress": progress_state(session, run.root_task_id),
            "current_task": {"id": str(current.id), "title": current.title, "status": current.status} if current else None,
            "active_outputs": len(live["outputs"]),
            "active_operations": len(live["operations"]),
            "resumed_at": _iso(resumed),
        },
        "tasks": task_rows,
        "live": live,
        "interrupted": interrupted_ops,
        "events": page["events"],
        "events_truncated": page["has_more"],
        "last_seq": page["last_seq"],
        "stats": {
            **live.get("stats", {}),
            "persisted_events": session.scalar(
                select(func.count()).select_from(EventLogModel).where(EventLogModel.run_id == run.id)
            ),
            "subscribers": bus.subscriber_count(rid),
            "active_steps": stepping,
        },
    }
