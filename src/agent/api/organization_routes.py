"""
Arquivo: src/agent/api/organization_routes.py
Nome: organization_routes.py
Propósito: interface HTTP da organização de engenharia — organograma, propriedade, quadro, contrato de trabalho, portões, revisões, handoff e indicadores de entrega.
Responsabilidade: camada de apresentação/transport — valida, delega ao `OrganizationService`/`AnalyticsService` e serializa.
Componentes: router, ReviewCreate, organization, owner, board, work_item, gates, create_review, handoff, delivery_metrics.
Dependências: agent.api.deps, agent.services.organization_service, agent.intelligence.analytics, fastapi, pydantic.
Observações: rotas novas e aditivas; nenhuma rota existente muda. Revisão sem independência vira 422, tarefa inexistente vira 404.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent.api.deps import db_session
from agent.intelligence.analytics import AnalyticsService
from agent.persistence.models import ProjectModel, TaskModel
from agent.services.organization_service import OrganizationService, ReviewRejectedError

router = APIRouter(tags=["organization"])


class ReviewCreate(BaseModel):
    """Pedido de revisão independente.

    Atributos:
        role: papel de quem revisa (ex.: `qa_engineer`).
        decision: `approved` ou `rejected`.
        reason: motivo; obrigatório para reprovar.
        evidence_ids: evidências conferidas.
    """

    role: str
    decision: str
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


@router.get("/organization")
def organization(
    project_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Organograma, papéis, especialidades, propriedade e os agentes do projeto por papel."""
    return OrganizationService(session).directory(project_id)


@router.get("/organization/owner")
def owner(path: str = Query(min_length=1), session: Session = Depends(db_session)) -> dict[str, Any]:
    """Dono de um caminho do projeto (`owner: null` quando não há regra)."""
    return {"path": path, "owner": OrganizationService(session).owner(path)}


@router.get("/projects/{project_id}/board")
def board(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict[str, Any]]:
    """Quadro do projeto: etapa, responsável, revisor e portões de cada tarefa."""
    if session.get(ProjectModel, project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return OrganizationService(session).board(project_id)


@router.get("/tasks/{task_id}/work-item")
def work_item(task_id: uuid.UUID, session: Session = Depends(db_session)) -> dict[str, Any]:
    """Contrato de trabalho da tarefa (atribuído na hora se ainda não existir)."""
    try:
        return OrganizationService(session).work_item(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/gates")
def gates(task_id: uuid.UUID, session: Session = Depends(db_session)) -> dict[str, Any]:
    """Portões G0–G4, etapa do fluxo e avaliação da entrega em cinco dimensões."""
    try:
        return OrganizationService(session).gates(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/reviews", status_code=201)
def create_review(task_id: uuid.UUID, body: ReviewCreate, session: Session = Depends(db_session)) -> dict[str, Any]:
    """Registra a revisão de um papel independente; a reprovação bloqueia a integração."""
    try:
        return OrganizationService(session).record_review(
            task_id, role=body.role, decision=body.decision, reason=body.reason, evidence_ids=body.evidence_ids
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/handoff")
def handoff(task_id: uuid.UUID, session: Session = Depends(db_session)) -> dict[str, Any]:
    """Handoff estruturado da tarefa, montado agora a partir do estado persistido."""
    task = session.get(TaskModel, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return OrganizationService(session).build_handoff(task)


@router.get("/api/intelligence/metrics/delivery")
def delivery_metrics(
    project_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Indicadores de entrega com numerador, denominador e tipo de medida."""
    return AnalyticsService(session).delivery_metrics(project_id=project_id)
