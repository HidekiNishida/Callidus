# src/agent/api/automation_routes.py — API das automações
"""Rotas das automações: criar, consultar, editar, ativar, suspender, executar uma
vez, testar, cancelar e remover.

A API não executa a automação por conta própria: ela registra o pedido e o runtime
(supervisor) faz o trabalho. "Executar uma vez" e "testar" são exceções explícitas,
que criam um disparo manual — sempre com chave própria, nunca colidindo com o
agendamento.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.api.deps import db_session, read_settings
from agent.automation.contracts import AutomationDefinition
from agent.automation.dependencies import DependencyResolver
from agent.automation.dispatcher import Dispatcher
from agent.automation.enums import AutomationState, FiringState, TargetKind
from agent.automation.executor import AutomationExecutor
from agent.automation.store import AutomationNotFound, AutomationService
from agent.config import Settings
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    EventLogModel,
    ProjectModel,
    ProjectRemoteModel,
)

router = APIRouter(prefix="/automations", tags=["automations"])


class AutomationIn(BaseModel):
    """Definição enviada pela interface."""

    definition: dict[str, Any]
    # Começa desabilitada, salvo pedido explícito.
    activate: bool = False


class AutomationPatch(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)


class TestIn(BaseModel):
    # `false`: só verifica prontidão (dependências e destino) sem executar a ação.
    execute: bool = False
    # Dispara mesmo assim que a definição esteja desabilitada.
    force: bool = False


def _present(session: Session, row: AutomationModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "description": row.description,
        "state": row.state,
        "contract_version": row.contract_version,
        "target": row.target_kind,
        "trigger": row.trigger_json or {},
        "action": row.action_json or {},
        "dependencies": row.dependencies_json or [],
        "permissions": row.permissions_json or {},
        "policy": row.policy_json or {},
        "timezone": row.timezone,
        "missed_policy": row.missed_policy,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "task_id": str(row.task_id) if row.task_id else None,
        "objective_mode": row.objective_mode,
        "objective": row.objective_json,
        "max_attempts": row.max_attempts,
        "timeout_sec": row.timeout_sec,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _present_firing(row: AutomationFiringModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "automation_id": str(row.automation_id),
        "idempotency_key": row.idempotency_key,
        "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
        "fired_at": row.fired_at.isoformat() if row.fired_at else None,
        "state": row.state,
        "attempt": row.attempt,
        "max_attempts": row.max_attempts,
        "run_id": str(row.run_id) if row.run_id else None,
        "task_id": str(row.task_id) if row.task_id else None,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "result": row.result_json or {},
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _readable_errors(exc: ValidationError) -> list[dict]:
    """Erros de validação legíveis (o `ctx` do pydantic carrega objetos não serializáveis)."""
    out: list[dict] = []
    for error in exc.errors():
        out.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
        )
    return out


def _service(session: Session) -> AutomationService:
    return AutomationService(session)


def _load(session: Session, automation_id: uuid.UUID) -> AutomationModel:
    try:
        return _service(session).get(automation_id)
    except AutomationNotFound as exc:
        raise HTTPException(status_code=404, detail="automação não encontrada") from exc


@router.post("/validate")
def validate_automation(body: AutomationIn) -> dict:
    """Valida a definição sem gravar nada."""
    try:
        definition = AutomationDefinition.model_validate(body.definition)
    except ValidationError as exc:
        return {"valid": False, "errors": _readable_errors(exc)}
    return {
        "valid": True,
        "definition": definition.model_dump(mode="json"),
        "next_run_at": None,
    }


@router.post("")
def create_automation(body: AutomationIn, session: Session = Depends(db_session)) -> dict:
    """Cria a automação. Ela nasce desabilitada, a menos que `activate` peça o contrário."""
    try:
        definition = AutomationDefinition.model_validate(body.definition)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_readable_errors(exc)) from exc
    project = session.get(ProjectModel, uuid.UUID(str(definition.project_id)))
    if project is None:
        raise HTTPException(status_code=404, detail="projeto não encontrado")
    definition.state = (
        AutomationState.ENABLED.value if body.activate else AutomationState.DISABLED.value
    )
    service = _service(session)
    row = service.create(definition)
    return _present(session, row)


@router.get("")
def list_automations(
    project_id: uuid.UUID | None = None,
    state: str | None = None,
    session: Session = Depends(db_session),
) -> list[dict]:
    rows = _service(session).list(project_id, state=state)
    return [_present(session, row) for row in rows]


@router.get("/supervisor/status")
def supervisor_status(settings: Settings = Depends(read_settings)) -> dict:
    """Situação do runtime de automações."""
    from agent.automation.supervisor import build_supervisor

    supervisor = build_supervisor(settings)
    payload = supervisor.status()
    try:
        from agent.automation.service import adapters_status, current_adapter

        payload["service"] = current_adapter().status().as_dict()
        payload["adapters"] = adapters_status()
    except Exception as exc:  # noqa: BLE001
        payload["service"] = {"error": str(exc)}
    return payload


@router.get("/supervisor/diagnose")
def supervisor_diagnose(settings: Settings = Depends(read_settings)) -> dict:
    """Diagnóstico: automações, próximos disparos e disparos pendentes."""
    from agent.automation.supervisor import build_supervisor

    return build_supervisor(settings).diagnose()


@router.get("/{automation_id}")
def get_automation(automation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    row = _load(session, automation_id)
    payload = _present(session, row)
    firings = list(
        session.scalars(
            select(AutomationFiringModel)
            .where(AutomationFiringModel.automation_id == row.id)
            .order_by(AutomationFiringModel.scheduled_for.desc())
            .limit(20)
        ).all()
    )
    payload["firings"] = [_present_firing(f) for f in firings]
    events = list(
        session.scalars(
            select(EventLogModel)
            .where(EventLogModel.event_type.like("automation.%"))
            .order_by(EventLogModel.created_at.desc())
            .limit(50)
        ).all()
    )
    payload["events"] = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "payload": e.payload_json or {},
        }
        for e in events
    ]
    return payload


@router.patch("/{automation_id}")
def update_automation(
    automation_id: uuid.UUID,
    body: AutomationPatch,
    session: Session = Depends(db_session),
) -> dict:
    _load(session, automation_id)
    try:
        row = _service(session).update(automation_id, body.changes)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return _present(session, row)


@router.delete("/{automation_id}")
def delete_automation(automation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    _load(session, automation_id)
    _service(session).delete(automation_id)
    return {"deleted": True, "id": str(automation_id)}


@router.post("/{automation_id}/enable")
def enable_automation(automation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    row = _load(session, automation_id)
    return _present(session, _service(session).set_state(row.id, AutomationState.ENABLED))


@router.post("/{automation_id}/suspend")
def suspend_automation(automation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    row = _load(session, automation_id)
    return _present(session, _service(session).set_state(row.id, AutomationState.SUSPENDED))


@router.post("/{automation_id}/disable")
def disable_automation(automation_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    row = _load(session, automation_id)
    return _present(session, _service(session).set_state(row.id, AutomationState.DISABLED))


@router.get("/{automation_id}/firings")
def list_firings(
    automation_id: uuid.UUID,
    limit: int = 50,
    session: Session = Depends(db_session),
) -> list[dict]:
    _load(session, automation_id)
    rows = list(
        session.scalars(
            select(AutomationFiringModel)
            .where(AutomationFiringModel.automation_id == automation_id)
            .order_by(AutomationFiringModel.scheduled_for.desc())
            .limit(max(1, min(limit, 500)))
        ).all()
    )
    return [_present_firing(row) for row in rows]


@router.post("/{automation_id}/run")
async def run_now(
    automation_id: uuid.UUID,
    wait: bool = False,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    """Executa uma vez, agora. Cria um disparo manual (chave própria)."""
    row = _load(session, automation_id)
    dispatcher = Dispatcher(session)
    firing = dispatcher.dispatch_manual(row, tag="manual")
    if firing is None:
        raise HTTPException(status_code=409, detail="não foi possível registrar o disparo")
    session.flush()
    if wait:
        executor = AutomationExecutor(session, settings)
        outcome = await executor.execute(firing)
        session.flush()
        return {"firing": _present_firing(firing), "outcome": outcome.__dict__}
    return {"firing": _present_firing(firing), "outcome": None}


@router.post("/{automation_id}/test")
async def test_automation(
    automation_id: uuid.UUID,
    body: TestIn | None = None,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    """Verifica a prontidão e, com `execute`, dispara um teste controlado."""
    payload = body or TestIn()
    row = _load(session, automation_id)
    project = session.get(ProjectModel, row.project_id)
    remote_row = session.get(ProjectRemoteModel, row.project_id)
    remote = dict(remote_row.config_json or {}) if remote_row else None
    resolver = DependencyResolver(
        settings=settings,
        project_root=project.root_path if project else None,
        remote=remote,
        target_kind=str(row.target_kind or TargetKind.LOCAL.value),
    )
    from agent.automation.contracts import DependencySpec

    specs = [DependencySpec.model_validate(item) for item in (row.dependencies_json or [])]
    check = await resolver.check_all(specs)
    result: dict[str, Any] = {"readiness": check.as_dict(), "executed": False}
    if payload.execute:
        dispatcher = Dispatcher(session)
        firing = dispatcher.dispatch_manual(row, tag="test")
        if firing is None:
            raise HTTPException(status_code=409, detail="não foi possível registrar o teste")
        session.flush()
        executor = AutomationExecutor(session, settings)
        outcome = await executor.execute(firing)
        session.flush()
        result["executed"] = True
        result["firing"] = _present_firing(firing)
        result["outcome"] = outcome.__dict__
    return result


@router.post("/{automation_id}/cancel")
def cancel_automation(
    automation_id: uuid.UUID, session: Session = Depends(db_session)
) -> dict:
    """Cancela os disparos pendentes da automação."""
    row = _load(session, automation_id)
    rows = list(
        session.scalars(
            select(AutomationFiringModel).where(
                AutomationFiringModel.automation_id == row.id,
                AutomationFiringModel.state.in_(
                    [
                        FiringState.PENDING.value,
                        FiringState.WAITING_DEPENDENCY.value,
                        FiringState.PREPARING.value,
                    ]
                ),
            )
        ).all()
    )
    for firing in rows:
        firing.state = FiringState.CANCELLED.value
        firing.error = "cancelado pelo usuário"
    session.flush()
    return {"cancelled": len(rows), "id": str(row.id)}
