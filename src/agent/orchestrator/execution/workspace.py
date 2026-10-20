"""
Arquivo: src/agent/orchestrator/execution/workspace.py
Nome: workspace.py
Propósito: descobrir a pasta de trabalho efetiva de uma etapa.
Responsabilidade: camada de aplicação — resolve a raiz do projeto (ou da conversa) usada pelas ferramentas.
Componentes: work_root.
Dependências: agent.services.inbox (effective_root), agent.persistence.models (ProjectModel, TaskModel, ConversationModel).
Observações: a raiz pode ser o projeto ou uma conversa solta (inbox) — as ferramentas sempre operam dentro dela.
"""

from __future__ import annotations

from agent.persistence.models import ConversationModel, ProjectModel, TaskModel
from agent.services.inbox import effective_root


def work_root(session, project: ProjectModel, task: TaskModel | None) -> str:
    """Pasta de trabalho da etapa.

    Args:
        session: sessão SQLAlchemy em uso.
        project: projeto da execução.
        task: etapa em foco; quando tem conversa própria, a conversa define a raiz.

    Returns:
        O caminho absoluto da pasta de trabalho.
    """
    conversation = None
    if task is not None and task.conversation_id:
        conversation = session.get(ConversationModel, task.conversation_id)
    return effective_root(project, conversation)
