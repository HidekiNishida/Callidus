"""
Arquivo: src/agent/services/inbox.py
Nome: inbox.py
Propósito: resolver a pasta do usuário quando ninguém escolheu um diretório de trabalho.
Responsabilidade: camada de aplicação — definição da raiz efetiva das ferramentas.
Componentes: user_home, is_inbox_path, is_inbox_project, effective_root.
Dependências: agent.brand.
Observações: sem escolha explícita, as ferramentas agem na pasta pessoal do usuário.
"""
from __future__ import annotations

from pathlib import Path

from agent.brand import INBOX_ROOT, LEGACY_INBOX_ROOT


def user_home() -> str:
    """Pasta pessoal do usuário.

    Returns:
        O caminho absoluto da pasta pessoal.
    """
    return str(Path.home())


def is_inbox_path(root_path: str | None) -> bool:
    """Indica se um caminho corresponde à caixa de entrada local.

    Args:
        root_path: caminho da raiz do projeto.

    Returns:
        `True` quando o caminho é a caixa de entrada (nova ou legada).
    """
    value = str(root_path or "")
    return value.startswith(INBOX_ROOT.split("://")[0]) or value.startswith(
        LEGACY_INBOX_ROOT.split("://")[0]
    )


def is_inbox_project(project) -> bool:
    """Indica se um projeto usa a caixa de entrada como pasta de trabalho.

    Args:
        project: projeto consultado.

    Returns:
        `True` quando o projeto é a caixa de entrada.
    """
    if project is None:
        return False
    return getattr(project, "path_origin", "") == "inbox" or is_inbox_path(getattr(project, "root_path", ""))


def effective_root(project, conversation=None) -> str:
    """Pasta em que as ferramentas podem agir. Sem escolha, é a do usuário.

    Args:
        project: projeto da conversa.
        conversation: conversa em execução, com a escolha de pasta do usuário.

    Returns:
        O caminho absoluto da pasta efetiva.
    """
    override = getattr(conversation, "root_path", None) if conversation is not None else None
    if override:
        return str(override)
    root = getattr(project, "root_path", None) if project is not None else None
    if root and not is_inbox_path(root):
        return str(root)
    return user_home()
