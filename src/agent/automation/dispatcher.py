"""
Arquivo: src/agent/automation/dispatcher.py
Nome: dispatcher.py
Propósito: registrar de forma idempotente os disparos elegíveis de uma automação.
Responsabilidade: camada de aplicação — criação das linhas de disparo e aplicação da política de disparos perdidos.
Componentes: Dispatcher, DispatchResult, temporal_key, event_key, manual_key.
Dependências: agent.automation.contracts, agent.automation.enums, agent.automation.store, agent.persistence.models.
Observações: a chave de idempotência é única no banco; reprocessar o mesmo disparo não executa duas vezes.

O despachante decide que chegou a hora e **registra** o disparo.

Ele não executa nada: cria a linha de disparo com uma chave de idempotência. Como a
chave é única no banco, reprocessar o mesmo disparo (reinício do runtime, tique
duplicado, evento repetido) nunca produz uma segunda execução equivalente.

A política de disparos perdidos é aplicada aqui — e é a que está gravada na
automação: `run_once`, `catch_up`, `group` ou `skip`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.automation.contracts import TriggerSpec
from agent.automation.enums import FiringState, MissedPolicy
from agent.automation.store import AutomationService
from agent.automation.timezones import to_utc
from agent.persistence.models import AutomationFiringModel, AutomationModel, EventLogModel


@dataclass
class DispatchResult:
    """O que o despachante fez."""

    created: list[AutomationFiringModel]
    skipped: int = 0
    duplicates: int = 0

    def as_dict(self) -> dict:
        """Desfecho do despacho como dicionário serializável.

        Returns:
            Um dicionário com os disparos criados, os ignorados e os duplicados.
        """
        return {
            "created": [str(f.id) for f in self.created],
            "skipped": self.skipped,
            "duplicates": self.duplicates,
        }


def temporal_key(automation_id: uuid.UUID, kind: str, moment: datetime) -> str:
    """Chave de idempotência de um disparo temporal.

    Args:
        automation_id: identificador da automação.
        kind: tipo do disparo (política aplicada).
        moment: instante agendado.

    Returns:
        A chave de idempotência.
    """
    stamp = to_utc(moment).isoformat()
    return f"auto:{automation_id}:{kind}:{stamp}"


def event_key(automation_id: uuid.UUID, source: str, event_id: str) -> str:
    """Chave de idempotência de um disparo por evento.

    Args:
        automation_id: identificador da automação.
        source: origem do evento.
        event_id: identificador do evento.

    Returns:
        A chave de idempotência.
    """
    return f"auto:{automation_id}:event:{source}:{event_id}"


def manual_key(automation_id: uuid.UUID, tag: str = "manual") -> str:
    """Chave de idempotência de um disparo manual, sempre única.

    Args:
        automation_id: identificador da automação.
        tag: marca do disparo manual.

    Returns:
        A chave de idempotência.
    """
    return f"auto:{automation_id}:{tag}:{uuid.uuid4().hex}"


class Dispatcher:
    """Registra disparos elegíveis.

    Atributos:
        _session: sessão usada nas gravações.
        _service: serviço das automações, usado para ler o gatilho da definição.
    """

    def __init__(self, session: Session) -> None:
        """Cria o despachante ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session
        self._service = AutomationService(session)

    # ------------------------------------------------------------ temporal

    def dispatch_due(self, automation: AutomationModel, *, now: datetime | None = None) -> DispatchResult:
        """Registra os disparos vencidos de uma automação temporal.

        Args:
            automation: automação cujo gatilho é avaliado.
            now: instante de referência; por padrão, agora.

        Returns:
            O desfecho do despacho, com os disparos criados, ignorados e duplicados.
        """
        moment = to_utc(now or datetime.now(timezone.utc))
        trigger = self._service.trigger_of(automation)
        if trigger.kind.value == "event":
            return DispatchResult(created=[])

        spec = TriggerSpec.model_validate(automation.trigger_json or {})
        window_start = to_utc(automation.last_run_at) if automation.last_run_at else None
        if window_start is None:
            # Sem histórico: o ponto de partida é a criação da automação — é a partir
            # daí que uma ocorrência pode ter ficado pendente.
            window_start = to_utc(automation.created_at)
        occurrences = trigger.occurrences(window_start, moment, limit=200)
        result = DispatchResult(created=[])
        if not occurrences:
            return result

        policy = MissedPolicy(automation.missed_policy or spec.missed_policy.value)

        if policy is MissedPolicy.SKIP:
            firing = self._create(
                automation,
                key=temporal_key(automation.id, "skipped", occurrences[-1]),
                scheduled_for=occurrences[-1],
                state=FiringState.SKIPPED.value,
                result={
                    "policy": policy.value,
                    "missed_occurrences": len(occurrences),
                    "occurrences": [o.isoformat() for o in occurrences],
                    "note": "ocorrências perdidas ignoradas pela política da automação",
                },
            )
            if firing is not None:
                result.created.append(firing)
            else:
                result.duplicates += 1
            self._advance(automation, occurrences[-1], moment)
            return result

        if policy is MissedPolicy.CATCH_UP:
            limit = max(1, int(spec.max_catch_up or 10))
            for occurrence in occurrences[-limit:]:
                firing = self._create(
                    automation,
                    key=temporal_key(automation.id, "time", occurrence),
                    scheduled_for=occurrence,
                    state=FiringState.PENDING.value,
                    result={"policy": policy.value, "occurrences": [occurrence.isoformat()]},
                )
                if firing is not None:
                    result.created.append(firing)
                else:
                    result.duplicates += 1
            self._advance(automation, occurrences[-1], moment)
            return result

        # `run_once` e `group`: um disparo só, carregando as ocorrências perdidas.
        last = occurrences[-1]
        firing = self._create(
            automation,
            key=temporal_key(automation.id, policy.value, last),
            scheduled_for=last,
            state=FiringState.PENDING.value,
            result={
                "policy": policy.value,
                "missed_occurrences": len(occurrences),
                "occurrences": [o.isoformat() for o in occurrences],
                "grouped": policy is MissedPolicy.GROUP,
            },
        )
        if firing is not None:
            result.created.append(firing)
        else:
            result.duplicates += 1
        self._advance(automation, last, moment)
        return result

    # ------------------------------------------------------------ evento

    def dispatch_event(
        self, automation: AutomationModel, candidate
    ) -> AutomationFiringModel | None:
        """Registra o disparo de um evento interno (idempotente pelo identificador do evento).

        Args:
            automation: automação que escuta o evento.
            candidate: evento candidato, com origem, tipo, identificador e instante.

        Returns:
            O disparo criado, ou `None` quando a chave já existia.
        """
        key = event_key(automation.id, candidate.source, candidate.event_id)
        firing = self._create(
            automation,
            key=key,
            scheduled_for=to_utc(candidate.occurred_at),
            state=FiringState.PENDING.value,
            result={
                "policy": "event",
                "event_id": candidate.event_id,
                "event_type": candidate.event_type,
                "source": candidate.source,
                "payload": candidate.payload,
            },
        )
        return firing

    # ------------------------------------------------------------ manual

    def dispatch_manual(
        self,
        automation: AutomationModel,
        *,
        tag: str = "manual",
        state: str = FiringState.PENDING.value,
        result: dict | None = None,
        scheduled_for: datetime | None = None,
    ) -> AutomationFiringModel | None:
        """Disparo manual ("executar agora", "testar"). Sempre único.

        Args:
            automation: automação a disparar.
            tag: marca do disparo manual.
            state: estado inicial do disparo.
            result: conteúdo do resultado inicial.
            scheduled_for: instante agendado; por padrão, agora.

        Returns:
            O disparo criado.
        """
        firing = self._create(
            automation,
            key=manual_key(automation.id, tag),
            scheduled_for=to_utc(scheduled_for or datetime.now(timezone.utc)),
            state=state,
            result=result or {"policy": "manual", "tag": tag},
        )
        return firing

    # ------------------------------------------------------------ interno

    def _create(
        self,
        automation: AutomationModel,
        *,
        key: str,
        scheduled_for: datetime,
        state: str,
        result: dict | None = None,
    ) -> AutomationFiringModel | None:
        """Cria a linha de disparo, respeitando a chave de idempotência.

        Args:
            automation: automação disparada.
            key: chave de idempotência do disparo.
            scheduled_for: instante agendado.
            state: estado inicial do disparo.
            result: conteúdo do resultado inicial.

        Returns:
            O disparo criado, ou `None` quando a chave já existia.
        """
        firing = AutomationFiringModel(
            automation_id=automation.id,
            project_id=automation.project_id,
            idempotency_key=key,
            scheduled_for=to_utc(scheduled_for),
            state=state,
            attempt=0,
            max_attempts=int(automation.max_attempts or 3),
            result_json=result,
        )
        # Savepoint: uma chave duplicada desfaz só este disparo, não o trabalho em curso.
        # O objeto entra **dentro** do savepoint — senão o rollback do savepoint não o
        # desfaz e a transação externa fica inválida.
        savepoint = self._session.begin_nested()
        try:
            self._session.add(firing)
            self._session.flush()
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            return None
        self._session.add(
            EventLogModel(
                project_id=automation.project_id,
                event_type="automation.fired",
                payload_json={
                    "automation_id": str(automation.id),
                    "firing_id": str(firing.id),
                    "scheduled_for": firing.scheduled_for.isoformat(),
                    "state": firing.state,
                },
            )
        )
        return firing

    def _advance(self, automation: AutomationModel, last_occurrence: datetime, now: datetime) -> None:
        """Avança o marcador de última execução e recalcula o próximo disparo.

        Args:
            automation: automação disparada.
            last_occurrence: última ocorrência coberta por este despacho.
            now: instante de referência do recálculo.
        """
        automation.last_run_at = to_utc(last_occurrence)
        automation.next_run_at = self._service.next_occurrence(automation, after=now)
