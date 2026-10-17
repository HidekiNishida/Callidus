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
    for c in kids:
        summaries.append(
            {
                "task_id": str(c.id),
                "title": c.title,
                "result": c.consolidated_result_json or {"status": c.status},
            }
        )
    report: dict[str, Any] = {
        "achieved": all(c.status == TaskStatus.COMPLETED.value for c in kids),
        "children": summaries,
    }
    parent.consolidated_result_json = report
    current = TaskStatus(parent.status)
    if current == TaskStatus.PLANNING and report["achieved"]:
        ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        current = TaskStatus.VERIFYING
    if current == TaskStatus.VERIFYING:
        if report["achieved"]:
            ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
        else:
            ts.update_status(
                parent_id,
                TaskStatusUpdate(status=TaskStatus.FAILED, reason="filhos incompletos"),
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
