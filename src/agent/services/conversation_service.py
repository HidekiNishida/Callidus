# src/agent/services/conversation_service.py — conversas dentro de um projeto
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.schemas import ConversationCreate
from agent.i18n.locale import detect_language
from agent.persistence.models import ConversationModel, TaskModel

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
