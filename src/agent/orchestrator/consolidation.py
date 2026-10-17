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


def verification_evidence_ok(session: Session, task: TaskModel) -> bool:
    meta = task.metadata_json or {}
    if not meta.get("verification"):
        return True
    evs = collect_evidences(session, task.id)
    return any(e.get("passed") is True for e in evs)


def children_of(session: Session, parent_id: uuid.UUID) -> list[TaskModel]:
    stmt = select(TaskModel).where(TaskModel.parent_id == parent_id)
    return list(session.scalars(stmt).all())


def consolidate_parent(session: Session, parent_id: uuid.UUID) -> dict[str, Any] | None:
    ts = TaskService(session)
    parent = ts.get_task(parent_id)
    kids = children_of(session, parent_id)
    if not kids:
        return None
    if any(TaskStatus(c.status) not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} for c in kids):
        return None

    summaries = []
    child_ok = True
    for c in kids:
        ev_ok = verification_evidence_ok(session, c)
        ok = c.status == TaskStatus.COMPLETED.value and ev_ok
        if not ok:
            child_ok = False
        summaries.append(
            {
                "task_id": str(c.id),
                "title": c.title,
                "evidence_ok": ev_ok,
                "result": c.consolidated_result_json or {"status": c.status},
            }
        )
    report: dict[str, Any] = {
        "achieved": child_ok,
        "children": summaries,
        "evidences": collect_evidences(session, parent_id),
    }
    for child in kids:
        meta = child.metadata_json or {}
        result = child.consolidated_result_json or {}
        if meta.get("final_answer") and result.get("markdown"):
            report["final_answer"] = result["markdown"]
            report["sources"] = result.get("sources") or []
    parent.consolidated_result_json = report
    current = TaskStatus(parent.status)
    if current == TaskStatus.PLANNING and report["achieved"]:
        ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        current = TaskStatus.VERIFYING
    if current == TaskStatus.VERIFYING:
        if report["achieved"]:
            ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
        else:
            for c in kids:
                if c.status == TaskStatus.COMPLETED.value and not verification_evidence_ok(session, c):
                    ts.update_status(c.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                    ts.update_status(
                        c.id,
                        TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason="evidência insuficiente"),
                    )
                elif c.status not in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value}:
                    ts.update_status(
                        c.id,
                        TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason="reabertura hierárquica"),
                    )
            ts.update_status(
                parent_id,
                TaskStatusUpdate(status=TaskStatus.PLANNING, reason="filhos incompletos ou sem evidência"),
            )
    return report


def collect_evidences(session: Session, task_id: uuid.UUID) -> list[dict[str, Any]]:
    stmt = select(EvidenceModel).where(EvidenceModel.task_id == task_id)
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
