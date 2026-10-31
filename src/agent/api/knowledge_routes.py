"""
Arquivo: src/agent/api/knowledge_routes.py
Nome: knowledge_routes.py
Propósito: rotas da API para o Knowledge Engine (busca, aquisição, validação, estatísticas).
Responsabilidade: camada de apresentação — endpoints REST para o Knowledge Engine.
Componentes: router (FastAPI), endpoints CRUD para knowledge items, requests, stats.
Dependências: agent.api.deps, agent.knowledge.service, agent.knowledge.request.
Observações: segue padrão das rotas existentes (project_routes, task_routes, etc.).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from agent.api.deps import get_db_session
from agent.api.presenters import present_knowledge_item, present_knowledge_request
from agent.knowledge.request import KnowledgeDepth, KnowledgeRequestCreate
from agent.knowledge.service import KnowledgeEngineService

router = APIRouter(prefix="/projects/{project_id}/knowledge", tags=["knowledge"])


@router.get("/stats")
async def get_knowledge_stats(
    project_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Estatísticas do Knowledge Engine do projeto."""
    service = KnowledgeEngineService(session)
    stats = service.get_stats(project_id)
    return {"success": True, "stats": stats}


@router.get("/search")
async def search_knowledge(
    project_id: uuid.UUID,
    q: str = Query(..., description="Termo de busca"),
    kind: str | None = Query(None, description="Tipo: fact, solution, pattern, etc."),
    technology: str | None = Query(None, description="Tecnologia: python, javascript, etc."),
    version: str | None = Query(None, description="Versão da tecnologia"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Confiança mínima"),
    limit: int = Query(20, ge=1, le=100, description="Máximo de resultados"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Busca itens de conhecimento."""
    service = KnowledgeEngineService(session)
    results = service.search_knowledge(
        project_id=project_id,
        query=q,
        kind=kind,
        technology=technology,
        version=version,
        min_confidence=min_confidence,
        limit=limit,
    )

    items = [present_knowledge_item(item) for item in results]
    return {"success": True, "count": len(items), "items": items}


@router.get("/items/{item_id}")
async def get_knowledge_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Obtém detalhes completos de um item de conhecimento."""
    service = KnowledgeEngineService(session)
    data = service.get_knowledge_with_sources(item_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado")

    return {"success": True, "data": data}


@router.post("/items")
async def create_knowledge_item(
    project_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Cria item de conhecimento manualmente."""
    service = KnowledgeEngineService(session)

    required = ["title", "content"]
    for field in required:
        if field not in payload:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Campo obrigatório: {field}")

    item = service.save_knowledge(
        project_id=project_id,
        kind=payload.get("kind", "fact"),
        title=payload["title"],
        content=payload["content"],
        summary=payload.get("summary"),
        technology=payload.get("technology"),
        version=payload.get("version"),
        confidence=payload.get("confidence", 0.7),
        sources=payload.get("sources"),
        context_tags=payload.get("context_tags"),
    )

    return {"success": True, "item_id": str(item.id), "title": item.title}


@router.patch("/items/{item_id}")
async def update_knowledge_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Atualiza item de conhecimento."""
    service = KnowledgeEngineService(session)

    item = service.update_knowledge(
        item_id=item_id,
        title=payload.get("title"),
        content=payload.get("content"),
        summary=payload.get("summary"),
        confidence=payload.get("confidence"),
        validation_status=payload.get("validation_status"),
        sources=payload.get("sources"),
    )

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado")

    return {"success": True, "item_id": str(item.id)}


@router.post("/items/{item_id}/validate")
async def validate_knowledge_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Valida um item de conhecimento."""
    service = KnowledgeEngineService(session)

    validation = service.add_validation(
        item_id=item_id,
        validation_kind=payload.get("validation_kind", "manual"),
        method=payload.get("method"),
        criteria=payload.get("criteria"),
        evidence=payload.get("evidence"),
        passed=payload.get("passed"),
        notes=payload.get("notes"),
        validated_by=payload.get("validated_by", "api"),
    )

    if not validation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado")

    return {"success": True, "validation_id": str(validation.id), "passed": validation.passed}


@router.post("/requests")
async def create_knowledge_request(
    project_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Cria solicitação de aquisição de conhecimento."""
    service = KnowledgeEngineService(session)

    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question é obrigatória")

    try:
        depth = KnowledgeDepth(payload.get("depth", "standard"))
    except ValueError:
        depth = KnowledgeDepth.STANDARD

    request_data = KnowledgeRequestCreate(
        project_id=project_id,
        task_id=uuid.UUID(payload["task_id"]) if payload.get("task_id") else None,
        question=question,
        context=payload.get("context"),
        constraints=payload.get("constraints"),
        desired_kind=payload.get("desired_kind"),
        depth=depth,
        validation_criteria=payload.get("validation_criteria"),
        max_acquisition_time_sec=payload.get("max_acquisition_time_sec", 120),
    )

    request = service.create_request(request_data)
    return {"success": True, "request_id": str(request.id)}


@router.post("/requests/{request_id}/acquire")
async def acquire_knowledge_for_request(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Executa aquisição de conhecimento para uma solicitação."""
    service = KnowledgeEngineService(session)

    providers = payload.get("providers")
    max_results = payload.get("max_results_per_provider", 3)

    item = await service.acquire_knowledge(
        request_id,
        providers=providers,
        max_results_per_provider=max_results,
    )

    if not item:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falha na aquisição")

    return {"success": True, "item_id": str(item.id), "title": item.title}


@router.get("/requests/{request_id}")
async def get_knowledge_request(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Obtém status de uma solicitação de conhecimento."""
    service = KnowledgeEngineService(session)
    # Buscar request
    from agent.persistence.models import KnowledgeRequestModel
    request = session.get(KnowledgeRequestModel, request_id)
    if not request or request.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")

    return {
        "success": True,
        "request": {
            "id": str(request.id),
            "question": request.question,
            "status": request.status,
            "result_item_id": str(request.result_item_id) if request.result_item_id else None,
            "error_message": request.error_message,
            "started_at": request.started_at.isoformat() if request.started_at else None,
            "completed_at": request.completed_at.isoformat() if request.completed_at else None,
            "created_at": request.created_at.isoformat() if request.created_at else None,
        },
    }


@router.post("/reuser")
async def reuser_knowledge(
    project_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Recupera conhecimento relevante para injeção no contexto."""
    from agent.knowledge.memory import KnowledgeReuser
    from agent.knowledge.memory.store import KnowledgeMemoryStore

    store = KnowledgeMemoryStore(session)
    reuser = KnowledgeReuser(store)

    objective = payload.get("objective")
    if not objective:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="objective é obrigatório")

    project_id_uuid = project_id
    task_technology = payload.get("technology")
    max_items = payload.get("max_items", 3)
    current_tokens = payload.get("current_tokens", 0)

    result = reuser.prepare_context_for_task(
        project_id=project_id_uuid,
        task_objective=objective,
        task_technology=task_technology,
        current_context_tokens=payload.get("current_tokens", 0),
        max_items=payload.get("max_items", 3),
    )

    from agent.knowledge.memory.reuse import KnowledgeReuser as KR
    formatted = KR.format_for_prompt(None, result)

    return {
        "success": True,
        "formatted_knowledge": formatted,
        "items_count": len(result.knowledge_items),
        "total_tokens": result.total_tokens,
        "budget_used": result.budget_used,
        "retrieval_time_ms": result.retrieval_time_ms,
        "items": [
            {
                "title": item.title,
                "technology": item.technology,
                "confidence": item.confidence,
                "validation_status": item.validation_status,
                "citation": item.citation,
            }
            for item in result.knowledge_items
        ],
    }