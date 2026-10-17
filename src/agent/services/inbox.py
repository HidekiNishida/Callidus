# src/agent/services/inbox.py — pasta do usuário quando ninguém escolheu um diretório
from __future__ import annotations

from pathlib import Path

INBOX_ROOT = "agente-inbox://local"


def user_home() -> str:
    return str(Path.home())


def is_inbox_path(root_path: str | None) -> bool:
    return str(root_path or "").startswith("agente-inbox://")


def is_inbox_project(project) -> bool:
    if project is None:
        return False
    return getattr(project, "path_origin", "") == "inbox" or is_inbox_path(getattr(project, "root_path", ""))


def effective_root(project, conversation=None) -> str:
    """Pasta em que as ferramentas podem agir. Sem escolha, é a do usuário."""
    override = getattr(conversation, "root_path", None) if conversation is not None else None
    if override:
        return str(override)
    root = getattr(project, "root_path", None) if project is not None else None
    if root and not is_inbox_path(root):
        return str(root)
    return user_home()
