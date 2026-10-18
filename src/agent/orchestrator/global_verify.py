# src/agent/orchestrator/global_verify.py — critérios globais de conclusão
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.failures import Failure, FailureCategory, FailureCause
from agent.domain.schemas import TaskCreate, TaskStatusUpdate
from agent.orchestrator.consolidation import (
    children_of,
    collect_evidences,
    verification_evidence_ok,
    verification_spec,
)
from agent.persistence.models import TaskModel
from agent.services.task_service import TaskService
from agent.verification.fingerprint import is_current


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
        if verification_spec(t) and TaskStatus(t.status) == TaskStatus.COMPLETED:
            if not verification_evidence_ok(session, t):
                return False, f"evidência ausente ou desatualizada: {t.title}"

    report = root.consolidated_result_json or {}
    if report and report.get("achieved") is False:
        return False, "consolidação do objetivo falhou"

    return True, "ok"


def _gap_failure(session: Session, task: TaskModel) -> Failure:
    evs = collect_evidences(session, task.id)
    last = evs[-1] if evs else None
    if last and last.get("passed") is True and not is_current((last.get("detail") or {}).get("artifacts")):
        paths = ", ".join((last["detail"]["artifacts"].get("paths") or []))
        return Failure(
            FailureCategory.RECOVERABLE,
            FailureCause.STALE_EVIDENCE,
            f"os arquivos verificados ({paths}) mudaram depois da verificação; refazer com o estado atual",
        )
    return Failure(FailureCategory.RECOVERABLE, FailureCause.VERIFICATION_FAILED, "concluída sem evidência válida")


def reopen_verification_gaps(session: Session, root_id: uuid.UUID) -> list[uuid.UUID]:
    """Reabre tarefas verificadas cuja evidência mais recente não passou ou ficou desatualizada; o motivo
    entra em `last_failure`/`failures`. Desatualizada volta a VERIFYING: verifica-se o estado atual antes
    de repetir a operação. Sem evidência válida volta a RETRY_PENDING."""
    ts = TaskService(session)
    reopened: list[uuid.UUID] = []
    for t in _subtree_tasks(session, root_id):
        if not verification_spec(t):
            continue
        if TaskStatus(t.status) != TaskStatus.COMPLETED:
            continue
        if verification_evidence_ok(session, t):
            continue
        failure = _gap_failure(session, t)
        meta = dict(t.metadata_json or {})
        meta["last_failure"] = failure.as_dict()
        meta["failures"] = [*(meta.get("failures") or []), failure.as_dict()][-5:]
        t.metadata_json = meta
        ts.update_status(t.id, TaskStatusUpdate(status=TaskStatus.VERIFYING, reason=failure.detail))
        if failure.cause != FailureCause.STALE_EVIDENCE:
            ts.update_status(
                t.id,
                TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason=failure.detail),
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
