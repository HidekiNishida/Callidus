# src/agent/orchestrator/global_verify.py — critérios globais de conclusão
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskCreate, TaskStatusUpdate
from agent.orchestrator.consolidation import children_of, verification_evidence_ok
from agent.persistence.models import TaskModel
from agent.services.task_service import TaskService


def _subtree_tasks(session: Session, root_id: uuid.UUID) -> list[TaskModel]:
    all_tasks = list(session.scalars(select(TaskModel)).all())
    ids = {root_id}
    changed = True
    while changed:
        changed = False
        for t in all_tasks:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True
    return [t for t in all_tasks if t.id in ids]


def evaluate_global_acceptance(session: Session, root_id: uuid.UUID) -> tuple[bool, str]:
    root = session.get(TaskModel, root_id)
    if root is None:
        return False, "root ausente"
    if TaskStatus(root.status) not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        return False, "root ainda não concluído"

    for t in _subtree_tasks(session, root_id):
        meta = t.metadata_json or {}
        if meta.get("verification") and TaskStatus(t.status) == TaskStatus.COMPLETED:
            if not verification_evidence_ok(session, t):
                return False, f"evidência ausente: {t.title}"

    report = root.consolidated_result_json or {}
    if report and report.get("achieved") is False:
        return False, "consolidação do objetivo falhou"

    return True, "ok"


def reopen_verification_gaps(session: Session, root_id: uuid.UUID) -> list[uuid.UUID]:
    """Reabre tarefas de verificação concluídas sem evidência passante."""
    ts = TaskService(session)
    reopened: list[uuid.UUID] = []
    for t in _subtree_tasks(session, root_id):
        meta = t.metadata_json or {}
        if not meta.get("verification"):
            continue
        if TaskStatus(t.status) != TaskStatus.COMPLETED:
            continue
        if verification_evidence_ok(session, t):
            continue
        ts.update_status(t.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        ts.update_status(
            t.id,
            TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason="evidência global insuficiente"),
        )
        reopened.append(t.id)
        if t.parent_id:
            parent = ts.get_task(t.parent_id)
            if TaskStatus(parent.status) == TaskStatus.COMPLETED:
                ts.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                ts.update_status(
                    parent.id,
                    TaskStatusUpdate(status=TaskStatus.PLANNING, reason="reabertura hierárquica"),
                )
    return reopened


def ensure_global_verification_task(
    session: Session,
    project_id: uuid.UUID,
    root: TaskModel,
) -> TaskModel | None:
    """Cria subtarefa de verificação global se o root pedir explicitamente."""
    meta = root.metadata_json or {}
    if not meta.get("global_verification"):
        return None
    kids = children_of(session, root.id)
    if any((k.metadata_json or {}).get("global_verification_step") for k in kids):
        return None
    spec = meta.get("global_verification")
    if not isinstance(spec, dict):
        spec = {"type": "pytest", "path": "."}
    task = TaskService(session).create_task(
        project_id,
        TaskCreate(
            title="Verificação global",
            objective="Validar critérios globais do objetivo",
            kind="operation",
            parent_id=root.id,
            metadata={"verification": spec, "global_verification_step": True},
        ),
    )
    if TaskStatus(root.status) == TaskStatus.COMPLETED:
        TaskService(session).update_status(
            root.id,
            TaskStatusUpdate(status=TaskStatus.PLANNING, reason="verificação global pendente"),
        )
    return task
