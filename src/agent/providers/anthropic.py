# src/agent/providers/anthropic.py — API nativa da Anthropic (Messages API)
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    ToolCall,
)
from agent.providers.http import HttpClientConfig, client_kwargs, get_json, post_json, sse_payloads, stream_lines

ANTHROPIC_VERSION = "2023-06-01"


def _media_type(encoded: str) -> str:
    if encoded.startswith("data:"):
        head = encoded.split(",", 1)[0]
        if "image/png" in head:
            return "image/png"
        if "image/webp" in head:
            return "image/webp"
        if "image/gif" in head:
            return "image/gif"
        encoded = encoded.split(",", 1)[-1]
    return "image/jpeg" if encoded.startswith("/9j/") else "image/png"


def _image_block(encoded: str) -> dict[str, Any]:
    if encoded.startswith("data:"):
        head, _, data = encoded.partition(",")
        media_type = head.split(";")[0].removeprefix("data:") or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": _media_type(encoded), "data": encoded},
    }


def anthropic_messages(messages) -> tuple[str, list[dict[str, Any]]]:
    """Separa o prompt de sistema (campo `system` da API) das mensagens de conversa."""
    system_parts: list[str] = []
    conversation: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.images:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
            blocks.extend(_image_block(image) for image in message.images)
            conversation.append({"role": message.role, "content": blocks})
        else:
            conversation.append({"role": message.role, "content": message.content})
    return "\n\n".join(system_parts), conversation


def anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Converte o formato de ferramenta do Callidus (OpenAI) para o da Anthropic."""
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if tool.get("type") == "function" else tool
        name = function.get("name")
        if not name:
            continue
        converted.append(
            {
                "name": name,
                "description": function.get("description") or "",
                "input_schema": function.get("parameters") or function.get("input_schema") or {"type": "object"},
            }
        )
    return converted or None


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API (`/v1/messages`). A API não é compatível com OpenAI: usa
    `x-api-key`, prompt de sistema em campo próprio e blocos de conteúdo."""

    name = "anthropic"
    supports_streaming = True
    default_base_url = "https://api.anthropic.com"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
        max_retries: int = 1,
        allow_private_hosts: bool = True,
        verify_tls: bool = True,
        anthropic_version: str = ANTHROPIC_VERSION,
        models_cache_ttl: float = 0.0,
    ) -> None:
        resolved = base_url or self.default_base_url
        if not resolved:
            raise ProviderError("URL base é obrigatória para o provedor 'anthropic'")
        merged = {"anthropic-version": anthropic_version}
        merged.update(headers or {})
        self._http = HttpClientConfig(
            base_url=resolved,
            timeout=timeout,
            api_key=api_key,
            headers=merged,
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
            auth_header="x-api-key",
            auth_scheme="",
        )
        self._base_url = self._http.resolved_base_url()
        self.default_model = model
        self._models_cache: list[str] | None = None
        self._models_cached_at = 0.0
        self._models_cache_ttl = max(0.0, models_cache_ttl)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tools=True,
            structured_output=False,
            vision=True,
            model_listing=True,
            usage_reporting=True,
            cancellation=True,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**client_kwargs(self._http))

    async def list_models(self, *, force: bool = False) -> list[str]:
        if not force and self._models_cache is not None:
            if time.monotonic() - self._models_cached_at <= self._models_cache_ttl:
                return list(self._models_cache)
        url = f"{self._base_url}/v1/models"
        try:
            async with self._client() as client:
                data = await get_json(
                    client,
                    url,
                    label=self.name,
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} indisponível: {exc}") from exc
        items = (data or {}).get("data") or []
        models = [item.get("id", "") for item in items if item.get("id")]
        self._models_cache = models
        self._models_cached_at = time.monotonic()
        return models

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        models = await self.list_models()
        return ProviderHealth(
            provider=self.name,
            ok=True,
            detail="ok",
            models=models,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _body(self, request: ChatCompletionRequest) -> dict:
        system, conversation = anthropic_messages(request.messages)
        generation = dict(request.profile.generation or {})
        generation.pop("think", None)
        body: dict[str, Any] = {
            "model": request.profile.model_id,
            "max_tokens": int(generation.pop("max_tokens", None) or request.profile.output_reserve),
            "messages": conversation,
        }
        if system:
            body["system"] = system
        for key in ("temperature", "top_p", "top_k", "stop_sequences", "metadata"):
            if key in generation:
                body[key] = generation[key]
        tools = anthropic_tools(request.tools)
        if tools:
            body["tools"] = tools
        return body

    @staticmethod
    def _parse(data: dict[str, Any]) -> tuple[str, list[ToolCall] | None, str | None]:
        parts: list[str] = []
        calls: list[ToolCall] = []
        for block in (data or {}).get("content") or []:
            if block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                payload = block.get("input")
                if not isinstance(payload, dict):
                    payload = {}
                calls.append(ToolCall(id=block.get("id"), name=block.get("name") or "", arguments=payload))
        return "".join(parts), (calls or None), (data or {}).get("stop_reason")

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/messages"
        body = self._body(request)
        try:
            async with self._client() as client:
                data = await post_json(
                    client,
                    url,
                    body,
                    label=self.name,
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência {self.name}: {exc}") from exc
        content, tool_calls, stop_reason = self._parse(data)
        usage = (data or {}).get("usage") or {}
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=usage.get("input_tokens"),
            completion_tokens_estimate=usage.get("output_tokens"),
            tool_calls=tool_calls,
            finish_reason=stop_reason,
            model=(data or {}).get("model"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/messages"
        body = {**self._body(request), "stream": True}
        parts: list[str] = []
        usage: dict = {}
        stop_reason: str | None = None
        try:
            async with self._client() as client:
                async for line in stream_lines(
                    client,
                    url,
                    body,
                    label=self.name,
                    secrets=self._http.secrets(),
                ):
                    for payload in sse_payloads([line]):
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                f"Falha na inferência {self.name} (stream): bloco inválido ({exc})"
                            ) from exc
                        kind = event.get("type")
                        if kind == "content_block_delta":
                            piece = (event.get("delta") or {}).get("text") or ""
                            if piece:
                                parts.append(piece)
                                on_delta(piece)
                        elif kind == "message_delta":
                            delta = event.get("delta") or {}
                            stop_reason = delta.get("stop_reason") or stop_reason
                            usage = {**usage, **(event.get("usage") or {})}
                        elif kind == "message_start":
                            usage = {**usage, **((event.get("message") or {}).get("usage") or {})}
                        elif kind == "error":
                            error = event.get("error") or {}
                            raise ProviderError(
                                f"Falha na inferência {self.name}: {error.get('message') or 'erro no stream'}"
                            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência {self.name}: {exc}") from exc
        content = "".join(parts)
        response = ChatCompletionResponse(
            content=content,
            raw={"content": [{"type": "text", "text": content}], "usage": usage},
            prompt_tokens_estimate=usage.get("input_tokens"),
            completion_tokens_estimate=usage.get("output_tokens"),
            finish_reason=stop_reason,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response
