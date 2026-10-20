"""
Arquivo: src/agent/services/scheduler.py
Nome: scheduler.py
Propósito: expor a fachada do agendamento, delegando tudo ao runtime de automações.
Responsabilidade: camada de aplicação — compatibilidade com o ponto de entrada antigo do agendamento.
Componentes: start_scheduler, stop_scheduler, current_supervisor, schedule_enabled_on_run, schedule_disabled_on_run, legacy_scheduled_run.
Dependências: agent.automation, agent.persistence.models.
Observações: não há uma segunda implementação: tudo é delegado ao núcleo de automações.

Ponto de entrada antigo do agendamento.

O mecanismo real das automações vive em [`agent.automation`][agent.automation]: a
definição, o disparo idempotente, a verificação de dependências, a execução e o
supervisor headless. Este módulo continua existindo porque é ele que a API e os
serviços já conhecem — mas aqui não há uma segunda implementação: tudo é
delegado ao núcleo.

O protótipo anterior (APScheduler + `ScheduledRunModel`) tinha três defeitos que
quebravam o disparo de ponta a ponta: criava `ExecutionRunModel` **sem**
`root_task_id` (violava o contrato do banco), não era iniciado pelo ciclo de vida
da API e não tinha chave de idempotência. As linhas de `scheduled_runs` são
convertidas em automações na migração (o dado é preservado).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from agent.automation.enums import AutomationState
from agent.automation.store import AutomationService
from agent.automation.supervisor import AutomationSupervisor, build_supervisor
from agent.persistence.models import AutomationModel, ScheduledRunModel

logger = logging.getLogger(__name__)

_supervisor: AutomationSupervisor | None = None
_supervisor_task: asyncio.Task | None = None


def _get_next_run_time(cron_expr: str, base_time: datetime | None = None) -> datetime:
    """Calcula o próximo horário de execução baseado na expressão cron (UTC).

    Args:
        cron_expr: expressão cron da automação.
        base_time: instante de referência; por padrão, agora.

    Returns:
        O próximo horário de disparo, em UTC.
    """
    from agent.automation.timezones import next_cron_occurrence

    return next_cron_occurrence(cron_expr, "UTC", base_time or datetime.now())


# ─────────────────────────────────────────────────────────── ciclo de vida

def start_scheduler(settings: Any = None) -> asyncio.Task:
    """Inicia o runtime de automações em segundo plano.

    Devolve a tarefa: quem chama decide como esperar. Um `await` do processo
    inteiro trava o ciclo de vida da API — o runtime é um **tique**, não um
    bloqueio.

    Args:
        settings: configurações que definem o intervalo entre tiques.

    Returns:
        A tarefa asyncio que roda o supervisor.
    """
    global _supervisor, _supervisor_task
    if _supervisor_task and not _supervisor_task.done():
        return _supervisor_task
    _supervisor = build_supervisor(settings)
    interval = float(getattr(settings, "automation_tick_seconds", 5.0) or 5.0)
    _supervisor_task = asyncio.create_task(_supervisor.run_forever(interval_sec=interval))
    return _supervisor_task


async def stop_scheduler() -> None:
    """Para o runtime de automações.

    Observações:
        A tarefa é cancelada e aguardada; o cancelamento é absorvido.
    """
    global _supervisor, _supervisor_task
    if _supervisor is not None:
        _supervisor.stop()
    if _supervisor_task is not None:
        _supervisor_task.cancel()
        try:
            await _supervisor_task
        except asyncio.CancelledError:
            pass
        _supervisor_task = None
    _supervisor = None


def current_supervisor() -> AutomationSupervisor | None:
    """Supervisor de automações em execução.

    Returns:
        O supervisor ativo, ou `None` quando o runtime não foi iniciado.
    """
    return _supervisor


# ─────────────────────────────────────────────────────────── compatibilidade

def _as_uuid(schedule_id: str | uuid.UUID) -> uuid.UUID:
    """Normaliza um identificador de agendamento para `uuid.UUID`.

    Args:
        schedule_id: identificador em texto ou como UUID.

    Returns:
        O identificador normalizado.

    Raises:
        ValueError: quando o texto não é um UUID válido.
    """
    if isinstance(schedule_id, uuid.UUID):
        return schedule_id
    return uuid.UUID(str(schedule_id))


def schedule_enabled_on_run(session: Session, schedule_id: str | uuid.UUID) -> AutomationModel:
    """Ativa a automação e recalcula o próximo disparo.

    Args:
        session: sessão usada na operação.
        schedule_id: identificador da automação.

    Returns:
        A automação ativada.
    """
    key = _as_uuid(schedule_id)
    service = AutomationService(session)
    row = service.get(key)
    service.set_state(row.id, AutomationState.ENABLED)
    return row


def schedule_disabled_on_run(session: Session, schedule_id: str | uuid.UUID) -> AutomationModel:
    """Desativa a automação (para de disparar) preservando a definição.

    Args:
        session: sessão usada na operação.
        schedule_id: identificador da automação.

    Returns:
        A automação desativada.
    """
    key = _as_uuid(schedule_id)
    service = AutomationService(session)
    row = service.get(key)
    service.set_state(row.id, AutomationState.DISABLED)
    return row


def legacy_scheduled_run(session: Session, schedule_id: str | uuid.UUID) -> ScheduledRunModel | None:
    """Linha antiga de `scheduled_runs` (compatibilidade de leitura).

    Args:
        session: sessão usada na leitura.
        schedule_id: identificador do agendamento antigo.

    Returns:
        A linha antiga, ou `None` quando ela não existe ou o identificador é inválido.
    """
    try:
        return session.get(ScheduledRunModel, _as_uuid(schedule_id))
    except (ValueError, AttributeError):
        return None
