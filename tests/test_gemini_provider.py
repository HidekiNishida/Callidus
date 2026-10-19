# tests/test_gemini_provider.py — API nativa do Google Gemini
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    ModelProfile,
    ProviderAuthError,
)
from agent.providers.gemini import GeminiProvider

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="gemini-2.0-flash", output_reserve=256, generation={"temperature": 0.3}),
)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


@pytest.mark.asyncio
async def test_request_uses_gemini_shape(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = _body(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "olá"}]}, "finishReason": "STOP"}]},
        )

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="AIza-secreta-123456")
    response = await provider.chat(REQUEST)

    assert seen["url"].endswith("/models/gemini-2.0-flash:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "AIza-secreta-123456"
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "oi"}]}]
    assert seen["body"]["generationConfig"]["temperature"] == 0.3
    assert seen["body"]["generationConfig"]["maxOutputTokens"] == 256
    assert response.content == "olá"
    assert response.finish_reason == "STOP"


@pytest.mark.asyncio
async def test_assistant_role_becomes_model_and_system_is_separated(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    request = ChatCompletionRequest(
        messages=[
            ChatMessage(role="system", content="Seja breve"),
            ChatMessage(role="assistant", content="anterior"),
            ChatMessage(role="user", content="oi"),
        ],
        profile=ModelProfile(model_id="gemini-2.0-flash"),
    )
    await provider.chat(request)
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "Seja breve"}]}
    assert seen["body"]["contents"][0] == {"role": "model", "parts": [{"text": "anterior"}]}
    assert seen["body"]["contents"][1] == {"role": "user", "parts": [{"text": "oi"}]}


@pytest.mark.asyncio
async def test_usage_and_function_call_are_parsed(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "vou buscar"},
                                {"functionCall": {"name": "buscar", "args": {"termo": "x"}}},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
            },
        )

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    response = await provider.chat(REQUEST)
    assert response.content == "vou buscar"
    assert response.prompt_tokens_estimate == 9
    assert response.completion_tokens_estimate == 4
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "buscar"
    assert response.tool_calls[0].arguments == {"termo": "x"}


@pytest.mark.asyncio
async def test_tools_are_converted_to_function_declarations(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="gemini-2.0-flash"),
        tools=[
            {
                "type": "function",
                "function": {"name": "buscar", "parameters": {"type": "object", "properties": {}}},
            }
        ],
    )
    await provider.chat(request)
    declaration = seen["body"]["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "buscar"


@pytest.mark.asyncio
async def test_structured_output_sets_mime_type(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="gemini-2.0-flash"),
        response_format={"schema": {"type": "object"}},
    )
    await provider.chat(request)
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["generationConfig"]["responseSchema"] == {"type": "object"}


@pytest.mark.asyncio
async def test_streaming_uses_sse_and_collects_fragments(mock_http):
    body = (
        'data: {"candidates":[{"content":{"parts":[{"text":"Ol"}]}}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":"á"}]}}],"usageMetadata":{"promptTokenCount":3}}\n\n'
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "streamGenerateContent" in str(request.url)
        assert "alt=sse" in str(request.url)
        return httpx.Response(200, content=body)

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    pieces: list[str] = []
    response = await provider.chat_streaming(REQUEST, pieces.append)
    assert pieces == ["Ol", "á"]
    assert response.content == "Olá"
    assert response.prompt_tokens_estimate == 3


@pytest.mark.asyncio
async def test_model_list_comes_from_the_api(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={"models": [{"name": "models/gemini-2.0-flash"}, {"name": "models/gemini-1.5-pro"}]},
        )

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    assert await provider.list_models() == ["gemini-2.0-flash", "gemini-1.5-pro"]


@pytest.mark.asyncio
async def test_authentication_failure_is_reported(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "API key not valid"}})

    mock_http("gemini", handler)
    provider = GeminiProvider(api_key="k")
    with pytest.raises(ProviderAuthError):
        await provider.chat(REQUEST)
