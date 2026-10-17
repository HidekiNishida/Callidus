# src/agent/services/branches.py — ramos da conversa e o que cada um pode ver
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agent.persistence.models import BranchModel, TaskModel


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def ancestor_chain(branches: dict[uuid.UUID, BranchModel], branch_id: uuid.UUID | None) -> list[BranchModel]:
    chain: list[BranchModel] = []
    current = branches.get(branch_id) if branch_id else None
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        current = branches.get(current.parent_id) if current.parent_id else None
    return chain


def memory_visible(
    *,
    memory_branch_id: uuid.UUID | None,
    memory_created_at: datetime | None,
    conversation_id: uuid.UUID | None,
    task_branch_id: uuid.UUID | None,
    branches: dict[uuid.UUID, BranchModel],
) -> bool:
    """Memória do projeto vale para todos. A da conversa segue o ramo e os anteriores."""
    if conversation_id is None or memory_branch_id is None or task_branch_id is None:
        return True
    chain = ancestor_chain(branches, task_branch_id)
    if not any(item.id == memory_branch_id for item in chain):
        return False
    if memory_branch_id == task_branch_id:
        return True
    child = next((item for item in chain if item.parent_id == memory_branch_id), None)
    if child is None:
        return False
    created = _aware(memory_created_at)
    cutoff = _aware(child.created_at)
    if created is None or cutoff is None:
        return True
    return created <= cutoff


def visible_tasks(
    tasks: list[TaskModel],
    branch: BranchModel,
    branches: dict[uuid.UUID, BranchModel],
) -> list[TaskModel]:
    chain = ancestor_chain(branches, branch.id)
    chain_ids = {item.id for item in chain}
    child_by_parent = {item.parent_id: item for item in chain if item.parent_id}
    by_id = {task.id: task for task in tasks}
    visible_roots: set[uuid.UUID] = set()
    for task in tasks:
        if task.parent_id is not None:
            continue
        if task.branch_id is None:
            if branch.parent_id is None:
                visible_roots.add(task.id)
            continue
        if task.branch_id not in chain_ids:
            continue
        if task.branch_id == branch.id:
            visible_roots.add(task.id)
            continue
        child = child_by_parent.get(task.branch_id)
        if child is None:
            continue
        fork_id = child.fork_task_id
        if task.id == fork_id:
            continue
        cutoff = child.created_at
        fork = by_id.get(fork_id) if fork_id else None
        if fork is not None:
            cutoff = fork.created_at
        created = _aware(task.created_at)
        limit = _aware(cutoff)
        if created is not None and limit is not None and created < limit:
            visible_roots.add(task.id)

    def root_id(task: TaskModel) -> uuid.UUID:
        seen: set[uuid.UUID] = set()
        current = task
        while current.parent_id and current.parent_id in by_id and current.id not in seen:
            seen.add(current.id)
            current = by_id[current.parent_id]
        return current.id

    return [task for task in tasks if root_id(task) in visible_roots]
