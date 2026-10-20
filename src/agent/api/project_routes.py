"""
Arquivo: src/agent/api/project_routes.py
Nome: project_routes.py
Propósito: expor os projetos, o computador remoto, o grafo de conhecimento e a memória do projeto.
Responsabilidade: camada de apresentação/transport — rotas de projeto; delega as regras aos serviços.
Componentes: CRUD de projeto, rotas de remoto, filesystem, grafo, métricas, visão ao vivo, eventos e memória.
Dependências: agent.services.project_service, agent.services.run_service, agent.knowledge.graph_service, agent.api.live_view.
Observações: os arquivos da pasta do projeto não são apagados ao remover um projeto.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.api.deps import db_session
from agent.api.live_view import ACTION_COPY, how_for_task, thought_trace
from agent.domain.enums import MemoryKind
from agent.domain.schemas import EventRead, MemoryCreate, MemoryRead, ProjectCreate, ProjectRead, ProjectUpdate
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.persistence.models import EventLogModel
from agent.services.fs_browse import browse_directories, create_directory, pick_folder_native
from agent.services.metrics_service import MetricsService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolContext, build_default_registry

router = APIRouter()


@router.post("/projects", response_model=ProjectRead)
def create_project(body: ProjectCreate, session: Session = Depends(db_session)) -> ProjectRead:
    """Cria um projeto.

    Args:
        body: dados do projeto a criar.
        session: sessão do banco da requisição.

    Returns:
        O projeto criado, serializado.
    """
    project = ProjectService(session).create_project(body)
    return ProjectRead.model_validate(project)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(db_session)) -> list[ProjectRead]:
    """Lista os projetos visíveis.

    Args:
        session: sessão do banco da requisição.

    Returns:
        Os projetos existentes, serializados.
    """
    items = ProjectService(session).list_projects()
    return [ProjectRead.model_validate(p) for p in items]


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, session: Session = Depends(db_session)) -> ProjectRead:
    """Detalha um projeto.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        O projeto, serializado.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectRead.model_validate(project)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, session: Session = Depends(db_session)
) -> ProjectRead:
    """Altera o nome ou a raiz de um projeto.

    Args:
        project_id: identificador do projeto alterado.
        body: campos a alterar.
        session: sessão do banco da requisição.

    Returns:
        O projeto já alterado, serializado.

    Raises:
        HTTPException: com status 404 quando o projeto não existe e com status 400 quando a raiz pedida é inválida.
    """
    try:
        project = ProjectService(session).update_project(
            project_id, name=body.name, root_path=body.root_path
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectRead.model_validate(project)


@router.delete("/projects/{project_id}")
def delete_project(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Remove o projeto e o que pertence a ele (conversas, tarefas, execuções, memória, grafo).
    Os arquivos da pasta do projeto não são apagados."""
    try:
        result = ProjectService(session).delete_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Nada pendurado deve sobrar; se sobrar, a resposta explica em vez de virar 500.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"não foi possível remover o projeto: {exc.orig}",
        ) from exc
    return result


class RemoteIn(BaseModel):
    """Configuração do computador remoto de um projeto.

    Atributos:
        host: endereço do host remoto.
        port: porta do serviço SSH.
        user: usuário da conexão, quando necessário.
        key_path: caminho da chave privada, quando a autenticação usar chave.
        root: diretório raiz do trabalho remoto.
        shell: tipo de shell do sistema remoto.
        timeout: tempo máximo de espera, em segundos, por comando remoto.
    """
    host: str
    port: int = 22
    user: str | None = None
    key_path: str | None = None
    root: str = "."
    shell: str = "posix"
    timeout: float = 120.0


@router.get("/projects/{project_id}/remote")
def get_project_remote(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Computador remoto configurado para o projeto (vazio quando o projeto é local)."""
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"remote": ProjectService(session).get_remote(project_id)}


@router.put("/projects/{project_id}/remote")
def set_project_remote(project_id: uuid.UUID, body: RemoteIn, session: Session = Depends(db_session)) -> dict:
    """Aponta o projeto para um computador remoto (Linux, macOS ou Windows) via SSH."""
    from agent.remote.ssh import RemoteConfig

    try:
        config = RemoteConfig(**body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"configuração remota inválida: {exc}") from exc
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    saved = ProjectService(session).set_remote(project_id, config.model_dump())
    return {"remote": saved}


@router.delete("/projects/{project_id}/remote")
def clear_project_remote(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Volta o projeto para a máquina local."""
    removed = ProjectService(session).clear_remote(project_id)
    return {"remote": None, "removed": removed}


@router.post("/projects/{project_id}/remote/test")
async def test_project_remote(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Testa a conexão com o computador remoto configurado."""
    from agent.remote.ssh import RemoteConfig, RemoteError, SshTransport

    config = ProjectService(session).get_remote(project_id)
    if not config:
        raise HTTPException(status_code=400, detail="o projeto não tem computador remoto configurado")
    try:
        transport = SshTransport(RemoteConfig(**config))
        result = await transport.check()
    except RemoteError as exc:
        return {"ok": False, "detail": str(exc)}
    except Exception as exc:  # pragma: no cover - falha inesperada
        return {"ok": False, "detail": str(exc)}
    return {"ok": bool(result.get("ok")), "detail": result.get("system", ""), "exit_code": result.get("exit_code")}


class FsMkdirIn(BaseModel):
    """Pedido de criação de uma pasta no sistema de arquivos.

    Atributos:
        path: pasta onde a nova pasta será criada; quando ausente, usa a pasta atual.
        name: nome da nova pasta.
    """
    path: str | None = None
    name: str


@router.get("/fs/browse")
def fs_browse(path: str | None = None) -> dict:
    """Lista as pastas acessíveis a partir de um caminho.

    Args:
        path: caminho inicial da navegação; quando ausente, começa na raiz permitida.

    Returns:
        As pastas encontradas e o novo caminho de navegação.

    Raises:
        HTTPException: com status 400 quando o caminho está fora do alcance permitido.
    """
    try:
        return browse_directories(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fs/mkdir")
def fs_mkdir(body: FsMkdirIn) -> dict:
    """Cria uma pasta dentro do alcance permitido (para o seletor de pasta do projeto)."""
    try:
        return create_directory(body.path, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fs/pick-folder")
def fs_pick_folder() -> dict:
    """Abre o seletor nativo de pasta do sistema operacional.

    Returns:
        O caminho da pasta escolhida, ou `None` quando o usuário cancela.

    Raises:
        HTTPException: com status 400 quando o seletor não está disponível neste ambiente.
    """
    try:
        return {"path": pick_folder_native()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/knowledge/reindex")
def kg_reindex(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Reindexa o grafo de conhecimento do projeto.

    Args:
        project_id: identificador do projeto reindexado.
        session: sessão do banco da requisição.

    Returns:
        As estatísticas da reindexação.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stats = KnowledgeGraphService(session).reindex(project_id, project.root_path)
    session.commit()
    return stats


@router.get("/projects/{project_id}/knowledge/search")
def kg_search(
    project_id: uuid.UUID,
    q: str,
    limit: int = 20,
    session: Session = Depends(db_session),
) -> dict:
    """Busca nós no grafo de conhecimento do projeto.

    Args:
        project_id: identificador do projeto consultado.
        q: texto da busca.
        limit: número máximo de resultados, limitado a 100.
        session: sessão do banco da requisição.

    Returns:
        A consulta feita e os nós encontrados.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    hits = KnowledgeGraphService(session).search(project_id, q, limit=min(limit, 100))
    return {"query": q, "hits": hits}


@router.get("/projects/{project_id}/knowledge/neighbors")
def kg_neighbors(
    project_id: uuid.UUID,
    ref: str,
    depth: int = 1,
    session: Session = Depends(db_session),
) -> dict:
    """Lista os vizinhos de um nó do grafo de conhecimento.

    Args:
        project_id: identificador do projeto consultado.
        ref: identificador do nó de referência.
        depth: profundidade da varredura, limitada a 3.
        session: sessão do banco da requisição.

    Returns:
        A referência e os nós vizinhos encontrados.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    nodes = KnowledgeGraphService(session).neighbors(project_id, ref, depth=min(depth, 3))
    return {"ref": ref, "nodes": nodes}


@router.get("/projects/{project_id}/metrics")
def project_metrics(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Devolve as métricas do projeto.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        As métricas calculadas sobre as tarefas e execuções do projeto.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MetricsService(session).project_metrics(project_id)


@router.get("/projects/{project_id}/live")
def project_live(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Devolve a visão ao vivo do projeto: o que está rodando e o que vem a seguir.

    Args:
        project_id: identificador do projeto observado.
        session: sessão do banco da requisição.

    Returns:
        A run ativa, a tarefa em foco, a última ação do orquestrador e a linha do tempo de pensamentos.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.

    Observações:
        Quando existe run ativa sem primeiro passo executado, a tarefa pendente é apresentada como foco, para que a interface não mostre um projeto paradoxalmente parado.
    """
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
        how = how_for_task(focus)
    elif focus and action not in {"run_completed", "run_terminal"}:
        how = f"{how} Tarefa atual: {focus.title}. {how_for_task(focus)}"
    thoughts = thought_trace(session, project_id, tasks)
    busy = {"PENDING", "PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"}
    thinking = bool(active and focus and focus.status in busy)
    return {
        "project_id": str(project.id),
        "thoughts": thoughts,
        "thinking": thinking,
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


@router.get("/projects/{project_id}/overview")
def project_overview(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Devolve o resumo do projeto: tarefas por estado, runs e raiz.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        O total de tarefas, a contagem por estado, a run ativa e o caminho raiz.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
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


@router.get("/projects/{project_id}/git-diff")
async def project_git_diff(project_id: uuid.UUID, session: Session = Depends(db_session)) -> dict:
    """Devolve o diff do Git do projeto, calculado pela ferramenta de diff.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        O resultado da ferramenta `git_diff` executada na raiz do projeto.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        project = ProjectService(session).get_project(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    reg = build_default_registry()
    ctx = ToolContext(project_root=project.root_path)
    return await reg.execute("git_diff", ctx, {})


@router.get("/projects/{project_id}/events", response_model=list[EventRead])
def list_events(project_id: uuid.UUID, session: Session = Depends(db_session)) -> list[EventRead]:
    """Lista os eventos registrados do projeto, do mais recente para o mais antigo.

    Args:
        project_id: identificador do projeto consultado.
        session: sessão do banco da requisição.

    Returns:
        Até duzentos eventos do projeto, serializados.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
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


@router.post("/projects/{project_id}/memory", response_model=MemoryRead)
def add_memory(
    project_id: uuid.UUID, body: MemoryCreate, session: Session = Depends(db_session)
) -> MemoryRead:
    """Registra uma memória do projeto.

    Args:
        project_id: identificador do projeto que recebe a memória.
        body: conteúdo e tipo da memória.
        session: sessão do banco da requisição.

    Returns:
        A memória registrada, serializada.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        record = ProjectService(session).add_memory(project_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MemoryRead.model_validate(record)


@router.get("/projects/{project_id}/memory", response_model=list[MemoryRead])
def list_memory(
    project_id: uuid.UUID,
    kind: MemoryKind | None = None,
    session: Session = Depends(db_session),
) -> list[MemoryRead]:
    """Lista as memórias do projeto, opcionalmente filtradas por tipo.

    Args:
        project_id: identificador do projeto consultado.
        kind: quando informado, restringe a listagem ao tipo de memória.
        session: sessão do banco da requisição.

    Returns:
        As memórias do projeto, serializadas.

    Raises:
        HTTPException: com status 404 quando o projeto não existe.
    """
    try:
        records = ProjectService(session).list_memory(project_id, kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [MemoryRead.model_validate(r) for r in records]
