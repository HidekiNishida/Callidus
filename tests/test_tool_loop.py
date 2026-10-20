# tests/test_tool_loop.py — ciclo de ferramentas da operação (regressão da "resposta vazia")
"""Regressão do defeito encontrado na conversa real: um modelo que trabalha com ferramentas
(`gpt-oss:20b`) devolve `content` vazio quando o pedido chega sem ferramentas declaradas —
ele pede a ferramenta e não há para onde pedir. O Callidus tratava isso como "resposta vazia",
repetia o mesmo pedido e parava em estagnação."""
from __future__ import annotations

import json

import httpx
import pytest

from agent.domain.failures import FailureCause, classify_model_output
from agent.orchestrator.tool_loop import (
    MUTATION_TOOLS,
    OPERATION_TOOLS,
    json_schema_for,
    run_tool_loop,
    tool_result_text,
    tool_schemas,
)
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile, ProviderCapabilities, ToolCall
from agent.providers.ollama import OllamaProvider
from agent.tools.registry import ToolContext, build_default_registry


class _FakeProvider:
    """Provedor que devolve uma resposta por vez, conforme o roteiro."""

    name = "fake"
    supports_streaming = False

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[ChatCompletionRequest] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, tool_loop=True)

    async def chat(self, request: ChatCompletionRequest):
        self.requests.append(request)
        step = self.script.pop(0) if self.script else {"content": "ok"}
        calls = [
            ToolCall(id=f"c{index}", name=item["name"], arguments=item.get("arguments", {}))
            for index, item in enumerate(step.get("tool_calls") or [])
        ]
        return type(
            "R",
            (),
            {
                "content": step.get("content", ""),
                "tool_calls": calls or None,
                "reasoning": step.get("reasoning"),
                "completion_tokens_estimate": step.get("tokens", 10),
                "prompt_tokens_estimate": 5,
            },
        )()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(project_root=str(tmp_path))


def _profile() -> ModelProfile:
    return ModelProfile(model_id="gpt-oss:20b", context_limit=8192, input_budget=6000, output_reserve=1024)


def test_tool_schemas_use_json_schema_from_the_simplified_spec():
    registry = build_default_registry()
    spec = registry.get_spec("read_file")
    schema = json_schema_for(spec)
    assert schema["type"] == "object"
    assert schema["properties"]["path"]["type"] == "string"
    assert "path" in schema["required"]

    optional = json_schema_for(registry.get_spec("list_dir"))
    assert optional.get("required", []) == []

    names = [item["function"]["name"] for item in tool_schemas(registry, OPERATION_TOOLS)]
    assert "read_file" in names
    assert "write_file" in names


def test_tool_result_text_truncates_long_output():
    body = tool_result_text({"success": True, "content": "x" * 5000}, limit=100)
    assert body.startswith("x" * 50)
    assert "…" in body


@pytest.mark.asyncio
async def test_loop_executes_the_requested_tool_and_feeds_the_result_back(ctx):
    provider = _FakeProvider(
        [
            {"tool_calls": [{"name": "read_file", "arguments": {"path": "a.txt"}}]},
            {"content": '{"path":"a.txt","content":"oi"}'},
        ]
    )
    seen: list[str] = []

    async def on_tool(entry, result):
        seen.append(entry["tool"])

    outcome = await run_tool_loop(
        provider=provider,
        messages=[ChatMessage(role="user", content="faça")],
        profile=_profile(),
        registry=build_default_registry(),
        ctx=ctx,
        on_tool_call=on_tool,
        chat=lambda p, r, purpose, stream: p.chat(r),
    )

    assert outcome.stop_reason == "final"
    assert outcome.content == '{"path":"a.txt","content":"oi"}'
    assert seen == ["read_file"]
    # O histórico enviado na segunda chamada tem a resposta da ferramenta.
    second = provider.requests[1]
    assert any(m.role == "tool" for m in second.messages)
    assert second.messages[-1].role == "tool"


@pytest.mark.asyncio
async def test_model_that_applies_the_change_through_the_tool_ends_the_cycle(ctx):
    provider = _FakeProvider(
        [
            {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.txt", "content": "oi"}}]},
        ]
    )
    outcome = await run_tool_loop(
        provider=provider,
        messages=[ChatMessage(role="user", content="faça")],
        profile=_profile(),
        registry=build_default_registry(),
        ctx=ctx,
        chat=lambda p, r, purpose, stream: p.chat(r),
    )
    assert outcome.applied is True
    assert outcome.applied_tool == "write_file"
    assert outcome.applied_args["path"] == "a.txt"
    assert (ctx.project_root and (outcome.applied_result.get("success") is True))


@pytest.mark.asyncio
async def test_budget_exhausted_forces_a_final_call_that_can_apply_the_change(ctx, tmp_path):
    provider = _FakeProvider(
        [
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.txt", "content": "oi"}}]},
        ]
    )
    outcome = await run_tool_loop(
        provider=provider,
        messages=[ChatMessage(role="user", content="faça")],
        profile=_profile(),
        registry=build_default_registry(),
        ctx=ctx,
        max_iterations=2,
        chat=lambda p, r, purpose, stream: p.chat(r),
    )
    # A última chamada (a que força a alteração) é a que aplicou a escrita.
    assert outcome.applied is True
    assert provider.requests[-1].messages[-1].role == "user"


@pytest.mark.asyncio
async def test_repeated_tool_call_tells_the_model_it_already_knows(ctx):
    provider = _FakeProvider(
        [
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"content": "fim"},
        ]
    )
    outcome = await run_tool_loop(
        provider=provider,
        messages=[ChatMessage(role="user", content="faça")],
        profile=_profile(),
        registry=build_default_registry(),
        ctx=ctx,
        chat=lambda p, r, purpose, stream: p.chat(r),
    )
    tool_messages = [m for m in provider.requests[2].messages if m.role == "tool"]
    assert any("já consultou" in m.content for m in tool_messages)
    assert outcome.content == "fim"


def test_empty_output_with_reasoning_is_not_a_plain_invalid_json():
    failure = classify_model_output("", "resposta vazia", None, reasoning="vou ler o arquivo")
    assert failure is not None
    assert failure.cause == FailureCause.EMPTY_OUTPUT
    assert failure.category.value == "change_strategy"


def test_empty_output_without_reasoning_keeps_the_old_classification():
    failure = classify_model_output("", "resposta vazia", None)
    assert failure is not None
    assert failure.cause == FailureCause.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_ollama_sends_the_tool_history_and_reads_the_reasoning(mock_http):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "thinking": "vou ler o arquivo",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "read_file", "arguments": {"path": "a.txt"}}}
                    ],
                },
                "done_reason": "stop",
            },
        )

    mock_http("ollama", handler)
    provider = OllamaProvider("http://127.0.0.1:11434")
    request = ChatCompletionRequest(
        messages=[
            ChatMessage(role="user", content="faça"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": {"path": "a.txt"}}}
                ],
            ),
            ChatMessage(role="tool", content="conteúdo", tool_call_id="c1"),
        ],
        profile=ModelProfile(model_id="gpt-oss:20b"),
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
    )
    response = await provider.chat(request)

    body = seen["body"]
    assert body["messages"][1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert body["messages"][2]["role"] == "tool"
    assert response.reasoning == "vou ler o arquivo"
    assert response.tool_calls is not None and response.tool_calls[0].name == "read_file"


def test_mutation_tools_are_part_of_the_operation_set():
    assert set(MUTATION_TOOLS) <= set(OPERATION_TOOLS)
