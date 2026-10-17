# src/agent/orchestrator/engine.py — esqueleto do ciclo (Fase 4+)
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.services.task_service import TaskService


class OrchestratorEngine:
    """Coordenação explícita; expandir com decomposição, ferramentas e verificação."""

    def __init__(self, session: Session) -> None:
        self._tasks = TaskService(session)

    def tick(self, task_id: uuid.UUID) -> dict:
        """
        Um passo do ciclo: hoje apenas promove PLANNING→READY quando dependências ok.
        """
        task = self._tasks.get_task(task_id)
        promoted = self._tasks.promote_ready_if_dependencies_met(task_id)
        if promoted is not None:
            return {"action": "promoted_ready", "task_id": str(task_id)}

        status = TaskStatus(task.status)
        if status == TaskStatus.READY:
            self._tasks.update_status(task_id, TaskStatusUpdate(status=TaskStatus.RUNNING))
            return {"action": "started_running", "task_id": str(task_id)}

        return {"action": "noop", "task_id": str(task_id), "status": task.status}
