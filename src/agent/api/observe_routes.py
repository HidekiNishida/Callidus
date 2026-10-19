# src/agent/api/observe_routes.py — histórico, foto do estado e transmissão SSE de uma run
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from agent.api.deps import db_session, get_session_factory
from agent.observability.bus import RESYNC, EventBus, get_bus
from agent.observability.snapshot import TERMINAL_RUN_STATUSES, events_page, run_snapshot
from agent.persistence.models import ExecutionRunModel

router = APIRouter()

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})
HEARTBEAT_SEC = 15.0
_REORDER_WINDOW = 200


class _Disconnectable(Protocol):
    async def is_disconnected(self) -> bool: ...


def _run_or_404(session: Session, run_id: uuid.UUID) -> ExecutionRunModel:
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrada")
    return run


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: uuid.UUID,
    after: int = 0,
    limit: int = 200,
    types: str | None = None,
    task_id: uuid.UUID | None = None,
    tail: int | None = None,
    session: Session = Depends(db_session),
) -> dict:
    """Histórico persistido paginado (`after` + `limit`) ou os últimos `tail`; `types` aceita tipos exatos,
    categorias (`tool`) ou prefixos (`agent.output.`) separados por vírgula."""
    _run_or_404(session, run_id)
    return events_page(
        session,
        run_id,
        after=after,
        limit=limit,
        types=types.split(",") if types else None,
        task_id=task_id,
        tail=tail,
    )


@router.get("/runs/{run_id}/observe")
def run_observe(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    _run_or_404(session, run_id)
    return run_snapshot(session, run_id)


def _sse(data: dict[str, Any], *, event: str | None = None, seq: int | None = None) -> str:
    lines = []
    if event:
        lines.append(f"event: {event}")
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, default=str))
    return "\n".join(lines) + "\n\n"


def _page(factory: sessionmaker[Session], run_id: uuid.UUID, after: int) -> dict[str, Any]:
    with factory() as session:
        return events_page(session, run_id, after=after, limit=500)


def _status(factory: sessionmaker[Session], run_id: uuid.UUID) -> str | None:
    with factory() as session:
        run = session.get(ExecutionRunModel, run_id)
        return None if run is None else run.status


async def sse_stream(
    run_id: uuid.UUID,
    request: _Disconnectable,
    after: int,
    *,
    factory: sessionmaker[Session],
    bus: EventBus,
    heartbeat: float = HEARTBEAT_SEC,
    max_age: float | None = None,
) -> AsyncIterator[str]:
    """Assina antes de ler o banco (nada se perde entre as duas coisas), reenvia o persistido depois de `after`,
    manda as saídas em andamento (`live`) e segue com o que chega, sem repetir `seq`. Fila estourada vira
    releitura do banco. Termina com `end` quando a run acaba."""
    rid = str(run_id)
    sub = bus.subscribe(rid)
    sent: set[int] = set()
    cursor = after
    ended = False
    started_at = time.monotonic()

    async def replay(since: int) -> AsyncIterator[str]:
        nonlocal cursor, ended
        while True:
            page = await asyncio.to_thread(_page, factory, run_id, since)
            for env in page["events"]:
                if env["seq"] in sent:
                    continue
                sent.add(env["seq"])
                cursor = max(cursor, env["seq"])
                ended = ended or env["type"] in TERMINAL_EVENTS
                yield _sse(env, seq=env["seq"])
            if not page["has_more"]:
                return
            since = page["next_after"]

    try:
        yield "retry: 3000\n\n"
        async for chunk in replay(after):
            yield chunk
        if ended or await asyncio.to_thread(_status, factory, run_id) in TERMINAL_RUN_STATUSES:
            yield _sse({"run_id": rid, "last_seq": cursor}, event="end")
            return
        yield _sse(bus.live(rid), event="live")
        while True:
            if max_age is not None and time.monotonic() - started_at >= max_age:
                yield _sse({"run_id": rid, "last_seq": cursor}, event="rotate")
                return
            remaining_heartbeat = heartbeat
            if max_age is not None:
                remaining_heartbeat = min(remaining_heartbeat, max_age - (time.monotonic() - started_at))
                if remaining_heartbeat <= 0:
                    yield _sse({"run_id": rid, "last_seq": cursor}, event="rotate")
                    return
            try:
                env = await asyncio.wait_for(sub.queue.get(), timeout=remaining_heartbeat)
            except asyncio.TimeoutError:
                if max_age is not None and time.monotonic() - started_at >= max_age:
                    yield _sse({"run_id": rid, "last_seq": cursor}, event="rotate")
                    return
                if await request.is_disconnected():
                    return
                yield ": ping\n\n"
                continue
            if env.get("type") == RESYNC:
                yield _sse({"run_id": rid, "dropped": sub.dropped}, event="resync")
                async for chunk in replay(max(after, cursor - _REORDER_WINDOW)):
                    yield chunk
                if ended:
                    yield _sse({"run_id": rid, "last_seq": cursor}, event="end")
                    return
                yield _sse(bus.live(rid), event="live")
                continue
            if env.get("persisted", True):
                if env["seq"] in sent:
                    continue
                sent.add(env["seq"])
                cursor = max(cursor, env["seq"])
                yield _sse(env, seq=env["seq"])
            else:
                yield _sse(env)
            if env["type"] in TERMINAL_EVENTS:
                # Count this event's seq if it has one and not already counted
                if "seq" in env and env["seq"] not in sent:
                    sent.add(env["seq"])
                    cursor = max(cursor, env["seq"])
                # Replay any missed persisted events before ending
                async for chunk in replay(max(after, cursor - _REORDER_WINDOW)):
                    yield chunk
                yield _sse({"run_id": rid, "last_seq": cursor}, event="end")
                return
    finally:
        bus.unsubscribe(sub)


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: uuid.UUID,
    request: Request,
    after: int | None = None,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """SSE da run. A reconexão do navegador manda `Last-Event-ID` (último `seq` persistido recebido);
    `after` faz o mesmo explicitamente. Fragmentos não têm `id` e não mexem nesse cursor."""
    factory = get_session_factory()
    with factory() as session:
        _run_or_404(session, run_id)
    start = after or 0
    if last_event_id and last_event_id.strip().isdigit():
        start = max(start, int(last_event_id.strip()))
    return StreamingResponse(
        sse_stream(run_id, request, start, factory=factory, bus=get_bus()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
