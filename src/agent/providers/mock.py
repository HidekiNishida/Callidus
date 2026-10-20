# src/agent/providers/mock.py — provedor determinístico para testes
from __future__ import annotations

import json
from typing import Any

from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ProviderCapabilities,
)


class MockProvider(LLMProvider):
    """Provedor determinístico, sem rede: testes e execução offline. Não depende de serviço
    externo e não simula recursos que não tem (streaming, ferramentas)."""

    name = "mock"

    def __init__(self, responses: list[str] | None = None, keyword_map: dict[str, str] | None = None) -> None:
        self._responses = list(responses or [])
        self._keyword_map = keyword_map or {}
        self._call_index = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=False,
            tools=False,
            structured_output=False,
            vision=False,
            model_listing=True,
            usage_reporting=False,
            cancellation=True,
        )

    async def list_models(self) -> list[str]:
        return ["mock-model"]

    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        user_text = ""
        for m in request.messages:
            if m.role == "user":
                user_text += m.content
        for key, body in self._keyword_map.items():
            if key in user_text:
                return ChatCompletionResponse(content=body, raw={"mock": True})
        if self._call_index < len(self._responses):
            content = self._responses[self._call_index]
            self._call_index += 1
            return ChatCompletionResponse(content=content, raw={"mock": True, "index": self._call_index})
        return ChatCompletionResponse(
            content=json.dumps({"action": "noop", "summary": "mock default"}),
            raw={"mock": True},
        )


def decomposition_json(subtasks: list[dict[str, Any]]) -> str:
    return json.dumps({"subtasks": subtasks}, ensure_ascii=False)
