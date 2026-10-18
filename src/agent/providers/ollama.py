# src/agent/providers/ollama.py — integração HTTP com Ollama
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


def _ollama_message(message) -> dict:
    payload = {"role": message.role, "content": message.content}
    if message.images:
        payload["images"] = message.images
    return payload


def inference_failure_text(exc: Exception) -> str:
    detail = str(exc).strip()
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "timed out" in detail.lower():
        return "tempo esgotado"
    return detail or exc.__class__.__name__


def _reasoning_model(model_id: str) -> bool:
    low = model_id.lower()
    return any(token in low for token in ("qwen3", "gpt-oss", "deepseek", "reason"))


def chat_body(request: ChatCompletionRequest) -> dict:
    options = dict(request.profile.generation or {})
    think = options.pop("think", False)
    body = {
        "model": request.profile.model_id,
        "messages": [_ollama_message(m) for m in request.messages],
        "stream": False,
    }
    if _reasoning_model(request.profile.model_id):
        body["think"] = bool(think)
    if options:
        body["options"] = options
    if request.response_format is not None:
        body["format"] = request.response_format.get("schema") or request.response_format
    return body


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_streaming = True

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
        body = chat_body(request)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência Ollama: {inference_failure_text(exc)}") from exc

        message = data.get("message") or {}
        content = message.get("content") or ""
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=data.get("prompt_eval_count"),
            completion_tokens_estimate=data.get("eval_count"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """`/api/chat` com `stream: true`: uma linha JSON por fragmento; a última (`done`) traz uso de tokens
        e `done_reason`. A resposta devolvida é a mesma que `chat` daria (conteúdo inteiro + uso)."""
        url = f"{self._base_url}/api/chat"
        body = chat_body(request)
        body["stream"] = True
        parts: list[str] = []
        final: dict = {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(f"Falha na inferência Ollama (stream): linha inválida ({exc})") from exc
                        if data.get("error"):
                            raise ProviderError(f"Falha na inferência Ollama: {data['error']}")
                        piece = (data.get("message") or {}).get("content") or ""
                        if piece:
                            parts.append(piece)
                            on_delta(piece)
                        if data.get("done"):
                            final = data
                            break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência Ollama: {inference_failure_text(exc)}") from exc
        if not final:
            raise ProviderError("Falha na inferência Ollama: a transmissão terminou sem a mensagem final")
        content = "".join(parts)
        response = ChatCompletionResponse(
            content=content,
            raw={**final, "message": {"role": "assistant", "content": content}},
            prompt_tokens_estimate=final.get("prompt_eval_count"),
            completion_tokens_estimate=final.get("eval_count"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response