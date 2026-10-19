# src/agent/services/project_service.py — projetos e memória canônica inicial
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate, ProjectCreate
from agent.memory.store import structure_memory
from agent.persistence.models import (
    ConversationModel,
    EventLogModel,
    MemoryRecordModel,
    ProjectModel,
    ProjectRemoteModel,
)
from agent.services.cascade import delete_cascade
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

    def get_remote(self, project_id: uuid.UUID) -> dict | None:
        """Configuração do computador remoto do projeto (None quando o projeto é local)."""
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            return None
        return dict(row.config_json or {})

    def set_remote(self, project_id: uuid.UUID, config: dict) -> dict:
        self.get_project(project_id)
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            row = ProjectRemoteModel(project_id=project_id, config_json=dict(config))
            self._session.add(row)
        else:
            row.config_json = dict(config)
        self._session.flush()
        return dict(config)

    def clear_remote(self, project_id: uuid.UUID) -> bool:
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def list_projects(self) -> list[ProjectModel]:
        rows = list(self._session.scalars(select(ProjectModel).order_by(ProjectModel.created_at)).all())
        return [p for p in rows if not _is_leaked_test_project(p.root_path) and not is_inbox_project(p)]

    def delete_project(self, project_id: uuid.UUID) -> dict:
        """Remove o projeto e tudo que pertence a ele: conversas, tarefas, execuções, eventos,
        memória e o grafo de conhecimento. A remoção em cascata segue o grafo de chaves
        estrangeiras, então nada fica pendurado. Os arquivos da pasta do projeto **não** são
        apagados — a interface deixa isso explícito."""
        project = self.get_project(project_id)
        if is_inbox_project(project):
            raise ValueError("a pasta das conversas soltas não se remove por aqui")

        conversations = list(
            self._session.scalars(
                select(ConversationModel).where(ConversationModel.project_id == project.id)
            ).all()
        )
        # Valores lidos antes da remoção: depois do cascade o objeto sai da sessão.
        project_id = str(project.id)
        name = project.name
        root_path = project.root_path
        removed = delete_cascade(self._session, "projects", project.id)
        self._session.flush()
        return {
            "deleted": True,
            "project_id": project_id,
            "name": name,
            "conversations": len(conversations),
            "root_path": root_path,
            "rows": removed,
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
