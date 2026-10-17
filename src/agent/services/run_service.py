# src/agent/services/run_service.py — execuções e tentativas
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import RunStatus
from agent.domain.schemas import ExecutionRunCreate
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel


class RunService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(self, project_id: uuid.UUID, data: ExecutionRunCreate) -> ExecutionRunModel:
        task = self._session.get(TaskModel, data.root_task_id)
        if task is None or task.project_id != project_id:
            raise LookupError("Tarefa raiz inválida")

        run = ExecutionRunModel(
            project_id=project_id,
            root_task_id=data.root_task_id,
            status=RunStatus.ACTIVE.value,
        )
        self._session.add(run)
        self._session.flush()
        self._session.add(
            EventLogModel(
                project_id=project_id,
                run_id=run.id,
                task_id=task.id,
                event_type="run.started",
                payload_json={"root_task_id": str(task.id)},
            )
        )
        return run

    def list_runs(self, project_id: uuid.UUID) -> list[ExecutionRunModel]:
        stmt = (
            select(ExecutionRunModel)
            .where(ExecutionRunModel.project_id == project_id)
            .order_by(ExecutionRunModel.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def pause_run(self, run_id: uuid.UUID) -> ExecutionRunModel:
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        run.status = RunStatus.PAUSED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                event_type="run.paused",
                payload_json={},
            )
        )
        return run
