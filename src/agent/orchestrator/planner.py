# src/agent/orchestrator/planner.py — planner persistente (objetivo + memória canônica)
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate
from agent.services.project_service import ProjectService
from agent.persistence.models import TaskModel


def ensure_canonical_memory_for_objective(
    session: Session,
    project_id: uuid.UUID,
    root_task: TaskModel,
) -> None:
    ps = ProjectService(session)
    existing = ps.list_memory(project_id, MemoryKind.CANONICAL)
    if not any(m.title == "Objetivo global" and m.conversation_id is None for m in existing):
        ps.add_memory(
            project_id,
            MemoryCreate(
                kind=MemoryKind.CANONICAL,
                title="Objetivo global",
                content=root_task.objective,
                task_id=root_task.id,
                source_refs=[f"task:{root_task.id}"],
            ),
        )
    if root_task.conversation_id is None:
        return
    if any(m.conversation_id == root_task.conversation_id and m.task_id == root_task.id for m in existing):
        return
    ps.add_memory(
        project_id,
        MemoryCreate(
            kind=MemoryKind.CANONICAL,
            title=root_task.title[:180] or "Conversa",
            content=root_task.objective,
            task_id=root_task.id,
            conversation_id=root_task.conversation_id,
            source_refs=[f"task:{root_task.id}"],
        ),
    )
