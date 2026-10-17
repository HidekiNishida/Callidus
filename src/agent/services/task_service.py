# src/agent/services/task_service.py — CRUD de tarefas, dependências e transições
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.domain.state_machine import InvalidTransitionError, transition
from agent.persistence.models import (
    ConversationModel,
    EventLogModel,
    ProjectModel,
    TaskDependencyModel,
    TaskModel,
)


class TaskNotFoundError(LookupError):
    pass


class DependencyError(ValueError):
    pass


class TaskService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_task(self, project_id: uuid.UUID, data: TaskCreate) -> TaskModel:
        project = self._session.get(ProjectModel, project_id)
        if project is None:
            raise LookupError(f"Projeto não encontrado: {project_id}")

        conversation_id = data.conversation_id
        if data.parent_id is not None:
            parent = self._session.get(TaskModel, data.parent_id)
            if parent is None or parent.project_id != project_id:
                raise TaskNotFoundError("Tarefa pai inválida para este projeto")
            conversation_id = parent.conversation_id or conversation_id
        if conversation_id is not None:
            conversation = self._session.get(ConversationModel, conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise TaskNotFoundError("Conversa inválida para este projeto")

        task = TaskModel(
            project_id=project_id,
            conversation_id=conversation_id,
            parent_id=data.parent_id,
            title=data.title,
            objective=data.objective,
            scope=data.scope,
            acceptance_criteria=data.acceptance_criteria,
            kind=data.kind.value,
            metadata_json=data.metadata,
        )
        self._session.add(task)
        self._session.flush()
        self._log_event(
            project_id=project_id,
            task_id=task.id,
            event_type="task.created",
            payload={"title": task.title, "kind": task.kind},
        )
        return task

    def list_tasks(self, project_id: uuid.UUID) -> list[TaskModel]:
        stmt = select(TaskModel).where(TaskModel.project_id == project_id).order_by(TaskModel.sort_order)
        return list(self._session.scalars(stmt).all())

    def get_task(self, task_id: uuid.UUID) -> TaskModel:
        task = self._session.get(TaskModel, task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    def update_status(self, task_id: uuid.UUID, update: TaskStatusUpdate) -> TaskModel:
        task = self.get_task(task_id)
        current = TaskStatus(task.status)
        target = update.status
        try:
            transition(current, target)
        except InvalidTransitionError:
            raise

        task.status = target.value
        now = datetime.now(timezone.utc)
        if target == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            task.completed_at = now

        self._log_event(
            project_id=task.project_id,
            task_id=task.id,
            event_type="task.status_changed",
            payload={
                "from": current.value,
                "to": target.value,
                "reason": update.reason,
            },
        )
        return task

    def add_dependency(self, task_id: uuid.UUID, data: TaskDependencyCreate) -> TaskDependencyModel:
        task = self.get_task(task_id)
        dep = self.get_task(data.depends_on_task_id)
        if task.project_id != dep.project_id:
            raise DependencyError("Dependências devem estar no mesmo projeto")
        if task_id == data.depends_on_task_id:
            raise DependencyError("Tarefa não pode depender de si mesma")
        if self._creates_cycle(task_id, data.depends_on_task_id):
            raise DependencyError("Dependência circular detectada")

        row = TaskDependencyModel(task_id=task_id, depends_on_task_id=data.depends_on_task_id)
        self._session.add(row)
        self._session.flush()
        self._log_event(
            project_id=task.project_id,
            task_id=task_id,
            event_type="task.dependency_added",
            payload={"depends_on": str(data.depends_on_task_id)},
        )
        return row

    def dependencies_satisfied(self, task_id: uuid.UUID) -> bool:
        stmt = select(TaskDependencyModel).where(TaskDependencyModel.task_id == task_id)
        deps = list(self._session.scalars(stmt).all())
        for d in deps:
            other = self.get_task(d.depends_on_task_id)
            if other.status != TaskStatus.COMPLETED.value:
                return False
        return True

    def promote_ready_if_dependencies_met(self, task_id: uuid.UUID) -> TaskModel | None:
        task = self.get_task(task_id)
        if task.status != TaskStatus.PENDING.value and task.status != TaskStatus.PLANNING.value:
            return None
        if not self.dependencies_satisfied(task_id):
            return None
        if task.status == TaskStatus.PLANNING.value:
            return self.update_status(task_id, TaskStatusUpdate(status=TaskStatus.READY))
        return None

    def _creates_cycle(self, task_id: uuid.UUID, new_dep: uuid.UUID) -> bool:
        """DFS: existe caminho de new_dep até task_id nas dependências existentes?"""
        edges: dict[uuid.UUID, list[uuid.UUID]] = {}
        stmt = select(TaskDependencyModel)
        for row in self._session.scalars(stmt).all():
            edges.setdefault(row.task_id, []).append(row.depends_on_task_id)
        edges.setdefault(task_id, []).append(new_dep)

        stack = [new_dep]
        seen: set[uuid.UUID] = set()
        while stack:
            node = stack.pop()
            if node == task_id:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(edges.get(node, []))
        return False

    def _log_event(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID | None,
        event_type: str,
        payload: dict | None,
        run_id: uuid.UUID | None = None,
    ) -> None:
        self._session.add(
            EventLogModel(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                event_type=event_type,
                payload_json=payload,
            )
        )
