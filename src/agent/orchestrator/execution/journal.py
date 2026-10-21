"""
Arquivo: src/agent/orchestrator/execution/journal.py
Nome: journal.py
Propósito: registrar no banco o que a execução está fazendo e o que ela já falhou.
Responsabilidade: camada de aplicação — diário de execução (pensamento e histórico de falhas).
Componentes: note_thought, remember_failure.
Dependências: agent.persistence.models (EventLogModel), agent.orchestrator.stagnation (assinatura da falha),
agent.orchestrator.approach (memória de abordagem).
Observações: o histórico de falhas é a entrada da estagnação e do replanejamento — a memória da etapa vive aqui.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.domain.failures import Failure
from agent.orchestrator.approach import record_attempt
from agent.orchestrator.stagnation import error_signature, strategy_signature
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel


_PHASE_CATEGORY = {
    "quality": "decision",
    "execute": "decision",
    "investigate": "decision",
    "decompose": "decision",
    "plan": "activity",
    "tool": "activity",
    "thinking": "activity",
    "recover": "alert",
    "pause": "alert",
    "block": "error",
    "result": "result",
}


def note_thought(
    session,
    run: ExecutionRunModel,
    task: TaskModel | None,
    text: str,
    *,
    phase: str = "thinking",
    category: str | None = None,
) -> None:
    """Grava o que está acontecendo e publica a mesma frase no feed, se isso for seguro.

    A frase vai para `agent.thought` e, quando a categoria é válida, também para
    `work.explained`. Falha ao publicar a explicação não desfaz o registro nem a etapa.

    Args:
        session: sessão SQLAlchemy em uso.
        run: execução à qual o pensamento pertence.
        task: etapa em foco, quando houver.
        text: descrição curta do que está acontecendo.
        phase: fase da execução (`thinking`, `tool`, ...).
        category: categoria do feed; quando ausente, deriva da fase.
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
    _publish_explanation(task, text, phase=phase, category=category)


def _publish_explanation(task: TaskModel | None, text: str, *, phase: str, category: str | None) -> None:
    """Publica `work.explained` sem deixar a falha da narrativa derrubar a execução."""
    if task is None:
        return
    try:
        from agent.observability import emit
        from agent.orchestrator.narration import explanation_event

        payload = explanation_event(category or _PHASE_CATEGORY.get(phase, "activity"), text, phase=phase)
        if payload is None:
            return
        emit("work.explained", payload, task_id=task.id, commit=True)
    except Exception:
        return


def remember_failure(task: TaskModel, failure: Failure) -> dict[str, Any]:
    """Guarda a falha na tarefa: a próxima tentativa e a política de replanejamento leem daqui.

    Além do histórico, a etapa ganha a **memória de abordagem**: o que foi tentado, a hipótese
    da falha e o que precisa ser diferente na próxima tentativa. É essa memória que alimenta o
    prompt da etapa seguinte e que o replanejamento usa para escolher uma abordagem distinta.

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
    record_attempt(task, noted)
    _switch_operational_language(task, str(noted.get("cause") or ""))
    return noted


def _switch_operational_language(task: TaskModel, cause: str) -> None:
    """Se a saída inválida veio do inglês operacional, a próxima tentativa usa o pedido original."""
    try:
        from agent.orchestrator.language_strategy import switch_language

        updated = switch_language(task.metadata_json, cause)
        if updated is None:
            return
        task.metadata_json = {**(task.metadata_json or {}), "language": updated}
    except Exception:
        return


def failure_timestamp() -> str:
    """Instante atual em ISO-8601 (UTC) — usado nos registros de diagnóstico.

    Returns:
        A marca de tempo no formato ISO-8601 com sufixo UTC.
    """
    return datetime.now(timezone.utc).isoformat()
