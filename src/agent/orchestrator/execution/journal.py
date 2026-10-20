"""
Arquivo: src/agent/orchestrator/execution/journal.py
Nome: journal.py
Propósito: registrar no banco o que a execução está fazendo e o que ela já falhou.
Responsabilidade: camada de aplicação — diário de execução (pensamento e histórico de falhas).
Componentes: note_thought, remember_failure.
Dependências: agent.persistence.models (EventLogModel), agent.orchestrator.stagnation (assinatura da falha).
Observações: o histórico de falhas é a entrada da estagnação e do replanejamento — a memória da etapa vive aqui.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.domain.failures import Failure
from agent.orchestrator.stagnation import error_signature, strategy_signature
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel


def note_thought(
    session,
    run: ExecutionRunModel,
    task: TaskModel | None,
    text: str,
    *,
    phase: str = "thinking",
) -> None:
    """Grava o que está acontecendo e libera o banco para a interface ler durante a inferência.

    Args:
        session: sessão SQLAlchemy em uso.
        run: execução à qual o pensamento pertence.
        task: etapa em foco, quando houver.
        text: descrição curta do que está acontecendo.
        phase: fase da execução (`thinking`, `tool`, ...).
    """
    session.add(
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            task_id=task.id if task is not None else None,
            event_type="agent.thought",
            payload_json={"phase": phase, "text": text[:400], "task": task.title if task is not None else None},
        )
    )
    session.commit()


def remember_failure(task: TaskModel, failure: Failure) -> dict[str, Any]:
    """Guarda a falha na tarefa: a próxima tentativa e a política de replanejamento leem daqui.

    Args:
        task: etapa que falhou.
        failure: falha estruturada, com categoria e causa.

    Returns:
        A falha registrada, já com assinatura e estratégia (usadas para detectar estagnação).
    """
    meta = dict(task.metadata_json or {})
    history = list(meta.get("failures") or [])[-4:]
    noted = {**failure.as_dict(), "signature": error_signature(failure.as_dict()), "strategy": strategy_signature(task)}
    history.append(noted)
    meta["failures"] = history
    meta["last_failure"] = noted
    task.metadata_json = meta
    return noted


def failure_timestamp() -> str:
    """Instante atual em ISO-8601 (UTC) — usado nos registros de diagnóstico.

    Returns:
        A marca de tempo no formato ISO-8601 com sufixo UTC.
    """
    return datetime.now(timezone.utc).isoformat()
