# src/agent/orchestrator/consolidation.py — consolidação bottom-up
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.persistence.models import EvidenceModel, TaskModel
from agent.services.task_service import TaskService
from agent.verification.fingerprint import is_current


def verification_spec(task: TaskModel) -> dict | None:
    """Verificação declarada ou, para escrita sem declaração, a implícita que já rodou."""
    meta = task.metadata_json or {}
    return meta.get("verification") or meta.get("implicit_verification")


def verification_evidence_ok(session: Session, task: TaskModel) -> bool:
    """Vale só a evidência mais recente: precisa ter passado e os arquivos que ela avaliou não podem ter
    mudado desde então (evidência desatualizada não conta, mas fica gravada)."""
    if not verification_spec(task):
        return True
    evs = collect_evidences(session, task.id)
    if not evs or evs[-1].get("passed") is not True:
        return False
    detail = evs[-1].get("detail") or {}
    return detail.get("state") != "desatualizado" and is_current(detail.get("artifacts"))


def superseded(task: TaskModel) -> bool:
    """Etapa parada que um replanejamento já substituiu: não conta mais como pendência."""
    return bool((task.metadata_json or {}).get("superseded_by_replan"))


def settled(task: TaskModel) -> bool:
    """Filho que não impede o pai de seguir: concluído, cancelado ou falho já substituído."""
    status = TaskStatus(task.status)
    return status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} or (
        status == TaskStatus.FAILED and superseded(task)
    )


def children_of(session: Session, parent_id: uuid.UUID) -> list[TaskModel]:
    stmt = select(TaskModel).where(TaskModel.parent_id == parent_id)
    return list(session.scalars(stmt).all())


_TO_VERIFYING: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.PLANNING: [TaskStatus.VERIFYING],
    TaskStatus.READY: [TaskStatus.RUNNING, TaskStatus.VERIFYING],
    TaskStatus.RUNNING: [TaskStatus.VERIFYING],
    TaskStatus.VERIFYING: [],
}


def _walk(ts: TaskService, task_id: uuid.UUID, path: list[TaskStatus], reason: str | None = None) -> None:
    for status in path:
        ts.update_status(task_id, TaskStatusUpdate(status=status, reason=reason))


def consolidate_parent(session: Session, parent_id: uuid.UUID) -> dict[str, Any] | None:
    """Junta o resultado dos filhos no pai. O pai só conclui se todo filho não cancelado concluiu com
    evidência (filho substituído por replanejamento não conta). Filho concluído sem evidência é reaberto e o pai volta a PLANNING. Filho que falhou deixa o
    pai como está, com `achieved=False` e a lista `pending`: replanejar ou parar é decisão do runner."""
    ts = TaskService(session)
    parent = ts.get_task(parent_id)
    kids = children_of(session, parent_id)
    if not kids:
        return None
    if any(TaskStatus(c.status) not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED} for c in kids):
        return None

    summaries = []
    gaps: list[TaskModel] = []
    failed: list[TaskModel] = []
    for c in kids:
        ev_ok = verification_evidence_ok(session, c)
        if c.status == TaskStatus.COMPLETED.value and not ev_ok:
            gaps.append(c)
        elif c.status == TaskStatus.FAILED.value and not superseded(c):
            failed.append(c)
        summaries.append(
            {
                "task_id": str(c.id),
                "title": c.title,
                "evidence_ok": ev_ok,
                "result": c.consolidated_result_json or {"status": c.status},
            }
        )
    report: dict[str, Any] = {
        "achieved": not gaps and not failed,
        "children": summaries,
        "evidences": collect_evidences(session, parent_id),
        "pending": [
            {"task_id": str(c.id), "title": c.title, "status": c.status, "reason": pending_reason(c)}
            for c in [*gaps, *failed]
        ],
    }
    for child in kids:
        meta = child.metadata_json or {}
        result = child.consolidated_result_json or {}
        if meta.get("final_answer") and result.get("markdown"):
            report["final_answer"] = result["markdown"]
            report["sources"] = result.get("sources") or []
    parent.consolidated_result_json = report
    current = TaskStatus(parent.status)
    if current not in _TO_VERIFYING:
        return report
    if report["achieved"]:
        _walk(ts, parent_id, [*_TO_VERIFYING[current], TaskStatus.COMPLETED])
        return report
    if gaps:
        for c in gaps:
            _walk(ts, c.id, [TaskStatus.VERIFYING, TaskStatus.RETRY_PENDING], "evidência insuficiente")
        if current != TaskStatus.PLANNING:
            _walk(ts, parent_id, [*_TO_VERIFYING[current], TaskStatus.PLANNING], "filhos sem evidência")
    return report


def pending_reason(task: TaskModel) -> str:
    """Por que a tarefa não concluiu: última falha categorizada, motivo do bloqueio ou o status."""
    meta = task.metadata_json or {}
    failure = meta.get("last_failure") or {}
    return str(failure.get("detail") or meta.get("blocked_reason") or task.status)[:300]


def collect_evidences(session: Session, task_id: uuid.UUID) -> list[dict[str, Any]]:
    stmt = (
        select(EvidenceModel)
        .where(EvidenceModel.task_id == task_id)
        .order_by(EvidenceModel.created_at, EvidenceModel.id)
    )
    rows = list(session.scalars(stmt).all())
    return [
        {
            "verifier": r.verifier,
            "passed": r.passed,
            "summary": r.summary,
            "detail": r.detail_json,
        }
        for r in rows
    ]
