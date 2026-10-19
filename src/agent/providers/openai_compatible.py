# src/agent/providers/openai_compatible.py — adaptador reutilizável para APIs compatíveis com OpenAI
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

# Parâmetros de geração com equivalente direto na API compatível com OpenAI.
_GENERATION_KEYS = {
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "stop",
    "seed",
    "presence_penalty",
    "frequency_penalty",
    "repetition_penalty",
    "min_p",
    "typical_p",
    "logit_bias",
    "response_format",
}
# `think` é exclusivo do Ollama e não tem equivalente na API compatível com OpenAI: é omitido
# de forma explícita (documentado), nunca enviado como parâmetro desconhecido.
_OLLAMA_ONLY_KEYS = {"think"}


def generation_body(generation: dict[str, Any] | None) -> dict[str, Any]:
    """Traduz os parâmetros de geração do Callidus para o corpo de uma API compatível com OpenAI."""
    source = dict(generation or {})
    body: dict[str, Any] = {}
    for key, value in source.items():
        if key in _OLLAMA_ONLY_KEYS:
            continue
        if key == "num_predict":
            body.setdefault("max_tokens", value)
            continue
        if key in _GENERATION_KEYS:
            body[key] = value
            continue
        body[key] = value
    return body


def response_format_body(response_format: dict[str, Any] | None) -> dict[str, Any] | None:
    """Aceita o formato do Callidus (`{"schema": {...}}`) e o formato nativo (`{"type": ...}`)."""
    if response_format is None:
        return None
    if "type" in response_format:
        return response_format
    schema = response_format.get("schema")
    if not schema:
        return None
    return {"type": "json_schema", "json_schema": {"name": "response", "schema": schema}}


def _data_url(encoded: str) -> str:
    mime = "image/jpeg" if encoded.startswith("/9j/") else "image/png"
    return f"data:{mime};base64,{encoded}"


def openai_message(message) -> dict:
    if not message.images:
        return {"role": message.role, "content": message.content}
    parts: list[dict] = [{"type": "text", "text": message.content}]
    for image in message.images:
        parts.append({"type": "image_url", "image_url": {"url": _data_url(image)}})
    return {"role": message.role, "content": parts}


def parse_tool_calls(message: dict) -> list[ToolCall] | None:
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(id=item.get("id"), name=name, arguments=arguments))
    return calls or None


class OpenAICompatibleProvider(LLMProvider):
    """Adaptador para qualquer serviço que exponha o formato de `/v1/chat/completions` da OpenAI:
    gateways, provedores compatíveis, `llama-server` e o próprio OpenRouter. Recursos que o
    serviço não implementa apenas não voltam na resposta — nada é inventado."""

    name = "openai_compatible"
    supports_streaming = True
    default_base_url: str | None = None

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
        name: str | None = None,
        models_cache_ttl: float = 0.0,
    ) -> None:
        resolved = base_url or self.default_base_url
        if not resolved:
            raise ProviderError(f"URL base é obrigatória para o provedor '{name or self.name}'")
        self._http = HttpClientConfig(
            base_url=resolved,
            timeout=timeout,
            api_key=api_key,
            headers=dict(headers or {}),
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
        )
        self._base_url = self._http.resolved_base_url()
        self._timeout = timeout
        self.default_model = model
        self._models_cache: list[str] | None = None
        self._models_cached_at = 0.0
        self._models_cache_ttl = max(0.0, models_cache_ttl)
        if name:
            self.name = name

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tools=True,
            structured_output=True,
            vision=True,
            model_listing=True,
            usage_reporting=True,
            cancellation=True,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**client_kwargs(self._http))

    async def list_models(self, *, force: bool = False) -> list[str]:
        """Modelos disponíveis no serviço. Com `models_cache_ttl` a lista é cacheada em memória,
        para não consultar o catálogo a cada inferência."""
        if not force and self._models_cache is not None:
            age = time.monotonic() - self._models_cached_at
            if age <= self._models_cache_ttl:
                return list(self._models_cache)
        url = f"{self._base_url}/models"
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


    def _body(self, request: ChatCompletionRequest) -> dict:
        body: dict[str, Any] = {
            "model": request.profile.model_id,
            "messages": [openai_message(m) for m in request.messages],
        }
        body.update(generation_body(request.profile.generation))
        body.setdefault("max_tokens", request.profile.output_reserve)
        fmt = response_format_body(request.response_format)
        if fmt:
            body["response_format"] = fmt
        if request.tools:
            body["tools"] = request.tools
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice
        return body

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/chat/completions"
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

        error = (data or {}).get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ProviderError(f"Falha na inferência {self.name}: {message}")

        choices = (data or {}).get("choices") or []
        content = ""
        tool_calls: list[ToolCall] | None = None
        finish: str | None = None
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            tool_calls = parse_tool_calls(message)
            finish = choices[0].get("finish_reason")
        usage = (data or {}).get("usage") or {}
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=usage.get("prompt_tokens"),
            completion_tokens_estimate=usage.get("completion_tokens"),
            tool_calls=tool_calls,
            finish_reason=finish,
            model=(data or {}).get("model"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/chat/completions"
        body = {**self._body(request), "stream": True, "stream_options": {"include_usage": True}}
        parts: list[str] = []
        usage: dict = {}
        finish: str | None = None
        done = False
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
                        if payload == "[DONE]":
                            done = True
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                f"Falha na inferência {self.name} (stream): bloco inválido ({exc})"
                            ) from exc
                        if data.get("error"):
                            error = data["error"]
                            message = error.get("message") if isinstance(error, dict) else str(error)
                            raise ProviderError(f"Falha na inferência {self.name}: {message}")
                        usage = data.get("usage") or usage
                        for choice in data.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content") or ""
                            if piece:
                                parts.append(piece)
                                on_delta(piece)
                            finish = choice.get("finish_reason") or finish
                    if done:
                        break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência {self.name}: {exc}") from exc
        if not done and finish is None:
            raise ProviderError(f"Falha na inferência {self.name}: a transmissão terminou antes do fim")
        content = "".join(parts)
        response = ChatCompletionResponse(
            content=content,
            raw={
                "choices": [
                    {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
                ],
                "usage": usage,
            },
            prompt_tokens_estimate=usage.get("prompt_tokens"),
            completion_tokens_estimate=usage.get("completion_tokens"),
            finish_reason=finish,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response
