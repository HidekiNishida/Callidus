"""
Arquivo: src/agent/knowledge/tools.py
Nome: tools.py
Propósito: ferramentas do Knowledge Engine expostas ao modelo.
Responsabilidade: camada de aplicação — ferramentas search_knowledge, acquire_knowledge, etc.
Componentes: register_knowledge_tools.
Dependências: agent.tools.registry, agent.knowledge.service, agent.knowledge.memory.
Observações: seguem o padrão ToolSpec/ToolHandler do ToolRegistry.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from agent.tools.registry import ToolRegistry, ToolSpec, ToolContext, ToolRisk, ToolFamily, ExecutionMode
from agent.knowledge.service import KnowledgeEngineService
from agent.knowledge.memory import KnowledgeReuser
from agent.knowledge.models import KnowledgeValidationStatus


async def _get_knowledge_service(ctx: ToolContext) -> KnowledgeEngineService:
    """Obtém instância do KnowledgeEngineService."""
    return KnowledgeEngineService(ctx.session)


async def _get_knowledge_reuser(ctx: ToolContext) -> KnowledgeReuser:
    """Obtém instância do KnowledgeReuser."""
    from agent.knowledge.memory.store import KnowledgeMemoryStore
    store = KnowledgeMemoryStore(ctx.session)
    return KnowledgeReuser(store)


async def search_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Busca itens de conhecimento no projeto."""
    service = await _get_knowledge_service(ctx)

    project_id = uuid.UUID(ctx.project_id) if ctx.project_id else None
    if not project_id:
        return {"success": False, "error": "project_id não disponível no contexto"}

    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query é obrigatória"}

    kind = args.get("kind")
    technology = args.get("technology")
    version = args.get("version")
    min_confidence = args.get("min_confidence", 0.0)
    limit = args.get("limit", 10)

    results = service.search_knowledge(
        project_id=project_id,
        query=query,
        kind=kind,
        technology=technology,
        version=version,
        min_confidence=min_confidence,
        limit=limit,
    )

    items = []
    for item in results:
        items.append({
            "id": str(item.id),
            "title": item.title,
            "summary": item.summary,
            "technology": item.technology,
            "version": item.version,
            "kind": item.kind,
            "confidence": item.confidence,
            "validation_status": item.validation_status,
            "usage_count": item.usage_count,
            "source_count": item.source_count,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        })

    return {
        "success": True,
        "count": len(items),
        "items": items,
    }


async def get_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Obtém detalhes completos de um item de conhecimento."""
    service = await _get_knowledge_service(ctx)

    item_id_str = args.get("item_id")
    if not item_id_str:
        return {"success": False, "error": "item_id é obrigatório"}

    try:
        item_id = uuid.UUID(item_id_str)
    except ValueError:
        return {"success": False, "error": "item_id inválido"}

    data = service.get_knowledge_with_sources(item_id)
    if not data:
        return {"success": False, "error": "Item não encontrado"}

    item = data["item"]
    sources = data["sources"]
    validations = data["validations"]

    return {
        "success": True,
        "item": {
            "id": str(item.id),
            "title": item.title,
            "content": item.content,
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
        },
        "sources": [
            {
                "source_kind": s.source_kind,
                "title": s.title,
                "url": s.url,
                "author": s.author,
                "credibility": s.credibility,
                "published_at": s.published_at.isoformat() if s.published_at else None,
            }
            for s in sources
        ],
        "validations": [
            {
                "validation_kind": v.validation_kind,
                "method": v.method,
                "passed": v.passed,
                "notes": v.notes,
                "validated_at": v.validated_at.isoformat() if v.validated_at else None,
                "validated_by": v.validated_by,
            }
            for v in validations
        ],
    }


async def acquire_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Solicita aquisição de conhecimento externo para uma pergunta."""
    service = await _get_knowledge_service(ctx)

    project_id = uuid.UUID(ctx.project_id) if ctx.project_id else None
    if not project_id:
        return {"success": False, "error": "project_id não disponível no contexto"}

    question = args.get("question", "")
    if not question:
        return {"success": False, "error": "question é obrigatória"}

    task_id = None
    if ctx.task_id:
        try:
            task_id = uuid.UUID(ctx.task_id)
        except ValueError:
            pass

    # Criar solicitação
    from agent.knowledge.request import KnowledgeRequestCreate, KnowledgeDepth
    depth_str = args.get("depth", "standard")
    try:
        depth = KnowledgeDepth(depth_str)
    except ValueError:
        depth = KnowledgeDepth.STANDARD

    request_data = KnowledgeRequestCreate(
        project_id=project_id,
        task_id=task_id,
        question=question,
        depth=depth,
        max_acquisition_time_sec=args.get("max_time", 120),
    )

    request = service.create_request(request_data)

    # Executar aquisição (async)
    providers = args.get("providers")
    max_results = args.get("max_results_per_provider", 3)

    item = await service.acquire_knowledge(
        request.id,
        providers=providers,
        max_results_per_provider=max_results,
    )

    if not item:
        return {"success": False, "error": "Falha na aquisição", "request_id": str(request.id)}

    return {
        "success": True,
        "request_id": str(request.id),
        "item_id": str(item.id),
        "title": item.title,
        "summary": item.summary,
        "technology": item.technology,
        "confidence": item.confidence,
        "validation_status": item.validation_status,
    }


async def save_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Salva conhecimento manualmente (ex.: descoberta do agente)."""
    service = await _get_knowledge_service(ctx)

    project_id = uuid.UUID(ctx.project_id) if ctx.project_id else None
    if not project_id:
        return {"success": False, "error": "project_id não disponível no contexto"}

    title = args.get("title", "")
    content = args.get("content", "")
    if not title or not content:
        return {"success": False, "error": "title e content são obrigatórios"}

    kind = args.get("kind", "fact")
    summary = args.get("summary")
    technology = args.get("technology")
    version = args.get("version")
    confidence = args.get("confidence", 0.7)
    sources = args.get("sources", [])
    context_tags = args.get("context_tags")

    item = service.save_knowledge(
        project_id=project_id,
        kind=kind,
        title=title,
        content=content,
        summary=summary,
        technology=technology,
        version=version,
        confidence=confidence,
        sources=sources,
        context_tags=context_tags,
    )

    return {
        "success": True,
        "item_id": str(item.id),
        "title": item.title,
    }


async def validate_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Valida um item de conhecimento."""
    service = await _get_knowledge_service(ctx)

    item_id_str = args.get("item_id")
    if not item_id_str:
        return {"success": False, "error": "item_id é obrigatório"}

    try:
        item_id = uuid.UUID(item_id_str)
    except ValueError:
        return {"success": False, "error": "item_id inválido"}

    validation_kind = args.get("validation_kind", "manual")
    passed = args.get("passed")
    method = args.get("method")
    criteria = args.get("criteria")
    evidence = args.get("evidence")
    notes = args.get("notes")

    validation = service.add_validation(
        item_id=item_id,
        validation_kind=validation_kind,
        method=method,
        criteria=criteria,
        evidence=evidence,
        passed=passed,
        notes=notes,
        validated_by="agent",
    )

    if not validation:
        return {"success": False, "error": "Item não encontrado"}

    return {
        "success": True,
        "validation_id": str(validation.id),
        "passed": validation.passed,
        "item_validation_status": validation.item.validation_status if hasattr(validation, 'item') else None,
    }


async def reuser_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Recupera e formata conhecimento para injeção no contexto da task."""
    reuser = await _get_knowledge_reuser(ctx)

    project_id = uuid.UUID(ctx.project_id) if ctx.project_id else None
    if not project_id:
        return {"success": False, "error": "project_id não disponível no contexto"}

    task_objective = args.get("objective", "")
    if not task_objective:
        return {"success": False, "error": "objective é obrigatório"}

    task_technology = args.get("technology")
    max_items = args.get("max_items", 3)
    current_tokens = args.get("current_tokens", 0)

    result = reuser.prepare_context_for_task(
        project_id=project_id,
        task_objective=task_objective,
        task_technology=task_technology,
        current_context_tokens=current_tokens,
        max_items=max_items,
    )

    formatted = reuser.format_for_prompt(result)

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


async def knowledge_stats(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Estatísticas do Knowledge Engine do projeto."""
    service = await _get_knowledge_service(ctx)

    project_id = uuid.UUID(ctx.project_id) if ctx.project_id else None
    if not project_id:
        return {"success": False, "error": "project_id não disponível no contexto"}

    stats = service.get_stats(project_id)

    return {
        "success": True,
        "stats": stats,
    }


def register_knowledge_tools(registry: ToolRegistry) -> None:
    """Registra todas as ferramentas do Knowledge Engine."""

    registry.register(
        ToolSpec(
            id="search_knowledge",
            description="Busca itens de conhecimento no projeto por query, tecnologia, tipo, etc.",
            input_schema={
                "query": {"type": "string", "description": "Termo de busca"},
                "kind": {"type": "string", "description": "Tipo: fact, solution, pattern, etc."},
                "technology": {"type": "string", "description": "Tecnologia: python, javascript, etc."},
                "version": {"type": "string", "description": "Versão da tecnologia"},
                "min_confidence": {"type": "number", "description": "Confiança mínima (0-1)"},
                "limit": {"type": "integer", "description": "Máximo de resultados"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo count",
        ),
        search_knowledge,
    )

    registry.register(
        ToolSpec(
            id="get_knowledge",
            description="Obtém detalhes completos de um item de conhecimento (conteúdo, fontes, validações).",
            input_schema={
                "item_id": {"type": "string", "description": "ID do item de conhecimento"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira se o item existe",
        ),
        get_knowledge,
    )

    registry.register(
        ToolSpec(
            id="acquire_knowledge",
            description="Solicita aquisição de conhecimento externo via provedores de busca e IAs.",
            input_schema={
                "question": {"type": "string", "description": "Pergunta objetiva para pesquisa"},
                "depth": {"type": "string", "enum": ["quick", "standard", "deep", "comprehensive"]},
                "providers": {"type": "array", "items": {"type": "string"}, "description": "Provedores: duckduckgo, github, documentation"},
                "max_results_per_provider": {"type": "integer", "description": "Máx resultados por provedor"},
                "max_time": {"type": "integer", "description": "Tempo máximo em segundos"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.FOREGROUND.value,
            requires_approval=False,
            verify="confira request_id e item_id no retorno",
        ),
        acquire_knowledge,
    )

    registry.register(
        ToolSpec(
            id="save_knowledge",
            description="Salva conhecimento descoberto pelo agente (ex.: padrão, decisão, solução).",
            input_schema={
                "title": {"type": "string", "description": "Título do conhecimento"},
                "content": {"type": "string", "description": "Conteúdo completo"},
                "kind": {"type": "string", "enum": ["fact", "solution", "pattern", "decision", "documentation", "code_example", "best_practice", "warning", "troubleshooting"]},
                "summary": {"type": "string", "description": "Resumo curto"},
                "technology": {"type": "string", "description": "Tecnologia relacionada"},
                "version": {"type": "string", "description": "Versão da tecnologia"},
                "confidence": {"type": "number", "description": "Confiança (0-1)"},
                "sources": {"type": "array", "items": {"type": "object"}, "description": "Fontes de referência"},
                "context_tags": {"type": "array", "items": {"type": "string"}, "description": "Tags de contexto"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.WRITE.value,
            execution=ExecutionMode.FOREGROUND.value,
            requires_approval=False,
            verify="confira item_id no retorno",
        ),
        save_knowledge,
    )

    registry.register(
        ToolSpec(
            id="validate_knowledge",
            description="Valida um item de conhecimento (marca como validado ou falhou).",
            input_schema={
                "item_id": {"type": "string", "description": "ID do item"},
                "validation_kind": {"type": "string", "description": "Tipo: manual, code_review, test, usage"},
                "passed": {"type": "boolean", "description": "Se passou na validação"},
                "method": {"type": "string", "description": "Método de validação"},
                "criteria": {"type": "object", "description": "Critérios usados"},
                "evidence": {"type": "object", "description": "Evidências"},
                "notes": {"type": "string", "description": "Observações"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.WRITE.value,
            execution=ExecutionMode.FOREGROUND.value,
            requires_approval=False,
            verify="confira validation_id e status do item",
        ),
        validate_knowledge,
    )

    registry.register(
        ToolSpec(
            id="reuser_knowledge",
            description="Recupera conhecimento relevante para o contexto atual e formata para injeção no prompt.",
            input_schema={
                "objective": {"type": "string", "description": "Objetivo da task atual"},
                "technology": {"type": "string", "description": "Tecnologia da task"},
                "max_items": {"type": "integer", "description": "Máximo de itens a injetar"},
                "current_tokens": {"type": "integer", "description": "Tokens já usados no contexto"},
            },
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira formatted_knowledge no retorno",
        ),
        reuser_knowledge,
    )

    registry.register(
        ToolSpec(
            id="knowledge_stats",
            description="Estatísticas do Knowledge Engine do projeto.",
            input_schema={},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira stats no retorno",
        ),
        knowledge_stats,
    )