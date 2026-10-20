"""
Arquivo: tests/test_provider_selection.py
Nome: test_provider_selection.py
Propósito: verificar a seleção e a troca de provedor sem tocar no núcleo do agente.
Responsabilidade: camada de testes — comportamento da escolha de provedor e do perfil de modelo derivado da configuração.
Componentes: seleção por nome, uso do padrão do catálogo, provedor compatível com OpenAI, modelo do provedor como padrão do perfil, override de modelo pela run, fallback para o modelo padrão, provedores embutidos e troca entre runs.
Dependências: agent.orchestrator.runner (_select_provider, _profile_from_config), agent.orchestrator.decomposition.profile_from_run_config, agent.providers (ollama, llamacpp, openai_compatible, openrouter, mock), pytest.
Observações: arquivo de configuração e chaves de ambiente temporários, definidos por monkeypatch.

seleção e troca de provedor sem tocar no núcleo do agente
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import Settings
from agent.orchestrator.decomposition import profile_from_run_config
from agent.orchestrator.runner import _profile_from_config, _select_provider
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.mock import MockProvider
from agent.providers.ollama import OllamaProvider
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.openrouter import OpenRouterProvider

CONFIG = """
default_provider: ollama_remote

providers:
  ollama_remote:
    type: ollama
    base_url: ${CALLIDUS_OLLAMA_URL}
    model: qwen3:8b

  gateway:
    type: openai_compatible
    base_url: http://gateway.local/v1
    model: modelo-do-gateway
    api_key_env: GATEWAY_KEY
"""


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    """Configurações com um catálogo de provedores temporário e as variáveis de ambiente correspondentes."""
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "http://10.0.0.9:11434")
    monkeypatch.setenv("GATEWAY_KEY", "chave-de-teste-123456")
    path = tmp_path / "providers.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return Settings(provider_config_path=path)


def test_catalog_provider_is_selected_by_name(settings):
    """O provedor do catálogo é escolhido pelo nome e usa o modelo configurado."""
    provider = _select_provider(settings, {"provider": "ollama_remote"})
    assert isinstance(provider, OllamaProvider)
    assert provider.default_model == "qwen3:8b"


def test_default_provider_of_the_catalog_is_used(settings):
    """Sem nome na configuração, o provedor padrão do catálogo é usado."""
    provider = _select_provider(settings, {})
    assert isinstance(provider, OllamaProvider)
    assert provider.default_model == "qwen3:8b"


def test_openai_compatible_provider_is_selected(settings):
    """Um provedor do tipo compatível com OpenAI é construído com o modelo configurado."""
    provider = _select_provider(settings, {"provider": "gateway"})
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.default_model == "modelo-do-gateway"


def test_model_of_the_provider_is_the_default_of_the_profile(settings):
    """O modelo do provedor escolhido vira o modelo padrão do perfil da execução."""
    provider = _select_provider(settings, {"provider": "gateway"})
    profile = _profile_from_config({}, settings, provider)
    assert profile.model_id == "modelo-do-gateway"


def test_run_can_override_the_model(settings):
    """A configuração da run pode sobrescrever o modelo do provedor."""
    provider = _select_provider(settings, {"provider": "gateway"})
    profile = _profile_from_config({"model_id": "outro-modelo"}, settings, provider)
    assert profile.model_id == "outro-modelo"


def test_profile_falls_back_to_the_settings_default_without_provider():
    """Sem provedor, o perfil usa o modelo padrão das configurações."""
    settings = Settings(default_model_id="padrao")
    assert profile_from_run_config({}, settings).model_id == "padrao"


def test_builtin_providers_keep_working_without_configuration_file():
    """Os provedores embutidos continuam funcionando sem arquivo de configuração."""
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")
    assert isinstance(_select_provider(settings, {"provider": "ollama"}), OllamaProvider)
    assert isinstance(_select_provider(settings, {"provider": "llamacpp"}), LlamaCppProvider)
    assert isinstance(_select_provider(settings, {"provider": "mock"}), MockProvider)


def test_switching_provider_between_runs(settings):
    """Trocar o provedor entre execuções devolve instâncias do provedor pedido em cada uma."""
    first = _select_provider(settings, {"provider": "ollama_remote"})
    second = _select_provider(settings, {"provider": "gateway"})
    assert first.name == "ollama"
    assert second.name == "gateway"


def test_openrouter_can_be_declared_in_the_configuration(tmp_path, monkeypatch):
    """O OpenRouter pode ser declarado no arquivo de configuração e é construído com o modelo declarado."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-de-teste-123456")
    path = tmp_path / "providers.yaml"
    path.write_text(
        "providers:\n  router:\n    type: openrouter\n    model: autor/modelo\n    api_key_env: OPENROUTER_API_KEY\n",
        encoding="utf-8",
    )
    settings = Settings(provider_config_path=path)
    provider = _select_provider(settings, {"provider": "router"})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.default_model == "autor/modelo"
