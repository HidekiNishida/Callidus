"""
Arquivo: src/agent/services/autonomous_worker.py
Nome: autonomous_worker.py
Propósito: descobrir runs autônomos ativos e entregá-los ao escalonador em segundo plano.
Responsabilidade: camada de aplicação — laço de descoberta e execução das operações autônomas.
Componentes: autonomous_loop, focused_run, build_scheduler, start_background_worker, stop_background_worker, enable_autonomous_on_run.
Dependências: agent.services.agent_scheduler, agent.services.query_service, agent.persistence.database.
Observações: nenhuma inferência é feita para descobrir se existe trabalho; a sessão fica aberta só durante a operação.

Worker autônomo: descobre runs ativos e os entrega ao escalonador.

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

**Foco**: só a run autônoma mais recente avança (a última mensagem da pessoa). O
rodízio entre todas as runs ativas fazia cada uma andar a uma fração da velocidade —
com um modelo local, ainda trocando o modelo carregado a cada passo — e a mensagem nova
parecia parada. As runs mais antigas esperam a vez, sem pausa nem cancelamento.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Iterable

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

# Passos que não avançaram nada (a run espera algo de fora): a run em foco cede a vez à
# seguinte por um tempo, para uma run parada não segurar as outras para sempre.
_IDLE_ACTIONS = frozenset({"noop", "run_stalled", "run_paused", "run_terminal"})
IDLE_BACKOFF_SEC = 30.0


def focused_run(
    runs: Iterable[ExecutionRunModel],
    idle_since: dict[str, float],
    *,
    now: float,
    backoff: float = IDLE_BACKOFF_SEC,
) -> ExecutionRunModel | None:
    """Escolhe a única run autônoma que avança neste tique.

    Args:
        runs: runs ativas.
        idle_since: quando cada run (por id) teve um passo sem avanço.
        now: instante monotônico atual.
        backoff: segundos em que uma run ociosa cede a vez.

    Returns:
        A run autônoma mais recente que não está cedendo a vez; se todas estão, a mais
        recente; `None` sem run autônoma.

    Observações:
        Mais recente = última mensagem da pessoa. As demais não são pausadas: andam
        quando a run em foco termina ou fica ociosa.
    """
    autonomous = [run for run in runs if (run.config_json or {}).get("autonomous")]
    if not autonomous:
        return None
    autonomous.sort(key=lambda run: (run.created_at is not None, run.created_at), reverse=True)
    for run in autonomous:
        idle = idle_since.get(str(run.id))
        if idle is None or now - idle >= backoff:
            return run
    return autonomous[0]


def _note_outcome(idle_since: dict[str, float], result, now: float) -> None:
    """Registra se o passo de uma run avançou, para o foco do próximo tique.

    Args:
        idle_since: marcação de ociosidade por id de run (alterada no lugar).
        result: desfecho devolvido pelo escalonador (ou `None`).
        now: instante monotônico atual.
    """
    if result is None or result.kind != "run_step" or not result.key.startswith("run:"):
        return
    run_id = result.key.split(":", 1)[1]
    if result.ok and result.action not in _IDLE_ACTIONS:
        idle_since.pop(run_id, None)
    else:
        idle_since[run_id] = now


def request_stop() -> None:
    """Pede o encerramento do laço autônomo."""
    _stop.set()


def build_scheduler(settings: Settings | None = None) -> AgentScheduler:
    """Escalonador do worker, com os tratadores de etapa de run e de consulta.

    Args:
        settings: configurações do processo; quando ausentes, são lidas do ambiente.

    Returns:
        O escalonador com os tratadores registrados.
    """
    settings = settings or get_settings()
    scheduler = AgentScheduler(settings)

    async def _run_step(operation) -> dict:
        """Avança um run autônomo e devolve a ação do passo."""
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
        """Resolve uma consulta pendente: estado persistido primeiro, inferência se faltar.

        Args:
            operation: operação submetida ao escalonador, com o identificador da consulta.

        Returns:
            Um dicionário com o desfecho da resolução.
        """
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
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Laço que descobre trabalho autônomo e o executa uma operação por vez.

    Args:
        interval_sec: intervalo entre tiques, em segundos.
        scheduler: escalonador a usar; quando ausente, é construído com as configurações do processo.
        clock: relógio monotônico (injetável em teste).
    """
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = build_session_factory(engine)
    scheduler = scheduler or build_scheduler(settings)
    idle_since: dict[str, float] = {}
    while not _stop.is_set():
        try:
            session = factory()
            try:
                stmt = select(ExecutionRunModel).where(
                    ExecutionRunModel.status == RunStatus.ACTIVE.value
                )
                runs = list(session.scalars(stmt).all())
                focus = focused_run(runs, idle_since, now=clock())
                if focus is not None:
                    # Prioridade acima das operações antigas que ainda estejam na fila.
                    scheduler.submit("run_step", f"run:{focus.id}", {"run_id": str(focus.id)}, priority=1)
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
            _note_outcome(idle_since, await scheduler.run_once(), clock())
        except Exception as exc:
            logger.warning("autonomous loop error: %s", exc)
        await asyncio.sleep(interval_sec)


def start_background_worker() -> asyncio.Task:
    """Inicia o worker autônomo em segundo plano.

    Returns:
        A tarefa asyncio do laço; a que já estava em execução, se houver.
    """
    global _worker_task
    if _worker_task and not _worker_task.done():
        return _worker_task
    _stop.clear()
    _worker_task = asyncio.create_task(autonomous_loop())
    return _worker_task


async def stop_background_worker() -> None:
    """Para o worker autônomo, cancelando a tarefa do laço.

    Observações:
        O cancelamento é absorvido; o laço é encerrado na próxima iteração.
    """
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
    """Marca um run como autônomo.

    Args:
        session: sessão usada na alteração.
        run_id: identificador do run.

    Returns:
        O run atualizado.

    Raises:
        LookupError: quando o run não existe.
    """
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise LookupError(str(run_id))
    cfg = dict(run.config_json or {})
    cfg["autonomous"] = True
    run.config_json = cfg
    return run
