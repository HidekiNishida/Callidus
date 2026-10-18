# src/agent/orchestrator/progress.py — progresso verificável: estado persistido, não número de chamadas
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.orchestrator.consolidation import settled, superseded, verification_evidence_ok
from agent.persistence.models import TaskModel


def subtree(session: Session, root_id: uuid.UUID) -> list[TaskModel]:
    root = session.get(TaskModel, root_id)
    if root is None:
        return []
    tasks = list(session.scalars(select(TaskModel).where(TaskModel.project_id == root.project_id)).all())
    ids = {root_id}
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True
    return [t for t in tasks if t.id in ids]


def progress_state(session: Session, root_id: uuid.UUID) -> dict[str, int]:
    """`verified`: concluídas com evidência válida e atual (ou sem verificação exigida); `pending`: não
    assentadas; `failed`/`blocked`: paradas ainda não substituídas por replanejamento."""
    state = {"verified": 0, "pending": 0, "failed": 0, "blocked": 0}
    for t in subtree(session, root_id):
        status = TaskStatus(t.status)
        if status == TaskStatus.COMPLETED and verification_evidence_ok(session, t):
            state["verified"] += 1
        if not settled(t):
            state["pending"] += 1
        if status in {TaskStatus.FAILED, TaskStatus.BLOCKED} and not superseded(t):
            state["failed" if status == TaskStatus.FAILED else "blocked"] += 1
    return state


def made_progress(before: dict[str, int] | None, after: dict[str, int]) -> bool:
    """Progresso = mais etapas verificadas, ou menos pendências sem perder etapas verificadas.
    Decompor (mais pendências) ou chamar o modelo de novo não conta."""
    if before is None:
        return after.get("verified", 0) > 0
    if after.get("verified", 0) > before.get("verified", 0):
        return True
    return after.get("verified", 0) >= before.get("verified", 0) and after.get("pending", 0) < before.get("pending", 0)
