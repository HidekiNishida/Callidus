# src/agent/orchestrator/replan.py — revisar o plano quando uma etapa para no meio
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.orchestrator.consolidation import children_of
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec, apply_decomposition
from agent.persistence.models import TaskModel
from agent.services.task_service import TaskService

MAX_REPLANS = 2
_STOP = {TaskStatus.BLOCKED.value, TaskStatus.FAILED.value}
_CANCEL = {
    TaskStatus.PENDING.value,
    TaskStatus.READY.value,
    TaskStatus.PLANNING.value,
    TaskStatus.RETRY_PENDING.value,
}


def replan_under(session: Session, root_id: uuid.UUID) -> dict | None:
    """Se algum filho parou, revisa o pai uma vez e deixa o plano novo seguir."""
    kids = children_of(session, root_id)
    parents = [session.get(TaskModel, root_id)]
    seen = {root_id}
    pending = list(kids)
    while pending:
        current = pending.pop(0)
        if current.id in seen:
            continue
        seen.add(current.id)
        parents.append(current)
        pending.extend(children_of(session, current.id))
    for parent in parents:
        if parent is None:
            continue
        revised = replan_parent(session, parent)
        if revised:
            return revised
    return None


def replan_parent(session: Session, parent: TaskModel) -> dict | None:
    meta = dict(parent.metadata_json or {})
    if int(meta.get("replan_count") or 0) >= MAX_REPLANS:
        return None
    kids = children_of(session, parent.id)
    stopped = next((kid for kid in kids if kid.status in _STOP), None)
    if stopped is None:
        return None
    if any((kid.metadata_json or {}).get("replan") and kid.status not in {*_STOP, TaskStatus.CANCELLED.value, TaskStatus.COMPLETED.value} for kid in kids):
        return None
    done = [kid.title for kid in kids if kid.status == TaskStatus.COMPLETED.value]
    tasks = TaskService(session)
    cancelled: list[str] = []
    for kid in kids:
        if kid.id == stopped.id or children_of(session, kid.id):
            continue
        if kid.status in _CANCEL:
            tasks.update_status(
                kid.id,
                TaskStatusUpdate(status=TaskStatus.CANCELLED, reason="plano revisado"),
            )
            cancelled.append(kid.title)
    result = stopped.consolidated_result_json or {}
    reason = ""
    if isinstance(result, dict):
        inner = result.get("result") if isinstance(result.get("result"), dict) else result
        reason = str((inner or {}).get("error") or (stopped.metadata_json or {}).get("blocked_reason") or stopped.status)
    objective = (
        f"Replanejar o que falta de «{parent.title}». "
        f"Já concluído: {', '.join(done) or 'nada'}. Não refazer isso. "
        f"Parou em «{stopped.title}»: {reason[:240]}. "
        f"Objetivo original: {parent.objective[:500]}"
    )
    plan = DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Ver o que ainda falta",
                objective=objective,
                metadata={"tool": "list_dir", "tool_args": {"path": "."}, "atomic": True, "replan": True},
            ),
            SubTaskSpec(
                title="Seguir com o plano corrigido",
                objective=objective,
                metadata={"model_operation": True, "atomic": True, "replan": True},
                depends_on_indices=[0],
            ),
        ]
    )
    apply_decomposition(session, parent.project_id, parent.id, plan)
    meta["replan_count"] = int(meta.get("replan_count") or 0) + 1
    meta["last_replan_reason"] = reason[:240]
    parent.metadata_json = meta
    session.flush()
    return {
        "action": "replanned",
        "task_id": str(parent.id),
        "stopped_at": stopped.title,
        "cancelled": cancelled,
        "thought": f"Replanejei depois de «{stopped.title}». O que já passou fica como está.",
    }
