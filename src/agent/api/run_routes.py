"""
Arquivo: src/agent/api/run_routes.py
Nome: run_routes.py
Propósito: expor as execuções: iniciar, avançar, pausar, retomar, cancelar e medir.
Responsabilidade: camada de apresentação/transport — rotas de execução; delega o passo ao orquestrador.
Componentes: start_run, list_runs, run_step, run_execute, pause_run, resume_run, cancel_run, autônomo, métricas, aprovações granulares (list_run_approvals, approve_operation, deny_operation).
Dependências: agent.services.run_service, agent.services.autonomous_worker, agent.orchestrator.runner, agent.services.metrics_service.
Observações: o passo é o mesmo que o worker autônomo usa — a verificação não depende de quem executa.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.api.deps import db_session, read_settings
from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ExecutionRunRead
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.models import ExecutionRunModel
from agent.services.autonomous_worker import enable_autonomous_on_run
from agent.services.metrics_service import MetricsService
from agent.services.run_service import RunService

router = APIRouter()


@router.post("/projects/{project_id}/runs", response_model=ExecutionRunRead)
def start_run(
    project_id: uuid.UUID, body: ExecutionRunCreate, session: Session = Depends(db_session)
) -> ExecutionRunRead:
    """Inicia uma execução no projeto.

    Args:
        project_id: identificador do projeto que recebe a run.
        body: objetivo e opções da execução.
        session: sessão do banco da requisição.

    Returns:
        A run iniciada, serializada.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        run = RunService(session).start_run(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExecutionRunRead.model_validate(run)


@router.get("/projects/{project_id}/runs", response_model=list[ExecutionRunRead])
def list_runs(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[ExecutionRunRead]:
    """Lista as execuções de um projeto.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        As execuções do projeto, serializadas.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        runs = RunService(session).list_runs(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ExecutionRunRead.model_validate(r) for r in runs]


@router.post("/runs/{run_id}/step")
async def run_step(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    """Executa um único passo do orquestrador sobre a run.

    Args:
        run_id: identificador da run executada.
        session: sessão do banco da requisição.
        settings: configurações do processo.

    Returns:
        O resultado do passo, com a ação executada e a tarefa afetada.

    Raises:
        HTTPException: com status 404 quando a run não existe.

    Observações:
        É o mesmo passo do worker autônomo: a verificação não depende de quem executa.
    """
    orch = RunOrchestrator(session, settings)
    try:
        return await orch.step(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/execute")
async def run_execute(
    run_id: uuid.UUID,
    max_steps: int = 50,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    """Avança a run em vários passos até ela parar ou o orçamento acabar.

    Args:
        run_id: identificador da run executada.
        max_steps: número máximo de passos pedidos, limitado pelo teto de configuração.
        session: sessão do banco da requisição.
        settings: configurações do processo.

    Returns:
        A quantidade de passos executados e o registro de cada um.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    orch = RunOrchestrator(session, settings)
    try:
        log = await orch.run_until_idle(run_id, max_steps=min(max_steps, settings.max_orchestrator_steps))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"steps": len(log), "log": log}


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Pausa uma execução ativa.

    Args:
        run_id: identificador da run pausada.
        session: sessão do banco da requisição.

    Returns:
        O identificador da run e o novo estado.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    try:
        run = RunService(session).pause_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(run.id), "status": run.status}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: uuid.UUID, retry_blocked: bool = False, session: Session = Depends(db_session)) -> dict:
    """Retoma uma execução pausada ou bloqueada.

    Args:
        run_id: identificador da run retomada.
        retry_blocked: quando verdadeiro, repete também as tarefas que estavam bloqueadas.
        session: sessão do banco da requisição.

    Returns:
        O identificador da run e o novo estado.

    Raises:
        HTTPException: com status 404 quando a run não existe e com status 409 quando a retomada não é permitida no estado atual.
    """
    try:
        run = RunService(session).resume_run(run_id, retry_blocked=retry_blocked)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": str(run.id), "status": run.status}


@router.post("/runs/{run_id}/autonomous/enable")
def enable_autonomous(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Liga o modo autônomo da execução.

    Args:
        run_id: identificador da run alterada.
        session: sessão do banco da requisição.

    Returns:
        O identificador da run e a confirmação do modo autônomo.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    try:
        run = enable_autonomous_on_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    cfg = run.config_json or {}
    return {"id": str(run.id), "autonomous": bool(cfg.get("autonomous"))}


@router.post("/runs/{run_id}/autonomous/disable")
def disable_autonomous(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Desliga o modo autônomo da execução.

    Args:
        run_id: identificador da run alterada.
        session: sessão do banco da requisição.

    Returns:
        O identificador da run e a confirmação do modo manual.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=str(run_id))
    cfg = dict(run.config_json or {})
    cfg["autonomous"] = False
    run.config_json = cfg
    session.commit()
    return {"id": str(run.id), "autonomous": False}


class BudgetGrantBody(BaseModel):
    """Autorização explícita de mais tokens para uma execução."""

    tokens: int
    reason: str


@router.get("/runs/{run_id}/usage")
def run_usage(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
    purpose: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    task_id: str | None = None,
) -> dict:
    """Consumo acumulado da execução e a composição da chamada mais recente.

    Args:
        run_id: execução consultada.
        session: sessão do banco da requisição.
        purpose: filtra por finalidade.
        provider: filtra pelo provedor.
        model: filtra pelo modelo.
        agent: filtra pelo agente.
        task_id: filtra por tarefa.

    Returns:
        O demonstrativo derivado dos registros de inferência.

    Raises:
        HTTPException: com status 404 quando a execução não existe.
    """
    from agent.orchestrator.usage_report import build_usage_view

    view = build_usage_view(
        session,
        run_id=run_id,
        filters={
            "purpose": purpose or "",
            "provider": provider or "",
            "model": model or "",
            "agent": agent or "",
            "task_id": task_id or "",
        },
    )
    if view is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    return view


@router.post("/runs/{run_id}/budget-grant")
def run_budget_grant(
    run_id: uuid.UUID,
    body: BudgetGrantBody,
    session: Session = Depends(db_session),
) -> dict:
    """Autoriza mais tokens. A retomada sozinha não aumenta o teto.

    Args:
        run_id: execução que recebe a autorização.
        body: quantidade e motivo.
        session: sessão do banco da requisição.

    Returns:
        O teto resultante e a autorização gravada.

    Raises:
        HTTPException: com status 404 quando a execução não existe e 400 quando o pedido é inválido.
    """
    from agent.orchestrator.budget_gate import grant_budget

    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    try:
        result = grant_budget(session, run, tokens=body.tokens, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return result


@router.get("/runs/{run_id}/metrics")
def run_metrics(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Devolve as métricas de uma execução.

    Args:
        run_id: identificador da run consultada.
        session: sessão do banco da requisição.

    Returns:
        As métricas da run.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    metrics = MetricsService(session).run_metrics(run_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    return metrics


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Cancela uma execução.

    Args:
        run_id: identificador da run cancelada.
        session: sessão do banco da requisição.

    Returns:
        O identificador da run e o novo estado.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    try:
        run = RunService(session).cancel_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(run.id), "status": run.status}


class ApprovalDecisionBody(BaseModel):
    """Decisão sobre um pedido de aprovação.

    Atributos:
        note: observação opcional de quem decidiu (fica no registro auditável).
    """

    note: str | None = None


@router.get("/runs/{run_id}/approvals")
def list_run_approvals(run_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
    """Lista os pedidos de aprovação de operações arriscadas de uma execução.

    Args:
        run_id: execução consultada.
        session: sessão do banco da requisição.

    Returns:
        Os pedidos, com ferramenta, argumentos redigidos, risco, estado e datas.

    Raises:
        HTTPException: com status 404 quando a run não existe.
    """
    from agent.services.approval_service import ApprovalService, approval_view

    if session.get(ExecutionRunModel, run_id) is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    return [approval_view(row) for row in ApprovalService(session).list_for_run(run_id)]


def _decide_approval(approval_id: uuid.UUID, approve: bool, body: ApprovalDecisionBody | None, session: Session) -> dict:
    """Aplica a decisão e traduz os erros do serviço em respostas HTTP."""
    from agent.services.approval_service import ApprovalService, approval_view

    try:
        row = ApprovalService(session).decide(approval_id, approve=approve, note=body.note if body else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="pedido de aprovação não encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    run = session.get(ExecutionRunModel, row.run_id) if row.run_id else None
    return {**approval_view(row), "run_status": run.status if run is not None else None}


@router.post("/approvals/{approval_id}/approve")
def approve_operation(
    approval_id: uuid.UUID, body: ApprovalDecisionBody | None = None, session: Session = Depends(db_session)
) -> dict:
    """Aprova **uma** operação pendente; a execução que esperava por ela é retomada.

    Args:
        approval_id: pedido aprovado.
        body: observação opcional.
        session: sessão do banco da requisição.

    Returns:
        O pedido com a decisão e o estado atual da run.

    Raises:
        HTTPException: 404 quando o pedido não existe; 409 quando já foi decidido.
    """
    return _decide_approval(approval_id, True, body, session)


@router.post("/approvals/{approval_id}/deny")
def deny_operation(
    approval_id: uuid.UUID, body: ApprovalDecisionBody | None = None, session: Session = Depends(db_session)
) -> dict:
    """Nega uma operação pendente; a etapa continua bloqueada e o plano procura outro caminho.

    Args:
        approval_id: pedido negado.
        body: observação opcional.
        session: sessão do banco da requisição.

    Returns:
        O pedido com a decisão e o estado atual da run.

    Raises:
        HTTPException: 404 quando o pedido não existe; 409 quando já foi decidido.
    """
    return _decide_approval(approval_id, False, body, session)
