# tests/test_provider_security.py — credenciais, TLS e ausência de fallback silencioso
from __future__ import annotations

import httpx
import pytest

from agent.config import Settings
from agent.orchestrator.runner import _select_provider
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile, ProviderConfigError
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.registry import ProviderCatalog

SECRET = "sk-super-secreta-1234567890"
REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="m"),
)


@pytest.mark.asyncio
async def test_credential_never_appears_in_the_error_message(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"chave {SECRET} recusada")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key=SECRET)
    with pytest.raises(Exception) as exc:
        await provider.chat(REQUEST)
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_credential_is_not_leaked_when_the_server_echoes_it(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"erro interno com {SECRET}")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key=SECRET)
    with pytest.raises(Exception) as exc:
        await provider.chat(REQUEST)
    assert SECRET not in str(exc.value)


def test_provider_catalog_does_not_expose_the_credential(monkeypatch):
    monkeypatch.setenv("MINHA_CHAVE", SECRET)
    catalog = ProviderCatalog.from_mapping(
        {"providers": {"p": {"type": "openrouter", "api_key_env": "MINHA_CHAVE"}}}
    )
    provider = catalog.build("p", Settings())
    assert SECRET not in repr(provider.__dict__)


def test_tls_verification_stays_on_by_default():
    from agent.providers.http import HttpClientConfig, client_kwargs

    assert client_kwargs(HttpClientConfig(base_url="http://x/v1"))["verify"] is True
    assert Settings().provider_verify_tls is True


def test_unknown_provider_is_an_explicit_error_and_does_not_fall_back():
    settings = Settings(allow_mock_fallback=False)
    with pytest.raises(ProviderConfigError) as exc:
        _select_provider(settings, {"provider": "provedor-que-nao-existe"})
    assert "provedor-que-nao-existe" in str(exc.value)


def test_mock_fallback_requires_the_explicit_flag():
    settings = Settings(allow_mock_fallback=True)
    provider = _select_provider(settings, {"provider": "provedor-que-nao-existe"})
    assert provider.name == "mock"


def test_secret_is_not_written_into_the_run_configuration():
    settings = Settings(allow_mock_fallback=False)
    provider = _select_provider(settings, {"provider": "ollama"})
    assert "api_key" not in repr(vars(provider))
