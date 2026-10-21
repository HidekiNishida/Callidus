"""
Arquivo: src/agent/api/task_routes.py
Nome: task_routes.py
Propósito: expor as tarefas, suas dependências, contratos, tentativas, evidências e snapshots de contexto.
Responsabilidade: camada de apresentação/transport — rotas de tarefa; delega as regras ao serviço.
Componentes: criação e leitura de tarefas, status, dependências, contrato, contexto, tentativas e evidências.
Dependências: agent.services.task_service, agent.services.contract_service, agent.orchestrator.resume, agent.api.presenters.
Observações: a transição de status é validada pela máquina de estados — o conflito vira 409, não 500.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.api.deps import db_session
from agent.api.presenters import present_task
from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate, TaskCreate, TaskDependencyCreate, TaskRead, TaskStatusUpdate
from agent.domain.state_machine import InvalidTransitionError
from agent.i18n.locale import detect_language
from agent.memory.store import extract_memory_request
from agent.orchestrator.resume import resume_root
from agent.persistence.models import ContextSnapshotModel, EvidenceModel, OperationAttemptModel
from agent.services.attachments import attachment_note, materialize_attachments
from agent.services.contract_service import ContractService
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService
from agent.services.task_service import DependencyError, TaskNotFoundError, TaskService

router = APIRouter()


@router.post("/projects/{project_id}/tasks", response_model=TaskRead)
def create_task(
    project_id: uuid.UUID, body: TaskCreate, session: Session = Depends(db_session)
) -> TaskRead:
    """Cria uma tarefa no projeto, materializando anexos e memórias pedidas no objetivo.

    Args:
        project_id: identificador do projeto que recebe a tarefa.
        body: objetivo, título, metadados e anexos da tarefa.
        session: sessão do banco da requisição.

    Returns:
        A tarefa criada, serializada.

    Raises:
        HTTPException: com status 404 quando o projeto não existe e com status 400 quando os dados da tarefa são inválidos.

    Observações:
        Anexos viram arquivos dentro do projeto e entram no objetivo como nota; a memória lembrada no texto é gravada como memória canônica ou contextual.
    """
    raw_meta = dict(body.metadata or {})
    raw_attachments = raw_meta.get("attachments") or []
    locale = detect_language(body.objective)
    raw_meta.setdefault("locale", locale)
    cleaned = dict(raw_meta)
    cleaned.pop("attachments", None)
    payload = body.model_copy(update={"metadata": cleaned or None})
    try:
        project = ProjectService(session).get_project(project_id)
        task = TaskService(session).create_task(project_id, payload)
        if raw_attachments:
            refs = materialize_attachments(project.root_path, str(task.id), raw_attachments)
            meta = dict(task.metadata_json or {})
            meta["attachments"] = refs
            task.metadata_json = meta
            task.objective = f"{task.objective.rstrip()}\n\n{attachment_note(refs)}"
            session.flush()
        if task.conversation_id is not None:
            ConversationService(session).touch_title(task.conversation_id, task.title, locale)
        remembered = extract_memory_request(body.objective)
        if remembered:
            scope, fact = remembered
            ProjectService(session).add_memory(
                project_id,
                MemoryCreate(
                    kind=MemoryKind.CANONICAL if scope == "project" else MemoryKind.CONTEXTUAL,
                    title=(fact[:80] or "Memória"),
                    content=fact,
                    task_id=task.id,
                    conversation_id=None if scope == "project" else task.conversation_id,
                ),
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return present_task(session, task)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[TaskRead]:
    """Lista as tarefas de um projeto.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        As tarefas do projeto, serializadas.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tasks = TaskService(session).list_tasks(project_id)
    return [present_task(session, t) for t in tasks]


@router.patch("/tasks/{task_id}/status", response_model=TaskRead)
def update_task_status(
    task_id: uuid.UUID, body: TaskStatusUpdate, session: Session = Depends(db_session)
) -> TaskRead:
    """Move a tarefa para um novo estado, validando a transição.

    Args:
        task_id: identificador da tarefa movida.
        body: novo estado e o motivo da mudança.
        session: sessão do banco da requisição.

    Returns:
        A tarefa já movida, serializada.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe e com status 409 quando a transição pedida é inválida.
    """
    try:
        task = TaskService(session).update_status(task_id, body)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskRead.model_validate(task)


@router.post("/tasks/{task_id}/dependencies")
def add_dependency(
    task_id: uuid.UUID, body: TaskDependencyCreate, session: Session = Depends(db_session)
) -> dict:
    """Registra que uma tarefa depende de outra.

    Args:
        task_id: identificador da tarefa que depende.
        body: tarefa de dependência.
        session: sessão do banco da requisição.

    Returns:
        A dependência criada, com a tarefa e a dependência identificadas.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe e com status 400 quando a dependência é inválida.
    """
    try:
        row = TaskService(session).add_dependency(task_id, body)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": str(row.id), "task_id": str(row.task_id), "depends_on": str(row.depends_on_task_id)}


@router.get("/tasks/{task_id}/context-snapshots")
def task_context_snapshots(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
    """Lista os snapshots de contexto de uma tarefa, do mais recente para o mais antigo.

    Args:
        task_id: identificador da tarefa consultada.
        session: sessão do banco da requisição.

    Returns:
        Até vinte snapshots, com os tokens estimados, os componentes e as referências usadas.
    """
    stmt = (
        select(ContextSnapshotModel)
        .where(ContextSnapshotModel.task_id == task_id)
        .order_by(ContextSnapshotModel.created_at.desc())
        .limit(20)
    )
    rows = list(session.scalars(stmt).all())
    return [
        {
            "id": str(r.id),
            "estimated_tokens": r.estimated_tokens,
            "components": r.components_json,
            "strategy_notes": r.strategy_notes_json,
            "refs": r.refs_json,
            "categories": r.categories_json,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/context-snapshots/{snapshot_id}")
def get_context_snapshot(snapshot_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Detalha um snapshot de contexto.

    Args:
        snapshot_id: identificador do snapshot consultado.
        session: sessão do banco da requisição.

    Returns:
        O snapshot com seus componentes, notas de estratégia e referências.

    Raises:
        HTTPException: com status 404 quando o snapshot não existe.
    """
    row = session.get(ContextSnapshotModel, snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail=str(snapshot_id))
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "task_id": str(row.task_id) if row.task_id else None,
        "run_id": str(row.run_id) if row.run_id else None,
        "estimated_tokens": row.estimated_tokens,
        "components": row.components_json,
        "strategy_notes": row.strategy_notes_json,
        "refs": row.refs_json,
        "categories": row.categories_json,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/tasks/{task_id}/usage")
def task_usage(
    task_id: uuid.UUID,
    session: Session = Depends(db_session),
    purpose: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
) -> dict:
    """Demonstrativo de contexto e de consumo da tarefa.

    Args:
        task_id: tarefa consultada.
        session: sessão do banco da requisição.
        purpose: filtra as inferências por finalidade.
        provider: filtra pelo provedor.
        model: filtra pelo modelo.
        agent: filtra pelo agente.

    Returns:
        A janela da última chamada e o consumo acumulado da execução, em campos separados.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe.
    """
    from agent.orchestrator.usage_report import build_usage_view
    from agent.persistence.models import TaskModel

    if session.get(TaskModel, task_id) is None:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    view = build_usage_view(
        session,
        task_id=task_id,
        filters={"purpose": purpose or "", "provider": provider or "", "model": model or "", "agent": agent or ""},
    )
    if view is None:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    return view


@router.get("/tasks/{task_id}/memory")
def task_memory(
    task_id: uuid.UUID,
    session: Session = Depends(db_session),
    kind: str | None = None,
    q: str | None = None,
    file: str | None = None,
    state: str | None = None,
    include_children: bool = False,
) -> list[dict]:
    """Recupera a memória persistida da tarefa, sem devolver o histórico do modelo.

    Args:
        task_id: tarefa consultada.
        session: sessão do banco.
        kind: tipo do registro.
        q: assunto procurado no título, no resumo ou no conteúdo.
        file: arquivo ou símbolo procurado.
        state: estado mencionado no registro.
        include_children: quando verdadeiro, inclui as filhas diretas.

    Returns:
        Os registros encontrados, com resumo e referência. O conteúdo longo de artefato
        permanece no campo `content`, que para o nível 3 é a referência e o diagnóstico.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe.
    """
    from agent.memory.operational import recall
    from agent.persistence.models import TaskModel

    task = session.get(TaskModel, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    rows = recall(
        session,
        project_id=task.project_id,
        task_id=None if include_children else task.id,
        parent_task_id=task.id if include_children else None,
        kind=kind,
        text=q,
        file=file,
        state=state,
    )
    return [
        {
            "id": str(row.id),
            "task_id": str(row.task_id) if row.task_id else None,
            "kind": row.kind,
            "title": row.title,
            "summary": row.summary,
            "outline": row.outline_json,
            "refs": row.source_refs_json,
            "version": row.version,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/tasks/{task_id}/contract")
def get_task_contract(task_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Contrato da tarefa. Sem contrato, devolve os campos vazios (estado normal, não erro)."""
    row = ContractService(session).get(task_id)
    if row is None:
        return {"task_id": str(task_id), "inputs": None, "outputs": None, "invariants": None, "acceptance": None}
    return {
        "task_id": str(task_id),
        "inputs": row.inputs_json,
        "outputs": row.outputs_json,
        "invariants": row.invariants_json,
        "acceptance": row.acceptance_json,
    }


@router.put("/tasks/{task_id}/contract")
def upsert_task_contract(task_id: uuid.UUID, body: dict, session: Session = Depends(db_session)) -> dict:
    """Grava ou atualiza o contrato da tarefa, relatando o impacto da mudança.

    Args:
        task_id: identificador da tarefa cujo contrato é gravado.
        body: campos do contrato — entradas, saídas, invariantes e aceitação.
        session: sessão do banco da requisição.

    Returns:
        O contrato gravado e o impacto da mudança sobre as tarefas dependentes.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe.
    """
    try:
        out = ContractService(session).upsert_with_impact(
            task_id,
            inputs=body.get("inputs"),
            outputs=body.get("outputs"),
            invariants=body.get("invariants"),
            acceptance=body.get("acceptance"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return out


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, session: Session = Depends(db_session)) -> TaskRead:
    """Detalha uma tarefa.

    Args:
        task_id: identificador da tarefa consultada.
        session: sessão do banco da requisição.

    Returns:
        A tarefa, serializada.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe.
    """
    try:
        task = TaskService(session).get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return present_task(session, task)


class ResumeBody(BaseModel):
    """Opções do pedido de retomada de uma tarefa.

    Atributos:
        apply: quando verdadeiro, aplica o plano de retomada; quando falso, apenas devolve o plano.
    """
    apply: bool = False


@router.post("/tasks/{task_id}/resume-brief")
def task_resume_brief(
    task_id: uuid.UUID, body: ResumeBody, session: Session = Depends(db_session)
) -> dict:
    """Devolve — e opcionalmente aplica — o plano de retomada de uma tarefa.

    Args:
        task_id: identificador da tarefa retomada.
        body: indica se o plano deve ser aplicado.
        session: sessão do banco da requisição.

    Returns:
        O plano de retomada com o que já foi feito e o que falta.

    Raises:
        HTTPException: com status 404 quando a tarefa não existe.
    """
    try:
        return resume_root(session, task_id, apply=body.apply)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/attempts")
def task_attempts(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
    """Lista as tentativas de operação de uma tarefa, da mais recente para a mais antiga.

    Args:
        task_id: identificador da tarefa consultada.
        session: sessão do banco da requisição.

    Returns:
        As tentativas com o provedor usado, o resultado e o erro de cada uma.
    """
    stmt = (
        select(OperationAttemptModel)
        .where(OperationAttemptModel.task_id == task_id)
        .order_by(OperationAttemptModel.created_at.desc())
    )
    rows = list(session.scalars(stmt).all())
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "provider": r.provider,
            "success": r.success,
            "error": r.error_message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/tasks/{task_id}/evidences")
def task_evidences(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
    """Lista as evidências registradas para uma tarefa.

    Args:
        task_id: identificador da tarefa consultada.
        session: sessão do banco da requisição.

    Returns:
        As evidências com o verificador, o resultado e o resumo de cada uma.
    """
    stmt = select(EvidenceModel).where(EvidenceModel.task_id == task_id)
    rows = list(session.scalars(stmt).all())
    return [
        {
            "id": str(r.id),
            "verifier": r.verifier,
            "passed": r.passed,
            "summary": r.summary,
        }
        for r in rows
    ]
