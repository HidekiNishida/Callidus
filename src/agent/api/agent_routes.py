# src/agent/api/agent_routes.py — interface HTTP da hierarquia de agentes
"""Endpoints da hierarquia de agentes: consultar, suspender, retomar, descartar e perguntar.

A interface expõe as operações que o modelo de agente usa por dentro. O objetivo é
que a hierarquia seja **observável e controlável** de fora: dá para ver a árvore,
suspender um ramo, consultar um filho e descartar o que não serve mais.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.api.deps import db_session, read_settings
from agent.config import Settings
from agent.domain.agent_enums import AgentStatus, ExecutionStatus
from agent.domain.schemas import AgentAsk, AgentDiscard, AgentRead, AgentQueryRead
from agent.orchestrator.decomposition import profile_from_run_config
from agent.orchestrator.runner import _select_provider
from agent.persistence.models import AgentExecutionModel, AgentModel, AgentQueryModel
from agent.services.agent_service import (
    AgentNotFoundError,
    AgentService,
    DiscardBlockedError,
)
from agent.services.query_service import QueryRejectedError, QueryService

router = APIRouter()


class AgentExecutionRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    task_id: uuid.UUID | None
    run_id: uuid.UUID | None
    status: ExecutionStatus
    attempt: int
    checkpoint_json: dict | None
    last_error: str | None
    created_at: Any
    updated_at: Any
    started_at: Any
    finished_at: Any

    model_config = {"from_attributes": True}


def _agent_read(service: AgentService, agent: AgentModel) -> AgentRead:
    execution = service.current_execution(agent.id)
    children = service.children(agent.id)
    return AgentRead(
        id=agent.id,
        project_id=agent.project_id,
        parent_id=agent.parent_id,
        task_id=agent.task_id,
        role=agent.role,
        instructions=agent.instructions,
        status=AgentStatus(agent.status),
        depth=agent.depth,
        children=len(children),
        execution_status=ExecutionStatus(execution.status) if execution else None,
        findings=service.findings(agent.id),
        checkpoint=service.checkpoint(agent.id),
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.get("/projects/{project_id}/agents", response_model=list[AgentRead])
def list_agents(
    project_id: uuid.UUID, session: Session = Depends(db_session)
) -> list[AgentRead]:
    """Árvore de agentes do projeto (raízes primeiro)."""
    service = AgentService(session)
    agents = (
        session.query(AgentModel)
        .filter(AgentModel.project_id == project_id)
        .order_by(AgentModel.depth, AgentModel.created_at)
        .all()
    )
    return [_agent_read(service, agent) for agent in agents]


@router.get("/agents/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: uuid.UUID, session: Session = Depends(db_session)) -> AgentRead:
    service = AgentService(session)
    try:
        return _agent_read(service, service.get(agent_id))
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/executions", response_model=list[AgentExecutionRead])
def agent_executions(
    agent_id: uuid.UUID, session: Session = Depends(db_session)
) -> list[AgentExecutionRead]:
    service = AgentService(session)
    try:
        service.get(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [AgentExecutionRead.model_validate(row) for row in service.executions(agent_id)]


@router.post("/agents/{agent_id}/suspend")
def suspend_agent(
    agent_id: uuid.UUID,
    reason: str = "",
    session: Session = Depends(db_session),
) -> dict:
    """Suspende a execução do agente: persiste o estado e libera o contexto."""
    service = AgentService(session)
    try:
        service.get(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if service.current_execution(agent_id) is None:
        raise HTTPException(
            status_code=409, detail="o agente não tem execução para suspender"
        )
    execution = service.suspend(agent_id, reason=reason)
    return {
        "agent_id": str(agent_id),
        "execution_id": str(execution.id),
        "status": execution.status,
        "checkpoint": execution.checkpoint_json,
    }


@router.post("/agents/{agent_id}/resume")
def resume_agent(agent_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Retoma a execução suspensa a partir do estado persistido."""
    service = AgentService(session)
    try:
        execution = service.resume(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "agent_id": str(agent_id),
        "execution_id": str(execution.id),
        "status": execution.status,
        "attempt": execution.attempt,
        "checkpoint": execution.checkpoint_json,
    }


@router.post("/agents/{agent_id}/discard")
def discard_agent(
    agent_id: uuid.UUID,
    body: AgentDiscard | None = None,
    session: Session = Depends(db_session),
) -> dict:
    """Descarta o estado recuperável do agente. Resultados e artefatos são preservados."""
    payload = body or AgentDiscard()
    service = AgentService(session)
    try:
        return service.discard(
            agent_id,
            purge=payload.purge,
            reason=payload.reason,
            force=payload.force,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DiscardBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/queries", response_model=list[AgentQueryRead])
def agent_queries(
    agent_id: uuid.UUID, session: Session = Depends(db_session)
) -> list[AgentQueryRead]:
    service = QueryService(session)
    try:
        AgentService(session).get(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [AgentQueryRead.model_validate(row) for row in service.queries_of(agent_id)]


@router.post("/agents/{agent_id}/queries", response_model=AgentQueryRead)
async def ask_agent(
    agent_id: uuid.UUID,
    body: AgentAsk,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> AgentQueryRead:
    """Consulta dirigida: o solicitante pergunta ao alvo e recebe a resposta.

    A resposta sai do estado persistido quando ele já contém a informação; só há
    inferência quando falta evidência — e ela passa pelo executor compartilhado.
    """
    service = QueryService(session)
    try:
        query = service.ask(
            body.requester_agent_id,
            agent_id,
            body.question,
            task_id=body.task_id,
            correlation_id=body.correlation_id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QueryRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    provider = profile = None
    if not service.answer_from_persisted(query):
        try:
            # O limite do executor acompanha as configurações desta requisição.
            from agent.services.executor import get_executor

            get_executor(settings)
            provider = _select_provider(settings, {"provider": body.provider} if body.provider else {})
            profile = profile_from_run_config({}, settings, provider=provider)
        except Exception:  # noqa: BLE001 — sem provedor, responde com o estado persistido
            provider = None
    # A consulta já existe antes da inferência: se a resposta falhar, o registro (e a
    # tentativa contada) não desaparecem com o rollback da requisição.
    session.commit()
    query = await service.resolve(query.id, provider=provider, profile=profile)
    return AgentQueryRead.model_validate(query)


@router.get("/metrics/resources")
def resource_metrics(
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    """Métricas de recursos e de uso — só o que o Callidus sabe medir de fato.

    Tokens e memória do backend não entram aqui: quando o provedor não os informa, o
    número seria inventado. O que é real: concorrência de inferências, tempo de espera
    pelo executor e o estado da hierarquia de agentes.
    """
    from agent.services.executor import get_executor

    executor = get_executor(settings)
    agents = session.query(AgentModel).all()
    executions = session.query(AgentExecutionModel).all()
    queries = session.query(AgentQueryModel).all()
    return {
        "executor": executor.metrics().snapshot(),
        "executor_limit": executor.limit,
        "agents": {
            "total": len(agents),
            "by_status": _count_by(agents, "status"),
            "max_depth": max((a.depth for a in agents), default=0),
        },
        "executions": {
            "total": len(executions),
            "by_status": _count_by(executions, "status"),
            "suspended": sum(
                1 for e in executions if e.status == ExecutionStatus.SUSPENDED.value
            ),
        },
        "queries": {
            "total": len(queries),
            "by_status": _count_by(queries, "status"),
            "answered_from_state": sum(
                1
                for q in queries
                if (q.answer_json or {}).get("from_persisted_state") is True
                and (q.answer_json or {}).get("inference_used") is False
            ),
        },
    }


def _count_by(rows, attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attribute, "") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts
