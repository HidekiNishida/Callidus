# src/agent/observability/emitter.py — contexto de observação, emissão tipada e publicação após commit
from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from agent.observability.bus import get_bus
from agent.observability.contracts import (
    EVENT_SPECS,
    SCHEMA_VERSION,
    EventEnvelope,
    envelope_from_row,
    spec_for,
    validate_payload,
)
from agent.observability.sanitize import sanitize
from agent.persistence.models import EventLogModel, TaskModel

_PENDING_ROWS = "observability.pending_rows"
_PENDING_ENVS = "observability.pending_envelopes"
_UNSET: Any = object()
_order = itertools.count()


@dataclass
class Observation:
    session: Session
    run_id: uuid.UUID
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    agent: str = "orchestrator"


_CURRENT: ContextVar[Observation | None] = ContextVar("agent_observation", default=None)


def current() -> Observation | None:
    return _CURRENT.get()


@contextmanager
def observe(
    session: Session,
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent: str = "orchestrator",
) -> Iterator[Observation]:
    """Liga eventos emitidos dentro do bloco (inclusive em ferramentas e provedores) à run e à tarefa."""
    obs = Observation(session=session, run_id=run_id, project_id=project_id, task_id=task_id, agent=agent)
    token = _CURRENT.set(obs)
    try:
        yield obs
    finally:
        _CURRENT.reset(token)


def set_task(task_id: uuid.UUID | None) -> None:
    """Fixa a tarefa do contexto aberto por `observe` (cada bloco tem o seu objeto, então não vaza)."""
    obs = _CURRENT.get()
    if obs is not None:
        obs.task_id = task_id


@contextmanager
def scoped(*, task_id: Any = _UNSET, agent: str | None = None) -> Iterator[Observation | None]:
    """Troca tarefa/agente do contexto atual por um trecho; sem contexto ativo, não faz nada."""
    obs = _CURRENT.get()
    if obs is None:
        yield None
        return
    changes: dict[str, Any] = {}
    if task_id is not _UNSET:
        changes["task_id"] = task_id
    if agent is not None:
        changes["agent"] = agent
    token = _CURRENT.set(replace(obs, **changes))
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)


@lru_cache(maxsize=1)
def _limits() -> tuple[int, int]:
    from agent.config import get_settings

    s = get_settings()
    return s.event_text_limit, s.event_output_limit


def _limit_for(event_type: str) -> int:
    text_limit, output_limit = _limits()
    return output_limit if event_type == "agent.output.completed" or event_type not in EVENT_SPECS else text_limit


def _max_seq(session: Session, run_id: uuid.UUID) -> int:
    with session.no_autoflush:
        return int(
            session.execute(select(func.max(EventLogModel.seq)).where(EventLogModel.run_id == run_id)).scalar() or 0
        )


def _parent_of(session: Session, task_id: uuid.UUID | None) -> uuid.UUID | None:
    if task_id is None:
        return None
    with session.no_autoflush:
        task = session.get(TaskModel, task_id)
    return task.parent_id if task is not None else None


def emit(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    task_id: Any = _UNSET,
    agent: str | None = None,
    commit: bool = False,
) -> EventLogModel | dict[str, Any] | None:
    """Registra um fato da execução atual. Persistidos vão para `event_logs` e são publicados após o commit;
    fragmentos são publicados na hora. Sem contexto de observação (fora de uma run), não registra nada."""
    obs = _CURRENT.get()
    if obs is None:
        return None
    spec = spec_for(event_type)
    payload = validate_payload(event_type, data)
    tid = obs.task_id if task_id is _UNSET else task_id
    who = agent or obs.agent
    if not spec.persist:
        payload = sanitize(payload, limit=_limit_for(event_type))
        bus = get_bus()
        env = EventEnvelope(
            id=str(uuid.uuid4()),
            run_id=str(obs.run_id),
            project_id=None if obs.project_id is None else str(obs.project_id),
            task_id=None if tid is None else str(tid),
            parent_task_id=(lambda p: None if p is None else str(p))(_parent_of(obs.session, tid)),
            agent=who,
            type=event_type,
            seq=bus.allocate_seq(str(obs.run_id), lambda: _max_seq(obs.session, obs.run_id)),
            ts=datetime.now(timezone.utc),
            data=payload,
            persisted=False,
        ).model_dump(mode="json")
        bus.publish(env)
        return env
    row = EventLogModel(
        project_id=obs.project_id,
        run_id=obs.run_id,
        task_id=tid,
        event_type=event_type,
        payload_json=payload,
        agent=who,
    )
    obs.session.add(row)
    if commit:
        obs.session.commit()
    return row


def _on_init(target: EventLogModel, _args: Any, _kwargs: Any) -> None:
    target._obs_order = next(_order)


def _before_flush(session: Session, _ctx: Any, _instances: Any) -> None:
    rows = [o for o in session.new if isinstance(o, EventLogModel) and o.seq is None]
    if not rows:
        return
    obs = _CURRENT.get()
    mine = obs is not None and obs.session is session
    rows.sort(key=lambda r: getattr(r, "_obs_order", 0))
    bus = get_bus()
    pending = session.info.setdefault(_PENDING_ROWS, [])
    for row in rows:
        if row.run_id is None:
            if not mine:
                continue
            row.run_id = obs.run_id
            if row.project_id is None:
                row.project_id = obs.project_id
        if row.agent is None:
            row.agent = obs.agent if mine else "system"
        if row.parent_task_id is None:
            row.parent_task_id = _parent_of(session, row.task_id)
        if row.id is None:
            row.id = uuid.uuid4()
        if row.created_at is None:
            row.created_at = datetime.now(timezone.utc)
        row.schema_version = SCHEMA_VERSION
        if row.payload_json is not None:
            row.payload_json = sanitize(row.payload_json, limit=_limit_for(row.event_type))
        run_id = row.run_id
        row.seq = bus.allocate_seq(str(run_id), lambda: _max_seq(session, run_id))
        pending.append(row)


def _after_flush(session: Session, _ctx: Any) -> None:
    rows = session.info.pop(_PENDING_ROWS, None)
    if rows:
        session.info.setdefault(_PENDING_ENVS, []).extend(envelope_from_row(r) for r in rows)


def _after_commit(session: Session) -> None:
    envs = session.info.pop(_PENDING_ENVS, None)
    if envs:
        bus = get_bus()
        for env in envs:
            bus.publish(env)


def _after_soft_rollback(session: Session, previous_transaction: Any) -> None:
    if getattr(previous_transaction, "parent", None) is not None:
        return
    session.info.pop(_PENDING_ROWS, None)
    session.info.pop(_PENDING_ENVS, None)


def install() -> None:
    """Registra os listeners uma vez por processo (idempotente)."""
    if event.contains(Session, "before_flush", _before_flush):
        return
    event.listen(EventLogModel, "init", _on_init)
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_soft_rollback", _after_soft_rollback)


install()
