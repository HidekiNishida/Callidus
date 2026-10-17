# src/agent/services/conversation_service.py — conversas dentro e fora de projetos
from __future__ import annotations

import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from agent.domain.schemas import ConversationCreate, ProjectCreate
from agent.i18n.locale import detect_language
from agent.persistence.models import (
    ContextSnapshotModel,
    ConversationModel,
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    MemoryRecordModel,
    OperationAttemptModel,
    ProjectModel,
    TaskContractModel,
    TaskDependencyModel,
    TaskModel,
    utcnow,
)
from agent.services.inbox import INBOX_ROOT, is_inbox_path
from agent.services.project_service import ProjectService

_GENERIC_TITLES = {"Nova conversa", "New chat", "Nueva conversación"}


class ConversationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_conversations(self, project_id: uuid.UUID) -> list[ConversationModel]:
        self._backfill(project_id)
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.project_id == project_id)
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def list_loose(self) -> list[ConversationModel]:
        inbox = self._find_inbox()
        if inbox is None:
            return []
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.project_id == inbox.id)
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def create_loose(self, data: ConversationCreate) -> ConversationModel:
        return self.create_conversation(self._ensure_inbox().id, data)

    def move_conversation(
        self, conversation_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> ConversationModel:
        conversation = self.get_conversation(conversation_id)
        if project_id is None:
            target = self._ensure_inbox()
        else:
            target = ProjectService(self._session).get_project(project_id)
            if is_inbox_path(target.root_path):
                target = self._ensure_inbox()
        if conversation.project_id == target.id:
            return conversation
        tasks = list(
            self._session.scalars(
                select(TaskModel).where(TaskModel.conversation_id == conversation.id)
            ).all()
        )
        task_ids = [task.id for task in tasks]
        for task in tasks:
            task.project_id = target.id
        if task_ids:
            runs = list(
                self._session.scalars(
                    select(ExecutionRunModel).where(ExecutionRunModel.root_task_id.in_(task_ids))
                ).all()
            )
            for run in runs:
                run.project_id = target.id
        memories = list(
            self._session.scalars(
                select(MemoryRecordModel).where(MemoryRecordModel.conversation_id == conversation.id)
            ).all()
        )
        for memory in memories:
            memory.project_id = target.id
        conversation.project_id = target.id
        conversation.updated_at = utcnow()
        self._session.flush()
        return conversation

    def delete_conversation(self, conversation_id: uuid.UUID) -> None:
        conversation = self.get_conversation(conversation_id)
        tasks = list(
            self._session.scalars(
                select(TaskModel).where(TaskModel.conversation_id == conversation.id)
            ).all()
        )
        task_ids = [task.id for task in tasks]
        if task_ids:
            run_ids = list(
                self._session.scalars(
                    select(ExecutionRunModel.id).where(ExecutionRunModel.root_task_id.in_(task_ids))
                ).all()
            )
            self._session.execute(delete(EvidenceModel).where(EvidenceModel.task_id.in_(task_ids)))
            self._session.execute(
                delete(OperationAttemptModel).where(OperationAttemptModel.task_id.in_(task_ids))
            )
            if run_ids:
                self._session.execute(
                    delete(OperationAttemptModel).where(OperationAttemptModel.run_id.in_(run_ids))
                )
                self._session.execute(delete(EventLogModel).where(EventLogModel.run_id.in_(run_ids)))
                self._session.execute(
                    delete(ContextSnapshotModel).where(ContextSnapshotModel.run_id.in_(run_ids))
                )
                self._session.execute(delete(ExecutionRunModel).where(ExecutionRunModel.id.in_(run_ids)))
            self._session.execute(delete(EventLogModel).where(EventLogModel.task_id.in_(task_ids)))
            self._session.execute(
                delete(ContextSnapshotModel).where(ContextSnapshotModel.task_id.in_(task_ids))
            )
            self._session.execute(delete(TaskContractModel).where(TaskContractModel.task_id.in_(task_ids)))
            self._session.execute(
                delete(TaskDependencyModel).where(
                    or_(
                        TaskDependencyModel.task_id.in_(task_ids),
                        TaskDependencyModel.depends_on_task_id.in_(task_ids),
                    )
                )
            )
            self._session.execute(
                delete(MemoryRecordModel).where(
                    or_(
                        MemoryRecordModel.conversation_id == conversation.id,
                        MemoryRecordModel.task_id.in_(task_ids),
                    )
                )
            )
            remaining = set(task_ids)
            parent_by_id = {task.id: task.parent_id for task in tasks}
            while remaining:
                leaves = {item for item in remaining if parent_by_id.get(item) not in remaining}
                if not leaves:
                    leaves = set(remaining)
                self._session.execute(delete(TaskModel).where(TaskModel.id.in_(leaves)))
                remaining -= leaves
        else:
            self._session.execute(
                delete(MemoryRecordModel).where(MemoryRecordModel.conversation_id == conversation.id)
            )
        self._session.delete(conversation)
        self._session.flush()

    def create_conversation(self, project_id: uuid.UUID, data: ConversationCreate) -> ConversationModel:
        title = (data.title or "Nova conversa").strip()[:200] or "Nova conversa"
        locale = data.locale if data.locale in {"pt", "en", "es"} else "pt"
        conversation = ConversationModel(project_id=project_id, title=title, locale=locale)
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def get_conversation(self, conversation_id: uuid.UUID) -> ConversationModel:
        conversation = self._session.get(ConversationModel, conversation_id)
        if conversation is None:
            raise LookupError(f"Conversa não encontrada: {conversation_id}")
        return conversation

    def touch_title(self, conversation_id: uuid.UUID, title: str, locale: str) -> None:
        conversation = self.get_conversation(conversation_id)
        if conversation.title in _GENERIC_TITLES:
            conversation.title = title.strip()[:200] or conversation.title
        if locale in {"pt", "en", "es"}:
            conversation.locale = locale
        self._session.flush()

    def _find_inbox(self) -> ProjectModel | None:
        return self._session.scalar(select(ProjectModel).where(ProjectModel.root_path == INBOX_ROOT))

    def _ensure_inbox(self) -> ProjectModel:
        found = self._find_inbox()
        if found is not None:
            return found
        return ProjectService(self._session).create_project(
            ProjectCreate(name="Conversas soltas", root_path=INBOX_ROOT, description="inbox")
        )

    def _backfill(self, project_id: uuid.UUID) -> None:
        roots = list(
            self._session.scalars(
                select(TaskModel).where(
                    TaskModel.project_id == project_id,
                    TaskModel.parent_id.is_(None),
                    TaskModel.conversation_id.is_(None),
                )
            ).all()
        )
        for root in roots:
            locale = (root.metadata_json or {}).get("locale") or detect_language(root.objective or root.title)
            conversation = ConversationModel(
                project_id=project_id,
                title=(root.title or "Conversa")[:200],
                locale=locale if locale in {"pt", "en", "es"} else "pt",
            )
            self._session.add(conversation)
            self._session.flush()
            self._assign(root, conversation.id)

    def _assign(self, task: TaskModel, conversation_id: uuid.UUID) -> None:
        task.conversation_id = conversation_id
        children = list(
            self._session.scalars(select(TaskModel).where(TaskModel.parent_id == task.id)).all()
        )
        for child in children:
            self._assign(child, conversation_id)


def locale_for_task(session: Session, task: TaskModel | None) -> str:
    if task is None:
        return "pt"
    current = task
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.parent_id is None:
            break
        current = session.get(TaskModel, current.parent_id)
    root = current or task
    if root.conversation_id is not None:
        conversation = session.get(ConversationModel, root.conversation_id)
        if conversation is not None and conversation.locale:
            return conversation.locale
    meta = root.metadata_json or {}
    if meta.get("locale") in {"pt", "en", "es"}:
        return str(meta["locale"])
    return detect_language(root.objective or root.title or "")
