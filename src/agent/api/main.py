# src/agent/api/main.py — API HTTP do agente
from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.api.deps import db_session, get_engine, read_settings
from agent.config import Settings
from agent.domain.enums import MemoryKind, TaskStatus
from agent.domain.schemas import (
    EventRead,
    ExecutionRunCreate,
    ExecutionRunRead,
    MemoryCreate,
    MemoryRead,
    ProjectCreate,
    ProjectRead,
    TaskCreate,
    TaskDependencyCreate,
    TaskRead,
    TaskStatusUpdate,
)
from agent.domain.state_machine import InvalidTransitionError
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.ollama import OllamaProvider
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import DependencyError, TaskNotFoundError, TaskService
from agent.persistence.models import EventLogModel

app = FastAPI(title="Agente de IA Local", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    get_engine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/providers/ollama/models")
async def ollama_models(settings: Settings = Depends(read_settings)) -> dict:
    provider = OllamaProvider(settings.ollama_base_url)
    try:
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": "ollama", "models": models}


@app.get("/providers/llamacpp/models")
async def llamacpp_models(settings: Settings = Depends(read_settings)) -> dict:
    if not settings.llamacpp_base_url:
        raise HTTPException(status_code=400, detail="LLAMACPP_BASE_URL não configurada")
    provider = LlamaCppProvider(settings.llamacpp_base_url)
    try:
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": "llamacpp", "models": models}


@app.post("/projects", response_model=ProjectRead)
def create_project(body: ProjectCreate, session: Session = Depends(db_session)) -> ProjectRead:
    project = ProjectService(session).create_project(body)
    return ProjectRead.model_validate(project)


@app.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(db_session)) -> list[ProjectRead]:
    items = ProjectService(session).list_projects()
    return [ProjectRead.model_validate(p) for p in items]


@app.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, session: Session = Depends(db_session)) -> ProjectRead:
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectRead.model_validate(project)


@app.post("/projects/{project_id}/tasks", response_model=TaskRead)
def create_task(
    project_id: uuid.UUID, body: TaskCreate, session: Session = Depends(db_session)
) -> TaskRead:
    try:
        task = TaskService(session).create_task(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskRead.model_validate(task)


@app.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[TaskRead]:
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tasks = TaskService(session).list_tasks(project_id)
    return [TaskRead.model_validate(t) for t in tasks]


@app.patch("/tasks/{task_id}/status", response_model=TaskRead)
def update_task_status(
    task_id: uuid.UUID, body: TaskStatusUpdate, session: Session = Depends(db_session)
) -> TaskRead:
    try:
        task = TaskService(session).update_status(task_id, body)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskRead.model_validate(task)


@app.post("/tasks/{task_id}/dependencies")
def add_dependency(
    task_id: uuid.UUID, body: TaskDependencyCreate, session: Session = Depends(db_session)
) -> dict:
    try:
        row = TaskService(session).add_dependency(task_id, body)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": str(row.id), "task_id": str(row.task_id), "depends_on": str(row.depends_on_task_id)}


@app.post("/projects/{project_id}/runs", response_model=ExecutionRunRead)
def start_run(
    project_id: uuid.UUID, body: ExecutionRunCreate, session: Session = Depends(db_session)
) -> ExecutionRunRead:
    try:
        run = RunService(session).start_run(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExecutionRunRead.model_validate(run)


@app.get("/projects/{project_id}/events", response_model=list[EventRead])
def list_events(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[EventRead]:
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stmt = (
        select(EventLogModel)
        .where(EventLogModel.project_id == project_id)
        .order_by(EventLogModel.created_at.desc())
        .limit(200)
    )
    events = list(session.scalars(stmt).all())
    return [EventRead.model_validate(e) for e in events]


@app.post("/projects/{project_id}/memory", response_model=MemoryRead)
def add_memory(
    project_id: uuid.UUID, body: MemoryCreate, session: Session = Depends(db_session)
) -> MemoryRead:
    try:
        record = ProjectService(session).add_memory(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MemoryRead.model_validate(record)


@app.get("/projects/{project_id}/memory", response_model=list[MemoryRead])
def list_memory(
    project_id: uuid.UUID,
    kind: MemoryKind | None = None,
    session: Session = Depends(db_session),
) -> list[MemoryRead]:
    try:
        records = ProjectService(session).list_memory(project_id, kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [MemoryRead.model_validate(r) for r in records]


@app.post("/debug/chat/ollama")
async def debug_chat_ollama(
    body: dict,
    settings: Settings = Depends(read_settings),
) -> dict:
    """Endpoint de diagnóstico — não substitui o orquestrador."""
    model = body.get("model")
    prompt = body.get("prompt")
    if not model or not prompt:
        raise HTTPException(status_code=400, detail="model e prompt são obrigatórios")
    provider = OllamaProvider(settings.ollama_base_url)
    profile = ModelProfile(model_id=model)
    req = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        profile=profile,
    )
    try:
        resp = await provider.chat(req)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"content": resp.content}


def run() -> None:
    import uvicorn

    settings = read_settings()
    uvicorn.run(
        "agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
