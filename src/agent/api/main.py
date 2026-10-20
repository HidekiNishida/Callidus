"""
Arquivo: src/agent/api/main.py
Nome: main.py
Propósito: montar a aplicação HTTP do Callidus (rotas, ciclo de vida e interface estática).
Responsabilidade: camada de apresentação/transport — fachada da API; delega cada rota ao seu módulo.
Componentes: app, lifespan, montage da SPA, run().
Dependências: agent.api.*_routes, agent.api.deps, agent.services.autonomous_worker, agent.services.scheduler.
Observações: a ordem de inclusão dos roteadores é o que define a precedência das rotas com caminho ambíguo ficam por último.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.api.agent_routes import router as agent_router
from agent.api.automation_routes import router as automation_router
from agent.api.conversation_routes import router as conversation_router
from agent.api.deps import get_engine, read_settings
# Reexportado por compatibilidade: o import histórico `from agent.api.main import
# _mark_repeated_thought` continua funcionando depois da extração da visão ao vivo.
from agent.api.live_view import mark_repeated_thought as _mark_repeated_thought  # noqa: F401
from agent.api.observe_routes import router as observe_router
from agent.api.project_routes import router as project_router
from agent.api.provider_routes import router as provider_router
from agent.api.run_routes import router as run_router
from agent.api.system_routes import router as system_router
from agent.api.task_routes import router as task_router
from agent.brand import BRAND_NAME, BRAND_TAGLINE
from agent.config import Settings
from agent.services.autonomous_worker import start_background_worker, stop_background_worker
from agent.services.scheduler import start_scheduler, stop_scheduler

__all__ = ["app", "run"]


def _web_dir(settings: Settings) -> Path | None:
    """Pasta da interface estática, quando existe.

    Args:
        settings: configuração do processo (`static_web_dir` tem prioridade).

    Returns:
        O caminho da pasta da interface, ou `None` quando ela não existe.
    """
    if settings.static_web_dir and settings.static_web_dir.is_dir():
        return settings.static_web_dir
    candidate = Path(__file__).resolve().parents[3] / "web" / "static"
    return candidate if candidate.is_dir() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara e encerra o que depende do processo: banco, worker autônomo e agendador.

    Args:
        app: aplicação em execução.

    Yields:
        O controle da aplicação enquanto ela vive.
    """
    get_engine()
    settings = read_settings()
    if settings.enable_background_worker:
        start_background_worker()
    # O runtime de automações sobe junto com a API: com a interface aberta as
    # automações também funcionam. Quem garante o funcionamento **sem** a interface
    # é o supervisor nativo (`callidus-supervisor`), que usa o mesmo núcleo.
    if settings.enable_automation_supervisor:
        start_scheduler(settings)
    try:
        yield
    finally:
        if settings.enable_automation_supervisor:
            await stop_scheduler()
        if settings.enable_background_worker:
            await stop_background_worker()


app = FastAPI(
    title=BRAND_NAME,
    description=BRAND_TAGLINE,
    version="0.5.0",
    lifespan=lifespan,
)
# A ordem importa: cada roteador responde pelo seu prefixo; o resto (rotas com
# caminho variável) fica depois, para não capturar o caminho de outro grupo.
app.include_router(observe_router)
app.include_router(agent_router)
app.include_router(provider_router)
app.include_router(automation_router)
app.include_router(system_router)
app.include_router(project_router)
app.include_router(conversation_router)
app.include_router(task_router)
app.include_router(run_router)


_REVALIDATE = {"Cache-Control": "no-cache"}


class _RevalidatedStatic(StaticFiles):
    """Sem isso o navegador guarda a interface por heurística e mistura HTML antigo com módulos novos."""

    def file_response(self, *args, **kwargs):
        """Devolve o arquivo com o cabeçalho que proíbe o cache.

        Args:
            *args: argumentos repassados a `StaticFiles.file_response`.
            **kwargs: argumentos com nome repassados a `StaticFiles.file_response`.

        Returns:
            A resposta com `Cache-Control: no-cache`.
        """
        response = super().file_response(*args, **kwargs)
        response.headers.update(_REVALIDATE)
        return response


def _mount_web(settings: Settings) -> None:
    """Publica a interface estática e a página inicial da SPA.

    Args:
        settings: configuração do processo.
    """
    web = _web_dir(settings)
    if web is None:
        return
    assets = web / "assets"
    if assets.is_dir():
        app.mount("/assets", _RevalidatedStatic(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_index():
        """Devolve o `index.html` da interface.

        Returns:
            A resposta com o HTML da SPA.
        """
        return FileResponse(web / "index.html", headers=_REVALIDATE)


def run() -> None:
    """Sobe a API com o uvicorn (usado pelo comando `callidus-api`).

    Returns:
        Nada — o processo fica servindo até ser interrompido.
    """
    import uvicorn

    settings = read_settings()
    _mount_web(settings)
    uvicorn.run(
        "agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        timeout_graceful_shutdown=settings.shutdown_grace_seconds,
    )


_mount_web(read_settings())
