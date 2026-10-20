"""
Arquivo: src/agent/orchestrator/resume.py
Nome: resume.py
Propósito: onde a tarefa parou e o que ainda falta.
Responsabilidade: camada de aplicação.
Componentes: build_resume_brief, apply_resume, resume_root.
Dependências: agent.domain.enums, agent.domain.schemas, agent.orchestrator.consolidation, agent.persistence.models, agent.services.project_service, __future__….
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind, RunStatus, TaskStatus
from agent.domain.schemas import MemoryCreate
from agent.orchestrator.consolidation import children_of
from agent.persistence.models import ExecutionRunModel, TaskModel
from agent.services.project_service import ProjectService

_DONE = {TaskStatus.COMPLETED.value}
_STOPPED = {
    TaskStatus.BLOCKED.value,
    TaskStatus.FAILED.value,
    TaskStatus.RETRY_PENDING.value,
    TaskStatus.RUNNING.value,
    TaskStatus.VERIFYING.value,
    TaskStatus.PLANNING.value,
    TaskStatus.READY.value,
    TaskStatus.PENDING.value,
}


def _reason(task: TaskModel) -> str:
    """Diz por que a tarefa parou.

    Args:
        task: tarefa parada.

    Returns:
        O erro registrado, o motivo do bloqueio ou, na falta deles, o estado da tarefa.
    """
    result = task.consolidated_result_json or {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if isinstance(inner, dict) and inner.get("error"):
        return str(inner["error"])[:240]
    meta = task.metadata_json or {}
    if meta.get("blocked_reason"):
        return str(meta["blocked_reason"])[:240]
    return task.status


def build_resume_brief(session: Session, root: TaskModel) -> dict:
    """Monta o resumo do que já foi feito e do que falta para retomar o trabalho.

    Args:
        session: sessão do banco.
        root: tarefa raiz do objetivo.

    Returns:
        Um dicionário com as etapas concluídas, as pendentes, o ponto de parada, o motivo e a instrução corrigida.

    Observações:
        A instrução corrigida só existe quando a parada exige ação de fora; ela é o que evita refazer o trabalho já feito.
    """
    kids = children_of(session, root.id)
    done = [task for task in kids if task.status in _DONE]
    pending = [task for task in kids if task.status not in _DONE]
    stopped = next((task for task in pending if task.status in _STOPPED), pending[0] if pending else None)
    missing_titles = [task.title for task in pending]
    done_titles = [task.title for task in done]
    reason = _reason(stopped) if stopped is not None else ""
    corrected = None
    if stopped is not None and stopped.status in {
        TaskStatus.BLOCKED.value,
        TaskStatus.FAILED.value,
        TaskStatus.RETRY_PENDING.value,
    }:
        missing = ", ".join(missing_titles) or stopped.title
        finished = ", ".join(done_titles) or "nada concluído ainda"
        corrected = (
            f"{root.objective.strip()}\n\n"
            f"Continuar a partir de «{stopped.title}», sem refazer o que já passou ({finished}). "
            f"Ainda falta: {missing}. Motivo da parada: {reason}."
        )
    return {
        "root_id": str(root.id),
        "stopped_at": stopped.title if stopped is not None else None,
        "stopped_status": stopped.status if stopped is not None else None,
        "reason": reason,
        "done": done_titles,
        "missing": missing_titles,
        "instruction": root.objective,
        "corrected_instruction": corrected,
        "can_continue": root.status not in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value},
    }


def apply_resume(session: Session, root: TaskModel, brief: dict) -> ExecutionRunModel | None:
    """Aplica a retomada: corrige o objetivo e reativa a execução pausada.

    Args:
        session: sessão do banco.
        root: tarefa raiz do objetivo.
        brief: resumo da retomada produzido por `build_resume_brief`.

    Returns:
        A run reativada, ou `None` quando não há execução pausada para retomar.

    Observações:
        O objetivo anterior fica guardado nos metadados e a instrução corrigida vira memória contextual da conversa.
    """
    corrected = brief.get("corrected_instruction")
    if isinstance(corrected, str) and corrected.strip() and corrected.strip() != (root.objective or "").strip():
        meta = dict(root.metadata_json or {})
        meta.setdefault("objective_before_resume", root.objective)
        root.metadata_json = meta
        root.objective = corrected.strip()
        ProjectService(session).add_memory(
            root.project_id,
            MemoryCreate(
                kind=MemoryKind.CONTEXTUAL,
                title="Retomada",
                content=corrected.strip(),
                task_id=root.id,
                conversation_id=root.conversation_id,
                source_refs=[f"task:{root.id}"],
            ),
        )
    run = session.scalar(
        select(ExecutionRunModel)
        .where(
            ExecutionRunModel.root_task_id == root.id,
            ExecutionRunModel.status == RunStatus.PAUSED.value,
        )
        .order_by(ExecutionRunModel.created_at.desc())
    )
    if run is None:
        return None
    cfg = dict(run.config_json or {})
    cfg["autonomous"] = True
    run.config_json = cfg
    run.status = RunStatus.ACTIVE.value
    session.flush()
    return run


def resume_root(session: Session, task_id: uuid.UUID, *, apply: bool) -> dict:
    """Retoma o trabalho a partir da raiz do objetivo.

    Args:
        session: sessão do banco.
        task_id: identificador da tarefa a partir da qual a retomada é calculada.
        apply: quando verdadeiro, aplica a retomada; quando falso, devolve apenas o resumo.

    Returns:
        O resumo da retomada, com o identificador da run reativada quando houve.

    Raises:
        LookupError: quando a tarefa indicada não existe.
    """
    root = session.get(TaskModel, task_id)
    if root is None:
        raise LookupError(str(task_id))
    while root.parent_id is not None:
        parent = session.get(TaskModel, root.parent_id)
        if parent is None:
            break
        root = parent
    brief = build_resume_brief(session, root)
    run = apply_resume(session, root, brief) if apply else None
    brief["reactivated_run_id"] = str(run.id) if run is not None else None
    brief["instruction"] = root.objective
    return brief
