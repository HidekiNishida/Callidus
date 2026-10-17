# src/agent/services/project_service.py — projetos e memória canônica inicial
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate, ProjectCreate
from agent.memory.store import structure_memory
from agent.persistence.models import ConversationModel, EventLogModel, MemoryRecordModel, ProjectModel
from agent.services.inbox import is_inbox_path


def _is_leaked_test_project(root_path: str) -> bool:
    path = root_path.replace("\\", "/")
    return "pytest-of-" in path or "/T/pytest-" in path or is_inbox_path(path)


class ProjectService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_project(self, data: ProjectCreate) -> ProjectModel:
        project = ProjectModel(
            name=data.name,
            root_path=data.root_path,
            description=data.description,
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

    def list_projects(self) -> list[ProjectModel]:
        rows = list(self._session.scalars(select(ProjectModel).order_by(ProjectModel.created_at)).all())
        return [p for p in rows if not _is_leaked_test_project(p.root_path)]

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
        record = MemoryRecordModel(
            project_id=project_id,
            conversation_id=data.conversation_id,
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
