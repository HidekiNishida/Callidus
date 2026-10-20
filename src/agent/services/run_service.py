# src/agent/services/run_service.py — execuções e tentativas
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, TaskStatusUpdate
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel
from agent.services.agent_service import AgentService


class RunService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(self, project_id: uuid.UUID, data: ExecutionRunCreate) -> ExecutionRunModel:
        task = self._session.get(TaskModel, data.root_task_id)
        if task is None or task.project_id != project_id:
            raise LookupError("Tarefa raiz inválida")

        config = dict(data.config or {})
        meta = dict(task.metadata_json or {})
        if config.get("model_id"):
            meta["model_id"] = config["model_id"]
            if config.get("provider"):
                meta["provider"] = config["provider"]
            task.metadata_json = meta
        run = ExecutionRunModel(
            project_id=project_id,
            root_task_id=data.root_task_id,
            status=RunStatus.ACTIVE.value,
            config_json=data.config,
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
        # O run começa com um agente lógico na raiz: é quem delega e quem recebe as
        # respostas dos filhos.
        AgentService(self._session).ensure_agent(task.id)
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

    def resume_run(self, run_id: uuid.UUID, *, retry_blocked: bool = False) -> ExecutionRunModel:
        """Retoma um run pausado sem refazer o que foi comprovado: volta a ACTIVE, o motivo da pausa vai para
        o histórico `pauses` da raiz e os limites recomeçam a contar do evento `run.resumed`. Com
        `retry_blocked`, etapas bloqueadas voltam a PLANNING (depois de corrigida a causa de fora)."""
        from agent.services.task_service import TaskService

        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        if run.status != RunStatus.PAUSED.value:
            raise ValueError(f"run não está pausado ({run.status})")
        root = self._session.get(TaskModel, run.root_task_id)
        retried: list[str] = []
        pause = None
        if root is not None:
            meta = dict(root.metadata_json or {})
            pause = meta.pop("pause", None)
            if pause:
                meta["pauses"] = [*(meta.get("pauses") or []), pause][-10:]
            root.metadata_json = meta
            report = dict(root.consolidated_result_json or {})
            if report.pop("paused", None) is not None:
                report.pop("final_answer", None)
                report.pop("achieved", None)
                root.consolidated_result_json = report or None
            if retry_blocked:
                tasks = TaskService(self._session)
                for task in self._session.scalars(select(TaskModel).where(TaskModel.project_id == run.project_id)).all():
                    if task.status == TaskStatus.BLOCKED.value and self._under(task, root.id):
                        tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.PLANNING, reason="retomada"))
                        retried.append(str(task.id))
        run.status = RunStatus.ACTIVE.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=run.root_task_id,
                event_type="run.resumed",
                payload_json={"pause": pause, "retried": retried},
            )
        )
        self._session.flush()
        return run

    def _under(self, task: TaskModel, root_id: uuid.UUID) -> bool:
        seen: set[uuid.UUID] = set()
        current: TaskModel | None = task
        while current is not None and current.id not in seen:
            if current.id == root_id:
                return True
            seen.add(current.id)
            current = self._session.get(TaskModel, current.parent_id) if current.parent_id else None
        return False

    def cancel_run(self, run_id: uuid.UUID) -> ExecutionRunModel:
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        run.status = RunStatus.CANCELLED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                event_type="run.cancelled",
                payload_json={},
            )
        )
        return run
