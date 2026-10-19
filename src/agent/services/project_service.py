# src/agent/services/project_service.py — projetos e memória canônica inicial
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate, ProjectCreate
from agent.memory.store import structure_memory
from agent.persistence.models import (
    ContextSnapshotModel,
    ConversationModel,
    EventLogModel,
    ExecutionRunModel,
    KgEdgeModel,
    KgNodeModel,
    MemoryRecordModel,
    OperationAttemptModel,
    ProjectModel,
    ScheduledRunModel,
    TaskContractModel,
    TaskDependencyModel,
    TaskModel,
)
from agent.services.inbox import is_inbox_path, is_inbox_project, user_home


def _is_leaked_test_project(root_path: str) -> bool:
    path = root_path.replace("\\", "/")
    return "pytest-of-" in path or "/T/pytest-" in path or is_inbox_path(path)


class ProjectService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_project(self, data: ProjectCreate, *, origin: str | None = None) -> ProjectModel:
        raw = (data.root_path or "").strip()
        if origin == "inbox":
            root = user_home()
            path_origin = "inbox"
        elif not raw:
            root = user_home()
            path_origin = "home"
        else:
            root = str(Path(raw).expanduser().resolve())
            path_origin = origin or "chosen"
        project = ProjectModel(
            name=data.name,
            root_path=root,
            description=data.description,
            path_origin=path_origin,
        )
        self._session.add(project)
        self._session.flush()
        self._session.add(
            EventLogModel(
                project_id=project.id,
                event_type="project.created",
                payload_json={"name": project.name, "root_path": project.root_path},
            )
        )
        return project

    def update_project(self, project_id: uuid.UUID, *, name: str | None = None, root_path: str | None = None) -> ProjectModel:
        project = self.get_project(project_id)
        if is_inbox_project(project):
            raise ValueError("a pasta das conversas soltas não se altera por aqui")
        if name is not None and name.strip():
            project.name = name.strip()[:200]
        if root_path is not None:
            raw = root_path.strip()
            if not raw:
                project.root_path = user_home()
                project.path_origin = "home"
            else:
                path = Path(raw).expanduser().resolve()
                if not path.is_dir():
                    raise ValueError("a pasta não existe")
                project.root_path = str(path)
                project.path_origin = "chosen"
        self._session.flush()
        return project

    def list_projects(self) -> list[ProjectModel]:
        rows = list(self._session.scalars(select(ProjectModel).order_by(ProjectModel.created_at)).all())
        return [p for p in rows if not _is_leaked_test_project(p.root_path) and not is_inbox_project(p)]

    def delete_project(self, project_id: uuid.UUID) -> dict:
        """Remove o projeto e tudo que pertence a ele: conversas, tarefas, execuções, eventos,
        memória e o grafo de conhecimento. Os arquivos da pasta do projeto **não** são apagados —
        a interface deixa isso explícito."""
        project = self.get_project(project_id)
        if is_inbox_project(project):
            raise ValueError("a pasta das conversas soltas não se remove por aqui")

        from agent.services.conversation_service import ConversationService

        conversation_service = ConversationService(self._session)
        conversations = list(
            self._session.scalars(
                select(ConversationModel).where(ConversationModel.project_id == project.id)
            ).all()
        )
        removed_conversations = 0
        for conversation in conversations:
            conversation_service.delete_conversation(conversation.id)
            removed_conversations += 1

        task_ids = list(
            self._session.scalars(select(TaskModel.id).where(TaskModel.project_id == project.id)).all()
        )
        run_ids = list(
            self._session.scalars(
                select(ExecutionRunModel.id).where(ExecutionRunModel.project_id == project.id)
            ).all()
        )
        for model, column, values in (
            (EventLogModel, EventLogModel.run_id, run_ids),
            (OperationAttemptModel, OperationAttemptModel.run_id, run_ids),
            (ContextSnapshotModel, ContextSnapshotModel.run_id, run_ids),
            (EventLogModel, EventLogModel.task_id, task_ids),
            (ContextSnapshotModel, ContextSnapshotModel.task_id, task_ids),
            (TaskContractModel, TaskContractModel.task_id, task_ids),
            (TaskDependencyModel, TaskDependencyModel.task_id, task_ids),
            (TaskDependencyModel, TaskDependencyModel.depends_on_task_id, task_ids),
        ):
            if values:
                self._session.execute(delete(model).where(column.in_(values)))
        self._session.execute(
            delete(ExecutionRunModel).where(ExecutionRunModel.project_id == project.id)
        )
        self._session.execute(delete(ScheduledRunModel).where(ScheduledRunModel.project_id == project.id))
        self._session.execute(delete(TaskModel).where(TaskModel.project_id == project.id))
        self._session.execute(delete(MemoryRecordModel).where(MemoryRecordModel.project_id == project.id))
        self._session.execute(delete(KgEdgeModel).where(KgEdgeModel.project_id == project.id))
        self._session.execute(delete(KgNodeModel).where(KgNodeModel.project_id == project.id))
        self._session.execute(
            delete(EventLogModel).where(EventLogModel.project_id == project.id)
        )
        self._session.delete(project)
        self._session.flush()
        return {
            "deleted": True,
            "project_id": str(project.id),
            "name": project.name,
            "conversations": removed_conversations,
            "root_path": project.root_path,
        }

    def get_project(self, project_id: uuid.UUID) -> ProjectModel:
        project = self._session.get(ProjectModel, project_id)
        if project is None:
            raise LookupError(f"Projeto não encontrado: {project_id}")
        return project

    def add_memory(self, project_id: uuid.UUID, data: MemoryCreate) -> MemoryRecordModel:
        self.get_project(project_id)
        if data.conversation_id is not None:
            conversation = self._session.get(ConversationModel, data.conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise LookupError("Conversa inválida para este projeto")
        outline = structure_memory(data.content)
        branch_id = data.branch_id
        if branch_id is None and data.conversation_id is not None:
            conversation = self._session.get(ConversationModel, data.conversation_id)
            if conversation is not None:
                branch_id = conversation.active_branch_id
        record = MemoryRecordModel(
            project_id=project_id,
            conversation_id=data.conversation_id,
            branch_id=branch_id,
            task_id=data.task_id,
            kind=data.kind.value,
            title=data.title,
            content=data.content,
            summary=outline["summary"],
            outline_json=outline,
            source_refs_json=data.source_refs,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_memory(self, project_id: uuid.UUID, kind: MemoryKind | None = None) -> list[MemoryRecordModel]:
        self.get_project(project_id)
        stmt = select(MemoryRecordModel).where(MemoryRecordModel.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(MemoryRecordModel.kind == kind.value)
        stmt = stmt.order_by(MemoryRecordModel.created_at.desc())
        return list(self._session.scalars(stmt).all())
