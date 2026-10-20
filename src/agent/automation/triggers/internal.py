# src/agent/automation/triggers/internal.py — gatilho de evento interno do Callidus
"""Gatilho de evento: a automação acorda quando algo aconteceu no Callidus.

Duas fontes, ambas **persistidas** (portanto recuperáveis depois de um reinício):

- `event_logs` — o que o Callidus já grava: `task.completed`, `task.failed`,
  `run.completed`, `run.failed` (e qualquer outro tipo gravado).
- `automation_events` — eventos duráveis publicados por adaptadores (webhook,
  watcher de arquivo, gatilho externo).

A entrega é idempotente: a chave do disparo inclui o identificador do evento, então
o mesmo evento processado duas vezes não cria duas execuções.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.automation.contracts import TriggerSpec
from agent.automation.enums import TriggerKind
from agent.automation.timezones import to_utc
from agent.persistence.models import AutomationEventModel, EventLogModel

DEFAULT_EVENT_TYPES = (
    "task.completed",
    "task.failed",
    "run.completed",
    "run.failed",
)


@dataclass(frozen=True)
class EventCandidate:
    """Um evento elegível, pronto para virar disparo."""

    event_id: str
    source: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    project_id: str | None


def _matches_filter(payload: dict[str, Any], criteria: dict[str, Any]) -> bool:
    for key, expected in (criteria or {}).items():
        actual = payload.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
            continue
        if str(actual) != str(expected):
            return False
    return True


class EventTrigger:
    """Gatilho de evento interno."""

    kind = TriggerKind.EVENT

    def __init__(self, spec: TriggerSpec) -> None:
        types = list(spec.event_types)
        if spec.event_type:
            types.insert(0, spec.event_type)
        self._types = types or list(DEFAULT_EVENT_TYPES)
        self._filter = dict(spec.event_filter or {})
        self._project_id: str | None = None

    def with_project(self, project_id: str | None) -> "EventTrigger":
        """Restringe o gatilho aos eventos de um projeto."""
        clone = EventTrigger.__new__(EventTrigger)
        clone._types = self._types
        clone._filter = self._filter
        clone._project_id = project_id
        return clone

    @property
    def event_types(self) -> list[str]:
        return list(self._types)

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Eventos não têm horário próprio: o próximo disparo depende do evento."""
        return None

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        return []

    def candidate_events(
        self,
        session: Session,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[EventCandidate]:
        """Eventos elegíveis, dos mais recentes para os mais antigos.

        `since` limita a janela: é o que evita reprocessar a história inteira a cada
        tique do supervisor.
        """
        window_start = to_utc(since) if since else to_utc(datetime.now()) - timedelta(hours=24)
        found: list[EventCandidate] = []

        stmt = (
            select(EventLogModel)
            .where(EventLogModel.event_type.in_(self._types))
            .where(EventLogModel.created_at >= window_start)
            .order_by(EventLogModel.created_at.desc())
            .limit(limit)
        )
        for row in session.scalars(stmt).all():
            payload = dict(row.payload_json or {})
            if not _matches_filter(payload, self._filter):
                continue
            if self._project_id and row.project_id and str(row.project_id) != self._project_id:
                continue
            found.append(
                EventCandidate(
                    event_id=str(row.id),
                    source="event_log",
                    event_type=row.event_type,
                    occurred_at=to_utc(row.created_at),
                    payload={
                        "event_type": row.event_type,
                        "project_id": str(row.project_id) if row.project_id else None,
                        "task_id": str(row.task_id) if row.task_id else None,
                        "run_id": str(row.run_id) if row.run_id else None,
                        **payload,
                    },
                    project_id=str(row.project_id) if row.project_id else None,
                )
            )

        stmt = (
            select(AutomationEventModel)
            .where(AutomationEventModel.event_type.in_(self._types))
            .where(AutomationEventModel.created_at >= window_start)
            .order_by(AutomationEventModel.created_at.desc())
            .limit(limit)
        )
        for row in session.scalars(stmt).all():
            payload = dict(row.payload_json or {})
            if not _matches_filter(payload, self._filter):
                continue
            if self._project_id and row.project_id and str(row.project_id) != self._project_id:
                continue
            found.append(
                EventCandidate(
                    event_id=str(row.id),
                    source="automation_event",
                    event_type=row.event_type,
                    occurred_at=to_utc(row.created_at),
                    payload={"event_type": row.event_type, **payload},
                    project_id=str(row.project_id) if row.project_id else None,
                )
            )

        found.sort(key=lambda item: item.occurred_at, reverse=True)
        return found[:limit]


__all__ = ["DEFAULT_EVENT_TYPES", "EventCandidate", "EventTrigger"]
