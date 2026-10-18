# src/agent/services/scheduler.py — serviço de agendamento de execuções
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from croniter import croniter
from sqlalchemy import select

from agent.config import Settings, get_settings
from agent.persistence.database import build_session_factory, create_db_engine
from agent.persistence.models import ExecutionRunModel, ScheduledRunModel
from agent.domain.enums import RunStatus
from agent.orchestrator.runner import RunOrchestrator

logger = __import__('logging').getLogger(__name__)

_scheduler: Any = None  # APScheduler BackgroundScheduler instance
_scheduler_task: asyncio.Task | None = None
_stop_event = asyncio.Event()


def _get_next_run_time(cron_expr: str, base_time: datetime | None = None) -> datetime:
    """Calcula o próximo horário de execução baseado na expressão cron."""
    base = base_time or datetime.now()
    itr = croniter(cron_expr, base)
    return itr.get_next(datetime)


async def _schedule_job(schedule_id: str) -> None:
    """Job chamado pelo APScheduler para disparar uma execução."""
    logger.info(f"Disparando job agendado para schedule {schedule_id}")
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = build_session_factory(engine)
    session = factory()
    try:
        # Obter o schedule
        stmt = select(ScheduledRunModel).where(ScheduledRunModel.id == schedule_id)
        scheduled = session.scalars(stmt).first()
        if not scheduled or not scheduled.enabled:
            logger.warning(f"Schedule {schedule_id} não encontrado ou desabilitado")
            return

        # Criar uma nova ExecutionRun a partir do schedule
        run = ExecutionRunModel(
            project_id=scheduled.project_id,
            config_json=scheduled.config_json,
            status=RunStatus.ACTIVE.value,  # Para que o worker autônomo a pegue
        )
        session.add(run)
        session.commit()
        logger.info(f"ExecutionRun {run.id} criado a partir do schedule {schedule_id}")

        # Atualizar o schedule com o horário da última execução e calcular o próximo
        scheduled.last_run_at = datetime.now()
        scheduled.next_run_at = _get_next_run_time(scheduled.cron_expression, scheduled.last_run_at)
        session.add(scheduled)
        session.commit()
    except Exception as exc:
        logger.error(f"Falha ao disparar job agendado {schedule_id}: {exc}")
        session.rollback()
    finally:
        session.close()


async def start_scheduler() -> None:
    """Inicia o serviço de agendamento em segundo plano."""
    global _scheduler, _scheduler_task
    if _scheduler is not None:
        logger.warning("Scheduler já está iniciado")
        return

    settings = get_settings()
    engine = create_db_engine(settings)
    factory = build_session_factory(engine)

    # Importar APScheduler aqui para evitar carregamento se não usado
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.date import DateTrigger

    _scheduler = AsyncIOScheduler()
    _scheduler.start()

    # Carregar schedules habilitados do banco
    session = factory()
    try:
        stmt = select(ScheduledRunModel).where(ScheduledRunModel.enabled == True)  # noqa: E712
        schedules = session.scalars(stmt).all()
        for sched in schedules:
            # Calcular o próximo horário de execução
            next_run = _get_next_run_time(sched.cron_expression)
            # Adicionar job ao scheduler
            job = _scheduler.add_job(
                _schedule_job,
                trigger='cron',
                cron_expression=sched.cron_expression,
                id=str(sched.id),
                replace_existing=True,
            )
            logger.info(f"Schedule {sched.id} adicionado com próximo horário em {next_run}")
            # Atualizar o próximo horário no banco (opcional, já que o job vai atualizar após execução)
            sched.next_run_at = next_run
            session.add(sched)
        session.commit()
    except Exception as exc:
        logger.error(f"Falha ao carregar schedules: {exc}")
        session.rollback()
    finally:
        session.close()

    # Mantém o serviço vivo até que seja parado
    await _stop_event.wait()


def stop_scheduler() -> None:
    """Para o serviço de agendamento."""
    global _scheduler, _scheduler_task, _stop_event
    if _scheduler is None:
        return
    _stop_event.set()
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Scheduler parado")


def schedule_enabled_on_run(session, schedule_id: str) -> ScheduledRunModel:
    """Marca um schedule como habilitado."""
    sched = session.get(ScheduledRunModel, schedule_id)
    if sched is None:
        raise LookupError(str(schedule_id))
    sched.enabled = True
    return sched


def schedule_disabled_on_run(session, schedule_id: str) -> ScheduledRunModel:
    """Marca um schedule como desabilitado."""
    sched = session.get(ScheduledRunModel, schedule_id)
    if sched is None:
        raise LookupError(str(schedule_id))
    sched.enabled = False
    return sched