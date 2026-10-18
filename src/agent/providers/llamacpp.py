# src/agent/providers/llamacpp.py — servidor OpenAI-compatible (llama.cpp)
from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ProviderError,
)


def _data_url(encoded: str) -> str:
    mime = "image/jpeg" if encoded.startswith("/9j/") else "image/png"
    return f"data:{mime};base64,{encoded}"


def _openai_message(message) -> dict:
    if not message.images:
        return {"role": message.role, "content": message.content}
    parts: list[dict] = [{"type": "text", "text": message.content}]
    for image in message.images:
        parts.append({"type": "image_url", "image_url": {"url": _data_url(image)}})
    return {"role": message.role, "content": parts}


class LlamaCppProvider(LLMProvider):
    name = "llamacpp"
    supports_streaming = True

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

    def _body(self, request: ChatCompletionRequest) -> dict:
        body = {
            "model": request.profile.model_id,
            "messages": [_openai_message(m) for m in request.messages],
            "max_tokens": request.profile.output_reserve,
            **request.profile.generation,
        }
        if request.response_format is not None:
            body["response_format"] = request.response_format
        return body

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """`stream: true` no endpoint OpenAI: eventos `data: {...}` com `choices[0].delta.content` até `[DONE]`;
        o uso de tokens vem no último bloco quando o servidor suporta `include_usage`."""
        url = f"{self._base_url}/v1/chat/completions"
        body = {**self._body(request), "stream": True, "stream_options": {"include_usage": True}}
        parts: list[str] = []
        usage: dict = {}
        finish: str | None = None
        done = False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            done = True
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(f"Falha na inferência llama.cpp (stream): bloco inválido ({exc})") from exc
                        if data.get("error"):
                            raise ProviderError(f"Falha na inferência llama.cpp: {data['error']}")
                        usage = data.get("usage") or usage
                        for choice in data.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content") or ""
                            if piece:
                                parts.append(piece)
                                on_delta(piece)
                            finish = choice.get("finish_reason") or finish
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência llama.cpp: {exc}") from exc
        if not done and finish is None:
            raise ProviderError("Falha na inferência llama.cpp: a transmissão terminou antes do fim")
        content = "".join(parts)
        response = ChatCompletionResponse(
            content=content,
            raw={"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}], "usage": usage},
            prompt_tokens_estimate=usage.get("prompt_tokens"),
            completion_tokens_estimate=usage.get("completion_tokens"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/chat/completions"
        body = self._body(request)

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
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=usage.get("prompt_tokens"),
            completion_tokens_estimate=usage.get("completion_tokens"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response
