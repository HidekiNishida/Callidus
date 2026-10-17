# src/agent/services/autonomous_worker.py — execução autônoma em segundo plano
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from agent.config import Settings, get_settings
from agent.domain.enums import RunStatus
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, create_db_engine
from agent.persistence.models import ExecutionRunModel

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()


def request_stop() -> None:
    _stop.set()


async def autonomous_loop(interval_sec: float = 2.0) -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = build_session_factory(engine)
    while not _stop.is_set():
        try:
            session = factory()
            try:
                stmt = select(ExecutionRunModel).where(ExecutionRunModel.status == RunStatus.ACTIVE.value)
                runs = list(session.scalars(stmt).all())
                for run in runs:
                    cfg = run.config_json or {}
                    if not cfg.get("autonomous"):
                        continue
                    orch = RunOrchestrator(session, settings)
                    await orch.step(run.id)
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.warning("autonomous tick failed: %s", exc)
            finally:
                session.close()
        except Exception as exc:
            logger.warning("autonomous loop error: %s", exc)
        await asyncio.sleep(interval_sec)


def start_background_worker() -> asyncio.Task:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return _worker_task
    _stop.clear()
    _worker_task = asyncio.create_task(autonomous_loop())
    return _worker_task


async def stop_background_worker() -> None:
    request_stop()
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None


def enable_autonomous_on_run(session, run_id: uuid.UUID) -> ExecutionRunModel:
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise LookupError(str(run_id))
    cfg = dict(run.config_json or {})
    cfg["autonomous"] = True
    run.config_json = cfg
    return run
