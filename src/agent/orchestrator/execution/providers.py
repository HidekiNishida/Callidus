"""
Arquivo: src/agent/orchestrator/execution/providers.py
Nome: providers.py
Propósito: escolher o provedor de modelo do run e contabilizar o que ele consumiu.
Responsabilidade: camada de aplicação — seleção de provedor, perfil do modelo e acúmulo de uso.
Componentes: select_provider, default_provider_name, profile_from_config, supports_tool_loop, apply_provider_usage.
Dependências: agent.providers.registry, agent.providers.mock, agent.providers.base, agent.orchestrator.usage.
Observações: a troca de provedor é explícita e visível — nunca há fallback silencioso para o mock.
"""

from __future__ import annotations

from typing import Any

from agent.config import Settings
from agent.orchestrator.usage import accumulate_usage
from agent.persistence.models import TaskModel
from agent.providers.base import LLMProvider, ModelProfile, ProviderConfigError
from agent.providers.mock import MockProvider
from agent.providers.registry import build_provider_by_name


def select_provider(settings: Settings, run_config: dict) -> LLMProvider:
    """Provedor do run: nome vem do run (`config["provider"]`) ou das settings.

    Ordem: mock → catálogo de provedores configurado (`PROVIDERS_CONFIG_PATH`) → provedores
    embutidos (Ollama, llama.cpp). Nome desconhecido é erro explícito: trocar de provedor
    silenciosamente (por exemplo para o mock) mudaria custo, privacidade e resultado.

    Args:
        settings: configuração do processo.
        run_config: configuração do run (`provider`, `mock_keyword_map`).

    Returns:
        A instância do provedor escolhido.

    Raises:
        ProviderConfigError: quando o nome não existe e o fallback para o mock está desligado.
    """
    name = str(run_config.get("provider") or default_provider_name(settings) or "ollama")
    if name == "mock":
        kw = run_config.get("mock_keyword_map") or {}
        return MockProvider(keyword_map=kw)
    provider = build_provider_by_name(name, settings)
    if provider is not None:
        return provider
    if settings.allow_mock_fallback:
        return MockProvider()
    raise ProviderConfigError(
        f"provedor '{name}' desconhecido: use um nome definido no arquivo de provedores "
        "(PROVIDERS_CONFIG_PATH) ou 'ollama', 'llamacpp' ou 'mock'"
    )


def default_provider_name(settings: Settings) -> str:
    """Provedor padrão: o do arquivo de provedores, se houver; senão o das settings.

    Args:
        settings: configuração do processo.

    Returns:
        O nome do provedor padrão.
    """
    from agent.providers.registry import catalog_for_settings

    try:
        catalog = catalog_for_settings(settings)
    except ProviderConfigError:
        return settings.default_provider
    return catalog.default_provider or settings.default_provider


def profile_from_config(
    run_config: dict, settings: Settings, provider: LLMProvider | None = None
) -> ModelProfile:
    """Perfil do modelo (limites de contexto e geração) para este run.

    Args:
        run_config: configuração do run.
        settings: configuração do processo.
        provider: provedor escolhido; usado para ajustar o perfil às capacidades dele.

    Returns:
        O perfil do modelo a aplicar nas chamadas.
    """
    from agent.orchestrator.decomposition import profile_from_run_config

    return profile_from_run_config(run_config, settings, provider=provider)


def supports_tool_loop(provider: Any) -> bool:
    """O provedor sabe manter a conversa de ferramentas? Provedor sem o recurso fica no
    protocolo JSON de uma tacada (o modelo recebe as ferramentas só quando o transporte
    sabe devolver o resultado delas).

    Args:
        provider: provedor a inspecionar.

    Returns:
        `True` quando o provedor declara suporte ao ciclo de ferramentas.
    """
    capabilities = getattr(provider, "capabilities", None)
    if not callable(capabilities):
        return False
    try:
        return bool(capabilities().tool_loop)
    except Exception:  # pragma: no cover - provedor de teste sem capacidades
        return False


def apply_provider_usage(task: TaskModel, provider: Any) -> None:
    """Reconcilia o uso da etapa com o livro-razão, ou soma o diário do provedor.

    Args:
        task: etapa que disparou a inferência.
        provider: provedor usado. O diário `usage_log` é consumido e esvaziado.

    Observações:
        Quando a chamada já foi gravada no livro-razão, o metadado é reescrito
        pela soma dos registros. Somar `last_usage` de novo contaria a última
        resposta duas vezes e esqueceria as anteriores do ciclo de ferramentas.
    """
    from sqlalchemy.orm import object_session

    from agent.orchestrator.ledger import reconcile_task_usage

    log = list(getattr(provider, "usage_log", None) or [])
    provider.usage_log = []
    provider.last_usage = None
    session = object_session(task)
    if session is not None and reconcile_task_usage(session, task):
        return
    if not log:
        return
    prompt = 0
    completion = 0
    prompt_missing = 0
    completion_missing = 0
    for event in log:
        if event.get("prompt") is None:
            prompt_missing += 1
        else:
            prompt += int(event["prompt"])
        if event.get("completion") is None:
            completion_missing += 1
        else:
            completion += int(event["completion"])
    previous = (task.metadata_json or {}).get("usage") or {}
    meta = accumulate_usage(task.metadata_json, prompt, completion)
    usage = dict(meta.get("usage") or {})
    usage["calls"] = int(previous.get("calls") or 0) + len(log)
    usage["prompt_missing"] = int(previous.get("prompt_missing") or 0) + prompt_missing
    usage["completion_missing"] = int(previous.get("completion_missing") or 0) + completion_missing
    usage["measurement"] = "partial" if usage["prompt_missing"] or usage["completion_missing"] else "exact"
    meta["usage"] = usage
    task.metadata_json = meta
