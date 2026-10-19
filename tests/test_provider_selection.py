# tests/test_provider_selection.py — seleção e troca de provedor sem tocar no núcleo do agente
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
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "http://10.0.0.9:11434")
    monkeypatch.setenv("GATEWAY_KEY", "chave-de-teste-123456")
    path = tmp_path / "providers.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return Settings(provider_config_path=path)


def test_catalog_provider_is_selected_by_name(settings):
    provider = _select_provider(settings, {"provider": "ollama_remote"})
    assert isinstance(provider, OllamaProvider)
    assert provider.default_model == "qwen3:8b"


def test_default_provider_of_the_catalog_is_used(settings):
    provider = _select_provider(settings, {})
    assert isinstance(provider, OllamaProvider)
    assert provider.default_model == "qwen3:8b"


def test_openai_compatible_provider_is_selected(settings):
    provider = _select_provider(settings, {"provider": "gateway"})
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.default_model == "modelo-do-gateway"


def test_model_of_the_provider_is_the_default_of_the_profile(settings):
    provider = _select_provider(settings, {"provider": "gateway"})
    profile = _profile_from_config({}, settings, provider)
    assert profile.model_id == "modelo-do-gateway"


def test_run_can_override_the_model(settings):
    provider = _select_provider(settings, {"provider": "gateway"})
    profile = _profile_from_config({"model_id": "outro-modelo"}, settings, provider)
    assert profile.model_id == "outro-modelo"


def test_profile_falls_back_to_the_settings_default_without_provider():
    settings = Settings(default_model_id="padrao")
    assert profile_from_run_config({}, settings).model_id == "padrao"


def test_builtin_providers_keep_working_without_configuration_file():
    settings = Settings(ollama_base_url="http://127.0.0.1:11434")
    assert isinstance(_select_provider(settings, {"provider": "ollama"}), OllamaProvider)
    assert isinstance(_select_provider(settings, {"provider": "llamacpp"}), LlamaCppProvider)
    assert isinstance(_select_provider(settings, {"provider": "mock"}), MockProvider)


def test_switching_provider_between_runs(settings):
    first = _select_provider(settings, {"provider": "ollama_remote"})
    second = _select_provider(settings, {"provider": "gateway"})
    assert first.name == "ollama"
    assert second.name == "gateway"


def test_openrouter_can_be_declared_in_the_configuration(tmp_path, monkeypatch):
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
