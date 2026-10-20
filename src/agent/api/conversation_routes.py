"""
Arquivo: src/agent/api/conversation_routes.py
Nome: conversation_routes.py
Propósito: expor as conversas, seus ramos e as tarefas de cada conversa.
Responsabilidade: camada de apresentação/transport — rotas de conversa; delega as regras ao serviço.
Componentes: conversas soltas, mover, renomear, bifurcar, ativar ramo, conversas do projeto.
Dependências: agent.services.conversation_service, agent.api.presenters.
Observações: a conversa define a raiz do trabalho; o projeto sem conversa é o "inbox".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.api.deps import db_session
from agent.api.presenters import present_conversation, present_task
from agent.domain.schemas import (
    ConversationCreate,
    ConversationFork,
    ConversationMove,
    ConversationRead,
    ConversationUpdate,
    TaskRead,
)
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService

router = APIRouter()


@router.get("/conversations", response_model=list[ConversationRead])
def list_loose_conversations(session: Session = Depends(db_session)) -> list[ConversationRead]:
    """Lista as conversas soltas, ou seja, as que não pertencem a nenhum projeto.

    Args:
        session: sessão do banco da requisição.

    Returns:
        As conversas soltas, serializadas para a interface.
    """
    items = ConversationService(session).list_loose()
    return [present_conversation(session, item) for item in items]


@router.post("/conversations", response_model=ConversationRead)
def create_loose_conversation(
    body: ConversationCreate, session: Session = Depends(db_session)
) -> ConversationRead:
    """Cria uma conversa sem projeto associado — a caixa de entrada do agente.

    Args:
        body: dados da conversa a criar.
        session: sessão do banco da requisição.

    Returns:
        A conversa criada, serializada.
    """
    item = ConversationService(session).create_loose(body)
    return present_conversation(session, item)


@router.post("/conversations/{conversation_id}/move", response_model=ConversationRead)
def move_conversation(
    conversation_id: uuid.UUID, body: ConversationMove, session: Session = Depends(db_session)
) -> ConversationRead:
    """Move uma conversa para um projeto.

    Args:
        conversation_id: identificador da conversa movida.
        body: projeto de destino.
        session: sessão do banco da requisição.

    Returns:
        A conversa já movida, serializada.

    Raises:
        HTTPException: com status 404 quando a conversa ou o projeto não existem.
    """
    try:
        item = ConversationService(session).move_conversation(conversation_id, body.project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return present_conversation(session, item)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Remove uma conversa e o que depende dela.

    Args:
        conversation_id: identificador da conversa removida.
        session: sessão do banco da requisição.

    Returns:
        A confirmação da remoção.

    Raises:
        HTTPException: com status 404 quando a conversa não existe e com status 409 quando a remoção é impedida por integridade referencial.
    """
    try:
        ConversationService(session).delete_conversation(conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"não foi possível remover a conversa: {exc.orig}",
        ) from exc
    return {"deleted": True}


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, session: Session = Depends(db_session)
) -> ConversationRead:
    """Atualiza título e raiz de uma conversa.

    Args:
        conversation_id: identificador da conversa alterada.
        body: campos a alterar; `clear_root` tem precedência sobre `root_path`.
        session: sessão do banco da requisição.

    Returns:
        A conversa já alterada, serializada.

    Raises:
        HTTPException: com status 404 quando a conversa não existe e com status 400 quando a raiz pedida é inválida.
    """
    service = ConversationService(session)
    try:
        if body.title is not None:
            service.rename(conversation_id, body.title)
        if body.clear_root:
            item = service.set_root(conversation_id, None)
        elif body.root_path is not None:
            item = service.set_root(conversation_id, body.root_path)
        else:
            item = service.get_conversation(conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return present_conversation(session, item)


@router.get("/conversations/{conversation_id}/tasks", response_model=list[TaskRead])
def conversation_tasks(
    conversation_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    session: Session = Depends(db_session),
) -> list[TaskRead]:
    """Lista as tarefas de uma conversa, opcionalmente restritas a um ramo.

    Args:
        conversation_id: identificador da conversa consultada.
        branch_id: quando informado, restringe a listagem ao ramo indicado.
        session: sessão do banco da requisição.

    Returns:
        As tarefas da conversa, serializadas.

    Raises:
        HTTPException: com status 404 quando a conversa não existe.
    """
    try:
        tasks = ConversationService(session).tasks_for_branch(conversation_id, branch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [present_task(session, task) for task in tasks]


@router.post("/conversations/{conversation_id}/fork")
def fork_conversation(
    conversation_id: uuid.UUID, body: ConversationFork, session: Session = Depends(db_session)
) -> dict:
    """Bifurca a conversa a partir de uma mensagem, criando uma tarefa no ramo novo.

    Args:
        conversation_id: identificador da conversa bifurcada.
        body: mensagem de origem e objetivo do ramo.
        session: sessão do banco da requisição.

    Returns:
        A conversa atualizada e a tarefa criada, ambas serializadas.

    Raises:
        HTTPException: com status 404 quando a conversa ou a mensagem de origem não existem.
    """
    service = ConversationService(session)
    try:
        task = service.fork_message(conversation_id, body.task_id, body.objective)
        item = service.get_conversation(conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "conversation": present_conversation(session, item),
        "task": present_task(session, task),
    }


@router.post("/conversations/{conversation_id}/branches/{branch_id}/activate", response_model=ConversationRead)
def activate_branch(
    conversation_id: uuid.UUID, branch_id: uuid.UUID, session: Session = Depends(db_session)
) -> ConversationRead:
    """Ativa um ramo da conversa, tornando-o o ramo corrente.

    Args:
        conversation_id: identificador da conversa.
        branch_id: identificador do ramo ativado.
        session: sessão do banco da requisição.

    Returns:
        A conversa com o ramo ativo, serializada.

    Raises:
        HTTPException: com status 404 quando a conversa ou o ramo não existem.
    """
    try:
        item = ConversationService(session).activate_branch(conversation_id, branch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return present_conversation(session, item)


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationRead])
def list_conversations(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[ConversationRead]:
    """Lista as conversas de um projeto.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        As conversas do projeto, serializadas.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
        items = ConversationService(session).list_conversations(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [present_conversation(session, item) for item in items]


@router.post("/projects/{project_id}/conversations", response_model=ConversationRead)
def create_conversation(
    project_id: uuid.UUID, body: ConversationCreate, session: Session = Depends(db_session)
) -> ConversationRead:
    """Cria uma conversa dentro de um projeto.

    Args:
        project_id: identificador do projeto que receberá a conversa.
        body: dados da conversa a criar.
        session: sessão do banco da requisição.

    Returns:
        A conversa criada, serializada.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
        item = ConversationService(session).create_conversation(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return present_conversation(session, item)
