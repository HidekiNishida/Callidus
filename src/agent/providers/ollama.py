# src/agent/providers/ollama.py — integração HTTP com Ollama
from __future__ import annotations

import httpx

from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ProviderError,
)


def _ollama_message(message) -> dict:
    payload = {"role": message.role, "content": message.content}
    if message.images:
        payload["images"] = message.images
    return payload


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def list_models(self) -> list[str]:
        url = f"{self._base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama indisponível em {self._base_url}: {exc}") from exc
        models = data.get("models") or []
        return [m.get("name", "") for m in models if m.get("name")]

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/api/chat"
        body = {
            "model": request.profile.model_id,
            "messages": [_ollama_message(m) for m in request.messages],
            "stream": False,
            "options": request.profile.generation or None,
        }
        if request.response_format is not None:
            body["format"] = request.response_format.get("schema") or request.response_format

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência Ollama: {exc}") from exc

        message = data.get("message") or {}
        content = message.get("content") or ""
        return ChatCompletionResponse(content=content, raw=data)
