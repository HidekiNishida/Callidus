"""
Arquivo: src/agent/api/system_routes.py
Nome: system_routes.py
Propósito: expor saúde, provedores, ferramentas, MCP e preferências da interface.
Responsabilidade: camada de apresentação/transport — rotas de diagnóstico e configuração do processo.
Componentes: health, list_providers, provider_models, provider_health, list_tools, tools_availability, tools_families, system_diagnose, list_skills, rotas de MCP, ui_defaults.
Dependências: agent.providers.*, agent.mcp.manager, agent.tools.registry, agent.config.Settings.
Observações: nenhuma credencial é exposta — só a origem declarada da chave.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from agent.api.deps import read_settings
from agent.config import Settings
from agent.mcp.manager import McpManager
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.ollama import OllamaProvider
from agent.tools.registry import build_default_registry

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Informa que o processo está vivo.

    Returns:
        O estado do serviço e a versão do Callidus.
    """
    return {"status": "ok", "version": "0.5.0"}


@router.get("/providers/ollama/models")
async def ollama_models(settings: Settings = Depends(read_settings)) -> dict:
    """Lista os modelos disponíveis no servidor Ollama.

    Args:
        settings: configurações do processo.

    Returns:
        O nome do provedor e a lista de modelos.

    Raises:
        HTTPException: com status 503 quando o servidor Ollama não responde.
    """
    provider = OllamaProvider(settings.ollama_base_url)
    try:
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": "ollama", "models": models}


@router.get("/providers/llamacpp/models")
async def llamacpp_models(settings: Settings = Depends(read_settings)) -> dict:
    """Lista os modelos disponíveis no servidor llama.cpp.

    Args:
        settings: configurações do processo.

    Returns:
        O nome do provedor e a lista de modelos.

    Raises:
        HTTPException: com status 503 quando o servidor llama.cpp não responde.
    """
    provider = LlamaCppProvider(settings.llamacpp_base_url)
    try:
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": "llamacpp", "models": models}


@router.get("/providers")
async def list_providers(settings: Settings = Depends(read_settings)) -> dict:
    """Provedores disponíveis: os do arquivo de configuração mais os embutidos. Nenhuma
    credencial é exposta — só a origem declarada da chave."""
    from agent.providers.registry import catalog_for_settings

    catalog = catalog_for_settings(settings)
    entries: list[dict] = []
    for name in catalog.names():
        spec = catalog.get(name)
        if spec is None:  # pragma: no cover - defensive
            continue
        entries.append(
            {
                "name": name,
                "type": spec.kind,
                "base_url": spec.base_url,
                "model": spec.model,
                "api_key_source": (
                    "env"
                    if spec.api_key_env
                    else ("file" if spec.api_key_file else ("inline" if spec.api_key else None))
                ),
                "source": "config",
            }
        )
    for name, kind, base_url in (
        ("ollama", "ollama", settings.ollama_base_url),
        ("llamacpp", "llamacpp", settings.llamacpp_base_url),
        ("mock", "mock", None),
    ):
        if any(entry["name"] == name for entry in entries):
            continue
        entries.append({"name": name, "type": kind, "base_url": base_url, "model": None, "api_key_source": None, "source": "builtin"})
    return {
        "default_provider": catalog.default_provider or settings.default_provider,
        "providers": entries,
    }


def provider_by_name(name: str, settings: Settings):
    """Constrói o provedor pedido ou responde com o erro correspondente.

    Args:
        name: nome do provedor.
        settings: configurações do processo.

    Returns:
        O provedor pronto para uso.

    Raises:
        HTTPException: com status 400 quando a configuração do provedor é inválida e com status 404 quando o provedor não existe.
    """
    from agent.providers.base import ProviderConfigError
    from agent.providers.registry import build_provider_by_name

    try:
        provider = build_provider_by_name(name, settings)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provedor '{name}' não encontrado")
    return provider


@router.get("/providers/{name}/models")
async def provider_models(name: str, settings: Settings = Depends(read_settings)) -> dict:
    """Lista os modelos de um provedor configurado.

    Args:
        name: nome do provedor.
        settings: configurações do processo.

    Returns:
        O nome do provedor e a lista de modelos.

    Raises:
        HTTPException: com status 503 quando o provedor não responde e com 400 ou 404 quando o provedor não pode ser construído.
    """
    provider = provider_by_name(name, settings)
    try:
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": name, "models": models}


@router.get("/providers/{name}/health")
async def provider_health(name: str, settings: Settings = Depends(read_settings)) -> dict:
    """Diagnóstico de conectividade: sempre 200 com o resultado (ok true/false)."""
    provider = provider_by_name(name, settings)
    health = await provider.health_check()
    return health.model_dump()


@router.get("/tools")
def list_tools() -> dict:
    """Lista as ferramentas disponíveis para o agente.

    Returns:
        A especificação de cada ferramenta registrada.
    """
    reg = build_default_registry()
    return {
        "tools": [s.model_dump() for s in reg.list_specs()],
    }


@router.get("/tools/availability")
def tools_availability() -> dict:
    """Situação de disponibilidade de cada ferramenta: o que falta para ela rodar.

    Returns:
        Uma lista com a ferramenta, a família, a disponibilidade e as dicas.
    """
    reg = build_default_registry()
    report = reg.availability_report()
    return {
        "count": len(report),
        "available": sum(1 for item in report if item["available"]),
        "missing": [item for item in report if not item["available"]],
        "tools": report,
    }


@router.get("/tools/families")
def tools_families(settings: Settings = Depends(read_settings)) -> dict:
    """Famílias de ferramentas habilitadas e como a política está configurada.

    Returns:
        As famílias habilitadas, as desligadas e o piso de risco automático.
    """
    from agent.tools.catalog import enabled_families
    from agent.tools.policy import ALLOW, DENY, tool_policy

    policy = tool_policy(settings)
    enabled = enabled_families(settings)
    return {
        "enabled_families": sorted(enabled) if enabled is not None else ["todas"],
        "disabled_families": sorted(policy.disabled_families),
        "max_auto_risk": policy.max_auto_risk.value,
        "always_allowed": sorted(name for name, rule in policy.tool_rules.items() if rule == ALLOW),
        "never_allowed": sorted(name for name, rule in policy.tool_rules.items() if rule == DENY),
    }


@router.get("/system/diagnose")
def system_diagnose() -> dict:
    """Diagnostica o ambiente: sistema, sessão gráfica, permissões e dependências.

    Returns:
        O diagnóstico completo, com as verificações que falharam.
    """
    from agent.system.platform_info import describe_system, diagnose_permissions, platform_summary
    from agent.tools.availability import environment_report

    return {
        "system": describe_system(),
        "permissions": diagnose_permissions(),
        "summary": platform_summary(),
        "environment": environment_report(),
    }


@router.get("/skills")
def list_skills() -> dict:
    """Skills instaladas, com versão, estado e origem.

    Returns:
        A lista de skills instaladas e o caminho do repositório de skills.
    """
    from agent.skills.authoring import SkillStore
    from agent.skills.discovery import installed_skills_dir

    store = SkillStore(installed_skills_dir())
    skills = store.list_installed()
    return {
        "root": str(store.root),
        "count": len(skills),
        "skills": [item.as_dict() for item in skills],
    }


def mcp_path(settings: Settings) -> Path:
    """Resolve o caminho do arquivo de configuração do MCP.

    Args:
        settings: configurações do processo.

    Returns:
        O arquivo de configuração configurado, ou o exemplo do repositório quando o configurado ainda não existe.
    """
    path = settings.mcp_config_path or settings.data_dir / "mcp.json"
    if not path.is_file():
        alt = Path(__file__).resolve().parents[3] / "data" / "mcp.example.json"
        return alt if alt.is_file() else path
    return path


@router.get("/mcp/servers")
def mcp_servers(settings: Settings = Depends(read_settings)) -> dict:
    """Lista os servidores MCP configurados e as ferramentas que eles oferecem.

    Args:
        settings: configurações do processo.

    Returns:
        Os servidores, as ferramentas e o caminho do arquivo de configuração.
    """
    mgr = McpManager(mcp_path(settings))
    return {
        "servers": [s.__dict__ for s in mgr.list_servers()],
        "tools": mgr.list_tools(),
        "config_path": str(mcp_path(settings)),
    }


@router.post("/mcp/discover")
async def mcp_discover(settings: Settings = Depends(read_settings)) -> dict:
    """Descobre as ferramentas dos servidores MCP configurados.

    Args:
        settings: configurações do processo.

    Returns:
        O resultado da descoberta, com as ferramentas encontradas em cada servidor.
    """
    mgr = McpManager(mcp_path(settings))
    return await mgr.discover()


@router.post("/mcp/call")
async def mcp_call(body: dict, settings: Settings = Depends(read_settings)) -> dict:
    """Chama uma ferramenta MCP.

    Args:
        body: corpo da requisição, com `tool_id` e os argumentos da chamada.
        settings: configurações do processo.

    Returns:
        O resultado devolvido pela ferramenta MCP.

    Raises:
        HTTPException: com status 400 quando o `tool_id` não vem na requisição.
    """
    tool_id = body.get("tool_id")
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id obrigatório")
    mgr = McpManager(mcp_path(settings))
    return await mgr.call_tool(tool_id, body.get("arguments") or {})


@router.get("/config/ui-defaults")
def ui_defaults(settings: Settings = Depends(read_settings)) -> dict:
    """Devolve as preferências que a interface usa como ponto de partida.

    Args:
        settings: configurações do processo.

    Returns:
        O provedor, o modelo e os endereços dos servidores locais configurados.
    """
    return {
        "provider": settings.default_provider,
        "model_id": settings.default_model_id,
        "approve_risky_tools": True,
        "use_generic_template": settings.use_generic_decomposition_template,
        "ollama_base_url": settings.ollama_base_url,
        "llamacpp_base_url": settings.llamacpp_base_url,
    }


@router.post("/debug/chat/ollama")
async def debug_chat_ollama(
    body: dict,
    settings: Settings = Depends(read_settings),
) -> dict:
    """Envia um prompt direto ao Ollama, para diagnóstico da conexão.

    Args:
        body: corpo da requisição, com `model` e `prompt`.
        settings: configurações do processo.

    Returns:
        O conteúdo devolvido pelo modelo.

    Raises:
        HTTPException: com status 400 quando modelo ou prompt faltam e com status 503 quando o Ollama não responde.
    """
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
