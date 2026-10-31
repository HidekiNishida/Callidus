"""
Arquivo: src/agent/api/presenters.py
Nome: presenters.py
Propósito: montar os payloads de leitura (tarefa, conversa, knowledge) que a API devolve.
Responsabilidade: camada de apresentação — serialização de leitura; não altera estado.
Componentes: usage_tokens, remembered_model, present_task, present_conversation, present_knowledge_item, present_knowledge_source, present_knowledge_validation.
Dependências: agent.domain.schemas, agent.services.conversation_service, agent.persistence.models.
Observações: a apresentação é única para toda a API — a mesma tarefa aparece igual em qualquer rota.
"""
from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.schemas import BranchRead, ConversationRead, TaskRead
from agent.i18n.locale import translate
from agent.persistence.models import (
    ConversationModel,
    ExecutionRunModel,
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeValidationModel,
    ProjectModel,
)
from agent.services.conversation_service import ConversationService, locale_for_task
from agent.services.inbox import effective_root, is_inbox_project


def present_knowledge_item(item: KnowledgeItemModel) -> dict:
    """Serializa um item de conhecimento para a API."""
    return {
        "id": str(item.id),
        "title": item.title,
        "summary": item.summary,
        "kind": item.kind,
        "technology": item.technology,
        "version": item.version,
        "confidence": item.confidence,
        "validation_status": item.validation_status,
        "context_tags": item.context_tags_json,
        "usage_count": item.usage_count,
        "source_count": item.source_count,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def present_knowledge_source(source: KnowledgeSourceModel) -> dict:
    """Serializa uma fonte de conhecimento para a API."""
    return {
        "id": str(source.id),
        "source_kind": source.source_kind,
        "title": source.title,
        "url": source.url,
        "author": source.author,
        "credibility": source.credibility,
        "published_at": source.published_at.isoformat() if source.published_at else None,
    }


def present_knowledge_validation(validation: KnowledgeValidationModel) -> dict:
    """Serializa uma validação de conhecimento para a API."""
    return {
        "id": str(validation.id),
        "validation_kind": validation.validation_kind,
        "method": validation.method,
        "passed": validation.passed,
        "notes": validation.notes,
        "validated_at": validation.validated_at.isoformat() if validation.validated_at else None,
        "validated_by": validation.validated_by,
    }


def usage_tokens(session: Session, task) -> int:
    """Informa quantos tokens a tarefa consumiu.

    Args:
        session: sessão do banco da requisição.
        task: tarefa consultada.

    Returns:
        O total de tokens registrado na tarefa, ou o estimado no snapshot mais recente quando a tarefa não tem uso próprio.
    """
    from agent.orchestrator.ledger import task_reported_total

    total, measurement = task_reported_total(session, task.id)
    if total is not None and measurement != "unavailable":
        return int(total)
    meta = task.metadata_json or {}
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
    if usage and usage.get("total") is not None and usage.get("measurement"):
        return int(usage["total"])
    # Estimativa de janela não é consumo. Sem registro, o total exibido é zero
    # e o painel de contexto mostra a estimativa no campo próprio.
    return 0


def remembered_model(session: Session, task) -> dict:
    """Recupera os metadados da tarefa, lembrando o modelo usado pelo run quando ela não tem um.

    Args:
        session: sessão do banco da requisição.
        task: tarefa consultada.

    Returns:
        Os metadados da tarefa, com `model_id` preenchido a partir do run raiz quando aplicável.
    """
    meta = dict(task.metadata_json or {})
    if task.parent_id is not None or meta.get("model_id"):
        return meta
    run = session.scalar(
        select(ExecutionRunModel)
        .where(ExecutionRunModel.root_task_id == task.id)
        .order_by(ExecutionRunModel.created_at.desc())
        .limit(1)
    )
    model_id = ((run.config_json or {}) if run else {}).get("model_id")
    if model_id:
        meta["model_id"] = model_id
    return meta


def present_task(session: Session, task) -> TaskRead:
    """Serializa uma tarefa no formato entregue à interface.

    Args:
        session: sessão do banco da requisição.
        task: registro da tarefa.

    Returns:
        A tarefa com título traduzido, uso de tokens e metadados complementados.

    Observações:
        A apresentação é única para toda a API: a mesma tarefa aparece igual em qualquer rota.
    """
    data = TaskRead.model_validate(task)
    return data.model_copy(
        update={
            "display_title": translate(task.title, locale_for_task(session, task)),
            "usage_tokens": usage_tokens(session, task),
            "metadata_json": remembered_model(session, task),
        }
    )


def present_conversation(session: Session, item: ConversationModel) -> ConversationRead:
    """Serializa uma conversa no formato entregue à interface.

    Args:
        session: sessão do banco da requisição.
        item: registro da conversa.

    Returns:
        A conversa com raiz efetiva, origem do caminho, ramo ativo e a lista de ramos.

    Observações:
        A conversa da caixa de entrada é apresentada sem `project_id`, para não se confundir com as conversas de um projeto.
    """
    service = ConversationService(session)
    service.ensure_branch(item)
    project = session.get(ProjectModel, item.project_id)
    inbox = is_inbox_project(project)
    chosen = bool(item.root_path) or (
        project is not None and project.path_origin == "chosen" and not inbox
    )
    branches = [BranchRead.model_validate(branch) for branch in service.branches_of(item.id)]
    data = ConversationRead.model_validate(item)
    return data.model_copy(
        update={
            "project_id": None if inbox else item.project_id,
            "workspace_id": item.project_id,
            "root_path": effective_root(project, item),
            "path_origin": "chosen" if chosen else "home",
            "active_branch_id": item.active_branch_id,
            "branches": branches,
        }
    )