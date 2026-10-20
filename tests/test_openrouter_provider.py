"""
Arquivo: tests/test_openrouter_provider.py
Nome: test_openrouter_provider.py
Propósito: verificar o adaptador do OpenRouter, da URL padrão aos cabeçalhos de identificação e ao cache de modelos.
Responsabilidade: camada de testes — comportamento observável do provedor OpenRouter (URL, cabeçalhos, modelos e erros).
Componentes: URL padrão e cabeçalhos de identificação, URL customizada, listagem cacheada de modelos, modelo enviado e erro devolvido pela API.
Dependências: agent.providers.openrouter.OpenRouterProvider, agent.providers.base, fixture mock_http do conftest, httpx, pytest.
Observações: todo o HTTP é simulado pela fixture mock_http; nenhum serviço do OpenRouter é contatado.

OpenRouter
"""
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.openrouter import OpenRouterProvider

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="autor/modelo"),
)


@pytest.mark.asyncio
async def test_default_base_url_and_identification_headers(mock_http):
    """Sem URL customizada, a chamada vai ao endpoint padrão do OpenRouter com os cabeçalhos de título, referer e autorização."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenRouterProvider(api_key="or-key", referer="https://callidus.local")
    await provider.chat(REQUEST)

    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["x-title"] == "Callidus"
    assert seen["headers"]["http-referer"] == "https://callidus.local"
    assert seen["headers"]["authorization"] == "Bearer or-key"


@pytest.mark.asyncio
async def test_custom_base_url_is_used(mock_http):
    """Uma URL de base customizada é usada no lugar do endpoint padrão."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenRouterProvider("https://proxy.local/api/v1", api_key="k")
    await provider.chat(REQUEST)
    assert seen["url"] == "https://proxy.local/api/v1/chat/completions"


@pytest.mark.asyncio
async def test_models_come_from_the_api_and_are_cached(mock_http):
    """Os modelos vêm da API e a segunda listação é servida do cache, sem nova chamada."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        calls["n"] += 1
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json={"data": [{"id": "autor/modelo-a"}, {"id": "autor/modelo-b"}]})

    mock_http("openai_compatible", handler)
    provider = OpenRouterProvider(api_key="k")
    assert await provider.list_models() == ["autor/modelo-a", "autor/modelo-b"]
    assert await provider.list_models() == ["autor/modelo-a", "autor/modelo-b"]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_chat_body_uses_the_configured_model(mock_http):
    """O corpo da requisição carrega o modelo configurado no provedor."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenRouterProvider(model="autor/modelo", api_key="k")
    await provider.chat(REQUEST)
    assert seen["body"]["model"] == "autor/modelo"


@pytest.mark.asyncio
async def test_error_body_from_openrouter_is_surfaced(mock_http):
    """O corpo de erro devolvido pelo OpenRouter aparece na exceção levantada."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(200, json={"error": {"message": "modelo indisponível", "code": 502}})

    mock_http("openai_compatible", handler)
    provider = OpenRouterProvider(api_key="k")
    with pytest.raises(Exception) as exc:
        await provider.chat(REQUEST)
    assert "modelo indisponível" in str(exc.value)
