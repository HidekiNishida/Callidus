# src/agent/services/autonomous_worker.py — execução autônoma em segundo plano
"""Worker autônomo: descobre runs ativos e os entrega ao escalonador.

Duas responsabilidades, deliberadamente separadas:

1. **Descoberta** — a cada tique, o worker pergunta ao banco quais runs estão
   ativos e autônomos. É uma consulta ao SQLite: **nenhuma inferência** é feita para
   descobrir se existe trabalho.
2. **Execução** — os runs entram na fila do
   [`AgentScheduler`][agent.services.agent_scheduler.AgentScheduler], que executa uma
   operação por vez. É o escalonador que garante exclusividade; o worker apenas
   alimenta a fila.

Antes, o worker chamava o orquestrador direto e segurava a sessão do banco durante a
inferência. Agora a sessão é aberta por operação e fechada em seguida: uma inferência
longa não segura a conexão.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from agent.config import Settings, get_settings
from agent.domain.agent_enums import QueryStatus
from agent.domain.enums import RunStatus
from agent.orchestrator.decomposition import profile_from_run_config
from agent.orchestrator.runner import RunOrchestrator, _select_provider
from agent.persistence.database import build_session_factory, create_db_engine
from agent.persistence.models import AgentQueryModel, ExecutionRunModel
from agent.services.agent_scheduler import AgentScheduler
from agent.services.query_service import QueryService

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()


def request_stop() -> None:
    _stop.set()


def build_scheduler(settings: Settings | None = None) -> AgentScheduler:
    """Escalonador do worker, com os tratadores de etapa de run e de consulta."""
    settings = settings or get_settings()
    scheduler = AgentScheduler(settings)

    async def _run_step(operation) -> dict:
        run_id = uuid.UUID(operation.payload["run_id"])
        engine = create_db_engine(settings)
        factory = build_session_factory(engine)
        session = factory()
        try:
            orchestrator = RunOrchestrator(session, settings)
            result = await orchestrator.step(run_id)
            session.commit()
            return {"action": str(result.get("action") or "stepped"), "run_id": str(run_id)}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _answer_query(operation) -> dict:
        """Resolve uma consulta pendente: estado persistido primeiro, inferência se faltar."""
        query_id = uuid.UUID(operation.payload["query_id"])
        engine = create_db_engine(settings)
        factory = build_session_factory(engine)
        session = factory()
        try:
            queries = QueryService(session, settings)
            provider = _select_provider(settings, {})
            profile = profile_from_run_config({}, settings, provider=provider)
            query = await queries.resolve(query_id, provider=provider, profile=profile)
            session.commit()
            return {
                "action": "query_answered",
                "query_id": str(query_id),
                "status": query.status,
            }
        except Exception as exc:
            # **Confirma** em vez de desfazer: a tentativa da consulta precisa sobreviver à
            # falha. Desfazer a transação devolveria a consulta a PENDING com o contador
            # intacto e ela seria reenviada a cada tique, sem nunca chegar ao limite.
            try:
                session.commit()
            except Exception:  # pragma: no cover - sessão inutilizável
                session.rollback()
            logger.warning("consulta %s falhou: %s", query_id, exc)
            return {"action": "query_failed", "query_id": str(query_id), "error": str(exc)}
        finally:
            session.close()

    scheduler.register("run_step", _run_step)
    scheduler.register("query", _answer_query)
    return scheduler


async def autonomous_loop(
    interval_sec: float = 2.0,
    scheduler: AgentScheduler | None = None,
) -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = build_session_factory(engine)
    scheduler = scheduler or build_scheduler(settings)
    while not _stop.is_set():
        try:
            session = factory()
            try:
                stmt = select(ExecutionRunModel).where(
                    ExecutionRunModel.status == RunStatus.ACTIVE.value
                )
                runs = list(session.scalars(stmt).all())
                for run in runs:
                    cfg = run.config_json or {}
                    if not cfg.get("autonomous"):
                        continue
                    scheduler.submit("run_step", f"run:{run.id}", {"run_id": str(run.id)})
                # Consultas pendentes entram na mesma fila: uma operação por vez.
                pending = list(
                    session.scalars(
                        select(AgentQueryModel).where(
                            AgentQueryModel.status == QueryStatus.PENDING.value
                        )
                    ).all()
                )
                for query in pending:
                    scheduler.submit("query", f"query:{query.id}", {"query_id": str(query.id)})
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.warning("autonomous tick failed: %s", exc)
            finally:
                session.close()
            # Uma operação por vez: o escalonador decide a ordem e o executor
            # compartilhado garante que só uma inferência esteja ativa.
            await scheduler.run_once()
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
