# src/agent/automation/supervisor.py — runtime autônomo das automações
"""O supervisor mantém as automações vivas **sem a interface**.

Ele roda num processo próprio (o `callidus-supervisor`, instalado como serviço
nativo do sistema) e também dentro da API. As duas rotas usam o mesmo núcleo: o
que muda é quem inicia o processo.

Cada tique:

1. **Recupera** — disparos interrompidos voltam para a fila; runs em curso são
   reconciliados com o estado real.
2. **Dispara** — automações vencidas registram disparo (com a política de disparos
   perdidos da própria automação) e eventos internos elegíveis viram disparo.
3. **Executa** — disparos prontos rodam: dependências, ação, evidência, estado.

O supervisor não consome inferência para descobrir trabalho: o que ele consulta é o
banco.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from agent.automation.contracts import TriggerSpec
from agent.automation.dispatcher import Dispatcher
from agent.automation.enums import AutomationState, FiringState, TriggerKind
from agent.automation.executor import AutomationExecutor
from agent.automation.store import AutomationService
from agent.automation.timezones import to_utc
from agent.config import Settings, get_settings
from agent.persistence.database import build_session_factory, create_db_engine, init_db
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    EventLogModel,
)

logger = logging.getLogger(__name__)

# Estados em que um disparo foi interrompido pelo encerramento do processo.
_INTERRUPTED = {FiringState.PREPARING.value, FiringState.RUNNING.value}


@dataclass
class SupervisorStats:
    ticks: int = 0
    dispatched: int = 0
    executed: int = 0
    failed: int = 0
    blocked: int = 0
    duplicates: int = 0
    recovered: int = 0
    last_tick_at: datetime | None = None
    last_error: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticks": self.ticks,
            "dispatched": self.dispatched,
            "executed": self.executed,
            "failed": self.failed,
            "blocked": self.blocked,
            "duplicates": self.duplicates,
            "recovered": self.recovered,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_error": self.last_error,
        }


class AutomationSupervisor:
    """Núcleo do runtime de automações — compartilhado pela API e pelo supervisor nativo."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory or build_session_factory(
            create_db_engine(self._settings)
        )
        self.stats = SupervisorStats()
        self._stop = asyncio.Event()
        self._last_heartbeat: datetime | None = None

    # ------------------------------------------------------------ ciclo

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self, interval_sec: float = 5.0) -> None:
        """Laço principal do supervisor."""
        logger.info("supervisor de automações iniciado")
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 — o supervisor não pode morrer
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("tique do supervisor falhou: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                continue
        logger.info("supervisor de automações parado")

    # ------------------------------------------------------------ tique

    async def tick(self) -> dict[str, Any]:
        """Um ciclo completo: recuperação → disparo → execução."""
        session = self._session_factory()
        try:
            summary = await self._tick_with(session)
            session.commit()
            self.stats.ticks += 1
            self.stats.last_tick_at = datetime.now(timezone.utc)
            self.stats.last_error = None
            self.stats.history.append(summary)
            self.stats.history = self.stats.history[-50:]
            self._heartbeat(session)
            return summary
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("tique do supervisor falhou: %s", exc)
            return {"error": self.stats.last_error}
        finally:
            session.close()

    def _heartbeat(self, session) -> None:
        """Grava o batimento do runtime — é o que `status` mostra de outro processo."""
        self.stats.ticks += 0  # mantém o contador explícito
        now = datetime.now(timezone.utc)
        if self._last_heartbeat and (now - self._last_heartbeat).total_seconds() < 30:
            return
        self._last_heartbeat = now
        session.add(
            EventLogModel(
                event_type="automation.heartbeat",
                payload_json={
                    "pid": os.getpid(),
                    "ticks": self.stats.ticks,
                    "dispatched": self.stats.dispatched,
                    "executed": self.stats.executed,
                    "failed": self.stats.failed,
                    "blocked": self.stats.blocked,
                    "duplicates": self.stats.duplicates,
                    "recovered": self.stats.recovered,
                    "last_tick_at": now.isoformat(),
                    "last_error": self.stats.last_error,
                },
            )
        )
        session.commit()

    async def _tick_with(self, session) -> dict[str, Any]:
        service = AutomationService(session)
        dispatcher = Dispatcher(session)
        executor = AutomationExecutor(session, self._settings)
        now = to_utc(datetime.now(timezone.utc))

        recovered = self._recover(session, service, executor)
        dispatched = self._dispatch(session, service, dispatcher, now)
        executed = await self._execute(session, executor, now)

        return {
            "recovered": recovered,
            "dispatched": dispatched,
            "executed": executed,
            "now": now.isoformat(),
        }

    # ------------------------------------------------------------ recuperação

    def _recover(self, session, service: AutomationService, executor: AutomationExecutor) -> int:
        """Recupera disparos interrompidos por encerramento do processo."""
        recovered = 0
        rows = list(
            session.scalars(
                select(AutomationFiringModel).where(
                    AutomationFiringModel.state.in_(sorted(_INTERRUPTED))
                )
            ).all()
        )
        for firing in rows:
            if firing.state == FiringState.RUNNING.value and firing.run_id is not None:
                # O trabalho pode ter sobrevivido: a reconciliação decide pelo estado do run.
                continue
            firing.state = FiringState.PENDING.value
            firing.next_attempt_at = None
            firing.error = "retomado após interrupção"
            recovered += 1
        self.stats.recovered += recovered
        return recovered

    # ------------------------------------------------------------ disparo

    def _dispatch(
        self,
        session,
        service: AutomationService,
        dispatcher: Dispatcher,
        now: datetime,
    ) -> dict[str, Any]:
        created: list[str] = []
        duplicates = 0
        for automation in service.enabled():
            try:
                result = dispatcher.dispatch_due(automation, now=now)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "falha ao despachar a automação %s: %s", automation.id, exc
                )
                continue
            created.extend(str(f.id) for f in result.created)
            duplicates += result.duplicates

            # Gatilho de evento: procura eventos elegíveis (persistidos).
            trigger_spec = TriggerSpec.model_validate(automation.trigger_json or {})
            if trigger_spec.kind is not TriggerKind.EVENT:
                continue
            trigger = service.trigger_of(automation)
            since = automation.last_run_at
            for candidate in trigger.candidate_events(session, since=since):
                firing = dispatcher.dispatch_event(automation, candidate)
                if firing is None:
                    duplicates += 1
                else:
                    created.append(str(firing.id))
        self.stats.dispatched += len(created)
        self.stats.duplicates += duplicates
        return {"created": created, "duplicates": duplicates}

    # ------------------------------------------------------------ execução

    async def _execute(self, session, executor: AutomationExecutor, now: datetime) -> list[dict]:
        outcomes: list[dict] = []
        limit = int(getattr(self._settings, "automation_max_executions_per_tick", 20) or 20)
        rows = list(
            session.scalars(
                select(AutomationFiringModel)
                .where(
                    AutomationFiringModel.state.in_(
                        [
                            FiringState.PENDING.value,
                            FiringState.WAITING_DEPENDENCY.value,
                        ]
                    )
                )
                .order_by(AutomationFiringModel.scheduled_for)
            ).all()
        )
        for firing in rows:
            if len(outcomes) >= limit:
                # Teto por tique: uma rajada de disparos não vira uma rajada de execuções.
                break
            if firing.next_attempt_at is not None and to_utc(firing.next_attempt_at) > now:
                continue
            automation = session.get(AutomationModel, firing.automation_id)
            if automation is None:
                firing.state = FiringState.CANCELLED.value
                continue
            if automation.state != AutomationState.ENABLED.value:
                # Automação suspensa/desabilitada: o disparo pendente é ignorado.
                firing.state = FiringState.SKIPPED.value
                firing.error = f"automação {automation.state}"
                continue
            outcome = await executor.execute(firing)
            outcomes.append(
                {
                    "firing_id": str(outcome.firing_id),
                    "state": outcome.state,
                    "ok": outcome.ok,
                    "detail": outcome.detail,
                }
            )
            if outcome.state == FiringState.COMPLETED.value:
                self.stats.executed += 1
            elif outcome.state == FiringState.FAILED.value:
                self.stats.failed += 1
            elif outcome.state in {
                FiringState.BLOCKED.value,
                FiringState.WAITING_DEPENDENCY.value,
            }:
                self.stats.blocked += 1
            session.flush()

        # Reconciliação: disparos que ficaram rodando (run entregue ao worker).
        for outcome in executor.reconcile():
            outcomes.append(
                {
                    "firing_id": str(outcome.firing_id),
                    "state": outcome.state,
                    "ok": outcome.ok,
                    "detail": outcome.detail,
                }
            )
        return outcomes

    # ------------------------------------------------------------ diagnóstico

    def status(self) -> dict[str, Any]:
        """Situação do runtime: automações, disparos e contadores."""
        session = self._session_factory()
        try:
            automations = list(session.scalars(select(AutomationModel)).all())
            firings = list(session.scalars(select(AutomationFiringModel)).all())
            by_state: dict[str, int] = {}
            for firing in firings:
                by_state[firing.state] = by_state.get(firing.state, 0) + 1
            enabled = [a for a in automations if a.state == AutomationState.ENABLED.value]
            heartbeat = self._read_heartbeat(session)
            upcoming = sorted(
                (a for a in enabled if a.next_run_at is not None),
                key=lambda a: a.next_run_at,
            )
            return {
                "running": not self._stop.is_set(),
                "stats": self.stats.as_dict(),
                "heartbeat": heartbeat,
                "automations": {
                    "total": len(automations),
                    "enabled": len(enabled),
                    "suspended": sum(1 for a in automations if a.state == AutomationState.SUSPENDED.value),
                    "disabled": sum(1 for a in automations if a.state == AutomationState.DISABLED.value),
                },
                "firings": {"total": len(firings), "by_state": by_state},
                "next_run_at": upcoming[0].next_run_at.isoformat() if upcoming else None,
                "next_run_automation_id": str(upcoming[0].id) if upcoming else None,
            }
        finally:
            session.close()

    def _read_heartbeat(self, session) -> dict[str, Any] | None:
        """Batimento gravado pelo runtime em execução (visível de outro processo)."""
        row = session.scalars(
            select(EventLogModel)
            .where(EventLogModel.event_type == "automation.heartbeat")
            .order_by(EventLogModel.created_at.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        payload = dict(row.payload_json or {})
        payload["created_at"] = row.created_at.isoformat() if row.created_at else None
        return payload

    def diagnose(self) -> dict[str, Any]:
        """Diagnóstico detalhado: automações vencidas, dependências e disparos pendentes."""
        session = self._session_factory()
        try:
            service = AutomationService(session)
            now = to_utc(datetime.now(timezone.utc))
            automations = []
            for automation in service.list():
                next_run = service.next_occurrence(automation, after=now)
                automations.append(
                    {
                        "id": str(automation.id),
                        "name": automation.name,
                        "state": automation.state,
                        "target": automation.target_kind,
                        "trigger": (automation.trigger_json or {}).get("kind"),
                        "timezone": automation.timezone,
                        "missed_policy": automation.missed_policy,
                        "next_run_at": next_run.isoformat() if next_run else None,
                        "stored_next_run_at": (
                            automation.next_run_at.isoformat() if automation.next_run_at else None
                        ),
                        "last_run_at": (
                            automation.last_run_at.isoformat() if automation.last_run_at else None
                        ),
                        "dependencies": automation.dependencies_json or [],
                    }
                )
            pending = list(
                session.scalars(
                    select(AutomationFiringModel).where(
                        AutomationFiringModel.state.in_(
                            [
                                FiringState.PENDING.value,
                                FiringState.WAITING_DEPENDENCY.value,
                                FiringState.RUNNING.value,
                            ]
                        )
                    )
                ).all()
            )
            return {
                "now": now.isoformat(),
                "stats": self.stats.as_dict(),
                "heartbeat": self._read_heartbeat(session),
                "automations": automations,
                "pending_firings": [
                    {
                        "id": str(f.id),
                        "automation_id": str(f.automation_id),
                        "state": f.state,
                        "attempt": f.attempt,
                        "next_attempt_at": (
                            f.next_attempt_at.isoformat() if f.next_attempt_at else None
                        ),
                        "error": f.error,
                    }
                    for f in pending
                ],
            }
        finally:
            session.close()


def build_supervisor(settings: Settings | None = None) -> AutomationSupervisor:
    """Supervisor com o banco inicializado (cria as tabelas que faltarem)."""
    settings = settings or get_settings()
    engine = init_db(create_db_engine(settings), settings)
    return AutomationSupervisor(settings, session_factory=build_session_factory(engine))


def find_automation(session, automation_id: uuid.UUID) -> AutomationModel | None:
    return session.get(AutomationModel, automation_id)
