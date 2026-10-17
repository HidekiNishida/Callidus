# src/agent/api/main.py — API HTTP do agente
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
from agent.mcp.manager import McpManager
from agent.orchestrator.runner import RunOrchestrator
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.services.attachments import attachment_note, materialize_attachments
from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    OperationAttemptModel,
)
from agent.tools.registry import ToolContext, build_default_registry
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.ollama import OllamaProvider
from agent.services.contract_service import ContractService
from agent.services.autonomous_worker import enable_autonomous_on_run, start_background_worker, stop_background_worker
from agent.services.metrics_service import MetricsService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import DependencyError, TaskNotFoundError, TaskService


def _web_dir(settings: Settings) -> Path | None:
    if settings.static_web_dir and settings.static_web_dir.is_dir():
        return settings.static_web_dir
    candidate = Path(__file__).resolve().parents[3] / "web" / "static"
    return candidate if candidate.is_dir() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    settings = read_settings()
    if settings.enable_background_worker:
        start_background_worker()
    try:
        yield
    finally:
        if settings.enable_background_worker:
            await stop_background_worker()


app = FastAPI(title="Agente de IA Local", version="0.5.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.5.0"}


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


@app.get("/tools")
def list_tools() -> dict:
    reg = build_default_registry()
    return {
        "tools": [s.model_dump() for s in reg.list_specs()],
    }


def _mcp_path(settings: Settings) -> Path:
    path = settings.mcp_config_path or settings.data_dir / "mcp.json"
    if not path.is_file():
        alt = Path(__file__).resolve().parents[3] / "data" / "mcp.example.json"
        return alt if alt.is_file() else path
    return path


@app.get("/mcp/servers")
def mcp_servers(settings: Settings = Depends(read_settings)) -> dict:
    mgr = McpManager(_mcp_path(settings))
    return {
        "servers": [s.__dict__ for s in mgr.list_servers()],
        "tools": mgr.list_tools(),
        "config_path": str(_mcp_path(settings)),
    }


@app.post("/mcp/discover")
async def mcp_discover(settings: Settings = Depends(read_settings)) -> dict:
    mgr = McpManager(_mcp_path(settings))
    return await mgr.discover()


@app.post("/mcp/call")
async def mcp_call(body: dict, settings: Settings = Depends(read_settings)) -> dict:
    tool_id = body.get("tool_id")
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id obrigatório")
    mgr = McpManager(_mcp_path(settings))
    return await mgr.call_tool(tool_id, body.get("arguments") or {})


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
    raw_meta = dict(body.metadata or {})
    raw_attachments = raw_meta.get("attachments") or []
    payload = body
    if raw_attachments:
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
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
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


@app.get("/projects/{project_id}/runs", response_model=list[ExecutionRunRead])
def list_runs(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[ExecutionRunRead]:
    try:
        runs = RunService(session).list_runs(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ExecutionRunRead.model_validate(r) for r in runs]


@app.post("/runs/{run_id}/step")
async def run_step(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    orch = RunOrchestrator(session, settings)
    try:
        return await orch.step(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/execute")
async def run_execute(
    run_id: uuid.UUID,
    max_steps: int = 50,
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict:
    orch = RunOrchestrator(session, settings)
    try:
        log = await orch.run_until_idle(run_id, max_steps=min(max_steps, settings.max_orchestrator_steps))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"steps": len(log), "log": log}


@app.post("/runs/{run_id}/pause")
def pause_run(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        run = RunService(session).pause_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(run.id), "status": run.status}


@app.post("/runs/{run_id}/autonomous/enable")
def enable_autonomous(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        run = enable_autonomous_on_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    cfg = run.config_json or {}
    return {"id": str(run.id), "autonomous": bool(cfg.get("autonomous"))}


@app.post("/runs/{run_id}/autonomous/disable")
def disable_autonomous(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=str(run_id))
    cfg = dict(run.config_json or {})
    cfg["autonomous"] = False
    run.config_json = cfg
    session.commit()
    return {"id": str(run.id), "autonomous": False}


@app.post("/projects/{project_id}/knowledge/reindex")
def kg_reindex(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stats = KnowledgeGraphService(session).reindex(project_id, project.root_path)
    session.commit()
    return stats


@app.get("/projects/{project_id}/knowledge/search")
def kg_search(
    project_id: uuid.UUID,
    q: str,
    limit: int = 20,
    session: Session = Depends(db_session),
) -> dict:
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    hits = KnowledgeGraphService(session).search(project_id, q, limit=min(limit, 100))
    return {"query": q, "hits": hits}


@app.get("/projects/{project_id}/knowledge/neighbors")
def kg_neighbors(
    project_id: uuid.UUID,
    ref: str,
    depth: int = 1,
    session: Session = Depends(db_session),
) -> dict:
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    nodes = KnowledgeGraphService(session).neighbors(project_id, ref, depth=min(depth, 3))
    return {"ref": ref, "nodes": nodes}


@app.get("/projects/{project_id}/metrics")
def project_metrics(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MetricsService(session).project_metrics(project_id)


@app.get("/tasks/{task_id}/context-snapshots")
def task_context_snapshots(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
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
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.get("/context-snapshots/{snapshot_id}")
def get_context_snapshot(snapshot_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
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
        "created_at": row.created_at.isoformat(),
    }


@app.get("/tasks/{task_id}/contract")
def get_task_contract(task_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    row = ContractService(session).get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="contrato não definido")
    return {
        "task_id": str(task_id),
        "inputs": row.inputs_json,
        "outputs": row.outputs_json,
        "invariants": row.invariants_json,
        "acceptance": row.acceptance_json,
    }


@app.put("/tasks/{task_id}/contract")
def upsert_task_contract(task_id: uuid.UUID, body: dict, session: Session = Depends(db_session)) -> dict:
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


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        run = RunService(session).cancel_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(run.id), "status": run.status}


@app.get("/config/ui-defaults")
def ui_defaults(settings: Settings = Depends(read_settings)) -> dict:
    return {
        "provider": settings.default_provider,
        "model_id": settings.default_model_id,
        "approve_risky_tools": True,
        "use_generic_template": settings.use_generic_decomposition_template,
        "ollama_base_url": settings.ollama_base_url,
    }


ACTION_COPY = {
    "started_planning": ("Planejando", "O orquestrador abriu o objetivo e registrou a memória canônica."),
    "decomposed": ("Dividindo o trabalho", "A tarefa foi quebrada em subtarefas menores e verificáveis."),
    "operation_ready": ("Pronta para executar", "Dependências ok. A operação pode rodar a ferramenta ou o modelo."),
    "planning_wait_children": ("Aguardando subtarefas", "O pai espera os filhos terminarem antes de consolidar."),
    "promoted_ready": ("Liberada", "Dependências satisfeitas; a tarefa passou para pronta."),
    "retry_ready": ("Nova tentativa", "A falha anterior foi recuperável. Vai tentar de novo."),
    "model_operation_invalid": ("Resposta inválida", "O modelo não devolveu o JSON esperado. Vai repetir."),
    "model_operation_failed": ("Escrita falhou", "A alteração proposta não foi gravada."),
    "tool_executed": ("Ferramenta", "A ferramenta rodou e o resultado foi registrado."),
    "verified_ok": ("Verificado", "O teste ou a checagem passou e gerou evidência."),
    "verify_failed": ("Verificação falhou", "O critério não passou. A tarefa volta para nova tentativa."),
    "verify_inconclusive": ("Verificação inconclusiva", "Não deu para decidir. A tarefa foi bloqueada."),
    "completed_without_verification": ("Concluída sem teste", "Não havia critério determinístico nesta operação."),
    "consolidated_parent": ("Consolidando", "Os resultados dos filhos sobem para a tarefa pai."),
    "blocked_contract": ("Bloqueada", "Falta um contrato obrigatório antes de continuar."),
    "blocked_loop": ("Loop detectado", "A mesma saída se repetiu. A execução parou para não girar à toa."),
    "blocked_attempts": ("Limite de tentativas", "Esgotou o orçamento de tentativas desta tarefa."),
    "blocked_decompose": ("Sem plano", "Não foi possível decompor o objetivo."),
    "blocked_no_metadata": ("Sem instrução", "A operação não diz qual ferramenta ou verificação usar."),
    "global_verify_reopen": ("Reabrindo", "A checagem global achou evidência faltando e reabriu tarefas."),
    "global_verify_failed": ("Objetivo incompleto", "Os critérios globais não foram atendidos."),
    "run_completed": ("Concluído", "O objetivo e as evidências foram aceitos."),
    "run_terminal": ("Encerrado", "Este run já estava finalizado."),
    "waiting": ("Aguardando", "Não há tarefa pronta neste instante."),
    "mcp_tool": ("MCP", "Uma ferramenta MCP local foi chamada."),
    "skipped_to_verify": ("Indo verificar", "A operação foi encaminhada para verificação."),
}


def _how_for_task(task) -> str:
    meta = task.metadata_json or {}
    if meta.get("tool"):
        return f"Ferramenta `{meta['tool']}` com argumentos locais."
    if meta.get("verification"):
        spec = meta["verification"]
        return f"Verificação determinística ({spec.get('type', 'check')})."
    if meta.get("model_operation"):
        return "O modelo local propõe a alteração; o runtime grava o arquivo e verifica."
    if meta.get("mcp_tool"):
        return f"Chamada MCP `{meta['mcp_tool']}`."
    return "O orquestrador escolhe o próximo passo pela máquina de estados, sem depender só do modelo."


@app.get("/projects/{project_id}/live")
def project_live(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tasks = TaskService(session).list_tasks(project_id)
    runs = RunService(session).list_runs(project_id)
    active = next((r for r in runs if r.status == "active"), None)
    focus = next(
        (
            t
            for t in tasks
            if t.status in {"RUNNING", "VERIFYING", "PLANNING", "RETRY_PENDING", "BLOCKED"}
        ),
        None,
    )
    stmt = (
        select(EventLogModel)
        .where(
            EventLogModel.project_id == project_id,
            EventLogModel.event_type == "orchestrator.action",
        )
        .order_by(EventLogModel.created_at.desc())
        .limit(1)
    )
    last = session.scalar(stmt)
    payload = (last.payload_json or {}) if last else {}
    action = payload.get("action") or "idle"
    title, how = ACTION_COPY.get(action, ("Em espera", "Nenhum passo recente."))
    pending = next((t for t in tasks if t.status == "PENDING"), None)
    if active and pending and focus is None and action in {"idle", "waiting"}:
        focus = pending
        title = f"Começando: {pending.title}"
        how = "A execução existe, mas o primeiro passo ainda não rodou. Ele será disparado agora."
    elif focus and action in {"idle", "waiting"}:
        title = f"{focus.status}: {focus.title}"
        how = _how_for_task(focus)
    elif focus and action not in {"run_completed", "run_terminal"}:
        how = f"{how} Tarefa atual: {focus.title}. {_how_for_task(focus)}"
    return {
        "project_id": str(project.id),
        "run": {
            "id": str(active.id),
            "status": active.status,
            "autonomous": bool((active.config_json or {}).get("autonomous")),
        }
        if active
        else None,
        "focus": {
            "id": str(focus.id),
            "title": focus.title,
            "status": focus.status,
            "objective": focus.objective,
        }
        if focus
        else None,
        "action": action,
        "headline": title,
        "how": how,
        "last_event_at": last.created_at.isoformat() if last else None,
        "model": {
            "provider": ((active or (runs[0] if runs else None)).config_json or {}).get("provider")
            if (active or runs)
            else None,
            "model_id": ((active or (runs[0] if runs else None)).config_json or {}).get("model_id")
            if (active or runs)
            else None,
            "autonomous": bool((active.config_json or {}).get("autonomous")) if active else False,
        },
        "operation": {
            "tool": (focus.metadata_json or {}).get("tool") if focus else None,
            "kind": focus.kind if focus else None,
        },
    }


@app.get("/projects/{project_id}/overview")
def project_overview(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tasks = TaskService(session).list_tasks(project_id)
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    runs = RunService(session).list_runs(project_id)
    active = next((r for r in runs if r.status == "active"), None)
    return {
        "project_id": str(project_id),
        "task_total": len(tasks),
        "tasks_by_status": by_status,
        "active_run_id": str(active.id) if active else None,
        "runs_total": len(runs),
        "root_path": project.root_path,
    }


@app.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, session: Session = Depends(db_session)) -> TaskRead:
    try:
        task = TaskService(session).get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskRead.model_validate(task)


@app.get("/projects/{project_id}/git-diff")
async def project_git_diff(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    reg = build_default_registry()
    ctx = ToolContext(project_root=project.root_path)
    return await reg.execute("git_diff", ctx, {})


@app.get("/tasks/{task_id}/attempts")
def task_attempts(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
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


@app.get("/tasks/{task_id}/evidences")
def task_evidences(task_id: uuid.UUID, session: Session = Depends(db_session)) -> list[dict]:
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


def _mount_web(settings: Settings) -> None:
    web = _web_dir(settings)
    if web is None:
        return
    assets = web / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_index():
        return FileResponse(web / "index.html")


def run() -> None:
    import uvicorn

    settings = read_settings()
    _mount_web(settings)
    uvicorn.run(
        "agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


_mount_web(read_settings())
