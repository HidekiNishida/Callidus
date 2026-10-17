# src/agent/providers/llamacpp.py — servidor OpenAI-compatible (llama.cpp)
from __future__ import annotations

import httpx

from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ProviderError,
)


class LlamaCppProvider(LLMProvider):
    name = "llamacpp"

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def list_models(self) -> list[str]:
        url = f"{self._base_url}/v1/models"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"llama.cpp server indisponível: {exc}") from exc
        items = data.get("data") or []
        return [item.get("id", "") for item in items if item.get("id")]

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/chat/completions"
        body = {
            "model": request.profile.model_id,
            "messages": [m.model_dump() for m in request.messages],
            "max_tokens": request.profile.output_reserve,
            **request.profile.generation,
        }
        if request.response_format is not None:
            body["response_format"] = request.response_format

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência llama.cpp: {exc}") from exc

        choices = data.get("choices") or []
        content = ""
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=usage.get("prompt_tokens"),
            completion_tokens_estimate=usage.get("completion_tokens"),
        )
