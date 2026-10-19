# tests/test_llamacpp_remote.py — llama.cpp local e remoto (API compatível com OpenAI)
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    ModelProfile,
    ProviderAuthError,
    ProviderError,
)
from agent.providers.llamacpp import LlamaCppProvider

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="meu-gguf", output_reserve=256),
)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


@pytest.mark.asyncio
async def test_remote_server_is_called_on_the_openai_endpoint(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = _body(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pronto"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}},
        )

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080")
    response = await provider.chat(REQUEST)

    assert seen["url"] == "https://gpu.exemplo:8080/v1/chat/completions"
    assert seen["body"]["model"] == "meu-gguf"
    assert seen["body"]["max_tokens"] == 256
    assert response.content == "pronto"
    assert response.prompt_tokens_estimate == 2


@pytest.mark.asyncio
async def test_api_key_is_sent_as_bearer(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080", api_key="llama-secreta-123")
    await provider.chat(REQUEST)
    assert seen["auth"] == "Bearer llama-secreta-123"


@pytest.mark.asyncio
async def test_api_key_file_is_read(tmp_path, mock_http):
    key_file = tmp_path / "key.txt"
    key_file.write_text("token-do-arquivo\n", encoding="utf-8")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080", api_key_file=str(key_file))
    await provider.chat(REQUEST)
    assert seen["auth"] == "Bearer token-do-arquivo"


@pytest.mark.asyncio
async def test_tools_are_sent(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="meu-gguf"),
        tools=[{"type": "function", "function": {"name": "buscar", "parameters": {"type": "object"}}}],
    )
    await provider.chat(request)
    assert seen["body"]["tools"][0]["function"]["name"] == "buscar"


@pytest.mark.asyncio
async def test_streaming_cut_before_the_end_fails(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"parcial"}}]}\n\n')

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080")
    with pytest.raises(ProviderError) as exc:
        await provider.chat_streaming(REQUEST, lambda _p: None)
    assert "terminou antes do fim" in str(exc.value)


@pytest.mark.asyncio
async def test_authentication_failure_is_reported(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080", api_key="k")
    with pytest.raises(ProviderAuthError):
        await provider.chat(REQUEST)


@pytest.mark.asyncio
async def test_models_are_listed(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "meu-gguf"}]})

    mock_http("llamacpp", handler)
    provider = LlamaCppProvider("https://gpu.exemplo:8080")
    assert await provider.list_models() == ["meu-gguf"]
