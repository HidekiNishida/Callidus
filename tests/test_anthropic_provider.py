# tests/test_anthropic_provider.py — API nativa da Anthropic
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.anthropic import AnthropicProvider
from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    ModelProfile,
    ProviderAuthError,
)

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="claude-x", output_reserve=512, generation={"temperature": 0.2}),
)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


@pytest.mark.asyncio
async def test_request_uses_anthropic_shape(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = _body(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "olá"}]})

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="sk-ant-secreta")
    await provider.chat(REQUEST)

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-secreta"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["model"] == "claude-x"
    assert seen["body"]["max_tokens"] == 512
    assert seen["body"]["messages"] == [{"role": "user", "content": "oi"}]
    assert "system" not in seen["body"]


@pytest.mark.asyncio
async def test_system_message_goes_to_its_own_field(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    request = ChatCompletionRequest(
        messages=[
            ChatMessage(role="system", content="Seja breve"),
            ChatMessage(role="user", content="oi"),
        ],
        profile=ModelProfile(model_id="claude-x"),
    )
    await provider.chat(request)
    assert seen["body"]["system"] == "Seja breve"
    assert seen["body"]["messages"] == [{"role": "user", "content": "oi"}]


@pytest.mark.asyncio
async def test_response_blocks_and_usage_are_parsed(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "claude-x",
                "content": [
                    {"type": "text", "text": "resposta "},
                    {"type": "text", "text": "completa"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 11, "output_tokens": 3},
            },
        )

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    response = await provider.chat(REQUEST)
    assert response.content == "resposta completa"
    assert response.prompt_tokens_estimate == 11
    assert response.completion_tokens_estimate == 3
    assert response.finish_reason == "end_turn"


@pytest.mark.asyncio
async def test_tool_use_block_becomes_tool_call(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "buscar", "input": {"termo": "x"}}
                ],
                "stop_reason": "tool_use",
            },
        )

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    response = await provider.chat(REQUEST)
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "buscar"
    assert response.tool_calls[0].arguments == {"termo": "x"}


@pytest.mark.asyncio
async def test_tools_are_converted_to_input_schema(mock_http):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="claude-x"),
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "buscar",
                    "description": "busca algo",
                    "parameters": {"type": "object", "properties": {"termo": {"type": "string"}}},
                },
            }
        ],
    )
    await provider.chat(request)
    tool = seen["body"]["tools"][0]
    assert tool["name"] == "buscar"
    assert tool["input_schema"]["properties"]["termo"]["type"] == "string"


@pytest.mark.asyncio
async def test_streaming_events_are_translated(mock_http):
    body = (
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":7}}}\n\n'
        'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Ol"}}\n\n'
        'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"á"}}\n\n'
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n'
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert _body(request)["stream"] is True
        return httpx.Response(200, content=body)

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    pieces: list[str] = []
    response = await provider.chat_streaming(REQUEST, pieces.append)
    assert pieces == ["Ol", "á"]
    assert response.content == "Olá"
    assert response.prompt_tokens_estimate == 7
    assert response.completion_tokens_estimate == 2
    assert response.finish_reason == "end_turn"


@pytest.mark.asyncio
async def test_authentication_failure_is_reported(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "authentication_error"}})

    mock_http("anthropic", handler)
    provider = AnthropicProvider(api_key="k")
    with pytest.raises(ProviderAuthError):
        await provider.chat(REQUEST)


def test_capabilities_declare_no_structured_output():
    capabilities = AnthropicProvider(api_key="k").capabilities()
    assert capabilities.streaming is True
    assert capabilities.tools is True
    assert capabilities.structured_output is False
