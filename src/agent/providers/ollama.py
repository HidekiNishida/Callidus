# src/agent/providers/ollama.py — integração HTTP com Ollama (local ou remoto)
from __future__ import annotations

import json
from collections.abc import Callable

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
from agent.providers.http import HttpClientConfig, client_kwargs, get_json, post_json, stream_lines


def _ollama_message(message) -> dict:
    payload = {"role": message.role, "content": message.content}
    if message.images:
        payload["images"] = message.images
    if message.tool_calls:
        payload["tool_calls"] = [_ollama_tool_call(call) for call in message.tool_calls]
    return payload


def _ollama_tool_call(call: dict) -> dict:
    """Chamada de ferramenta no formato do Ollama (`function.name` + `function.arguments` já decodificado)."""
    function = call.get("function") or {}
    name = function.get("name") or call.get("name") or ""
    arguments = function.get("arguments")
    if arguments is None:
        arguments = call.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"raw": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    item: dict = {"type": "function", "function": {"name": name, "arguments": arguments}}
    if call.get("id"):
        item["id"] = call["id"]
    return item


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
    # `keep_alive` é a capacidade real do Ollama para manter o modelo residente. Numa
    # hierarquia de agentes os intervalos entre inferências podem ser longos: manter o
    # modelo carregado evita recarregar pesos a cada pergunta. Só é enviado quando
    # configurado — o padrão do servidor continua valendo.
    keep_alive = options.pop("keep_alive", None)
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    if options:
        body["options"] = options
    if request.response_format is not None:
        body["format"] = request.response_format.get("schema") or request.response_format
    if request.tools:
        body["tools"] = request.tools
    if request.tool_choice:
        body["tool_choice"] = request.tool_choice
    return body


def _tool_calls(message: dict) -> list[ToolCall] | None:
    raw = message.get("tool_calls") or []
    calls: list[ToolCall] = []
    for item in raw:
        function = item.get("function") or item
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


class OllamaProvider(LLMProvider):
    """Ollama local (`http://127.0.0.1:11434`) ou remoto (VPS, rede interna). A API nativa do
    Ollama é usada: `/api/tags` e `/api/chat` (não é uma API compatível com OpenAI)."""

    name = "ollama"
    supports_streaming = True

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        *,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        max_retries: int = 1,
        allow_private_hosts: bool = True,
        verify_tls: bool = True,
        default_model: str | None = None,
    ) -> None:
        self._http = HttpClientConfig(
            base_url=base_url,
            timeout=timeout,
            api_key=api_key,
            headers=dict(headers or {}),
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
        )
        self._base_url = self._http.resolved_base_url()
        self._timeout = timeout
        self.default_model = default_model

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tools=True,
            tool_loop=True,
            structured_output=True,
            vision=True,
            model_listing=True,
            usage_reporting=True,
            cancellation=True,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**client_kwargs(self._http))

    async def list_models(self) -> list[str]:
        url = f"{self._base_url}/api/tags"
        try:
            async with self._client() as client:
                data = await get_json(
                    client,
                    url,
                    label="Ollama",
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama indisponível em {self._base_url}: {exc}") from exc
        models = (data or {}).get("models") or []
        return [m.get("name", "") for m in models if m.get("name")]


    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        url = f"{self._base_url}/api/chat"
        body = chat_body(request)

        try:
            async with self._client() as client:
                data = await post_json(
                    client,
                    url,
                    body,
                    label="Ollama",
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência Ollama: {inference_failure_text(exc)}") from exc

        message = (data or {}).get("message") or {}
        content = message.get("content") or ""
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=(data or {}).get("prompt_eval_count"),
            completion_tokens_estimate=(data or {}).get("eval_count"),
            tool_calls=_tool_calls(message),
            finish_reason=(data or {}).get("done_reason"),
            model=(data or {}).get("model"),
            reasoning=message.get("thinking") or None,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def _chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """`/api/chat` com `stream: true`: uma linha JSON por fragmento; a última (`done`) traz uso de tokens
        e `done_reason`. A resposta devolvida é a mesma que `chat` daria (conteúdo inteiro + uso)."""
        url = f"{self._base_url}/api/chat"
        body = chat_body(request)
        body["stream"] = True
        parts: list[str] = []
        thoughts: list[str] = []
        streamed_calls: list[dict] = []
        final: dict = {}
        try:
            async with self._client() as client:
                async for line in stream_lines(
                    client,
                    url,
                    body,
                    label="Ollama",
                    secrets=self._http.secrets(),
                ):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(
                            f"Falha na inferência Ollama (stream): linha inválida ({exc})"
                        ) from exc
                    if data.get("error"):
                        raise ProviderError(f"Falha na inferência Ollama: {data['error']}")
                    message = data.get("message") or {}
                    piece = message.get("content") or ""
                    if piece:
                        parts.append(piece)
                        on_delta(piece)
                    thought = message.get("thinking") or ""
                    if thought:
                        thoughts.append(thought)
                    if message.get("tool_calls"):
                        streamed_calls.extend(message["tool_calls"])
                    if data.get("done"):
                        final = data
                        break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência Ollama: {inference_failure_text(exc)}") from exc
        if not final:
            raise ProviderError("Falha na inferência Ollama: a transmissão terminou sem a mensagem final")
        content = "".join(parts)
        message = final.get("message") or {}
        calls = _tool_calls(message) or _tool_calls({"tool_calls": streamed_calls})
        response = ChatCompletionResponse(
            content=content,
            raw={**final, "message": {"role": "assistant", "content": content}},
            prompt_tokens_estimate=final.get("prompt_eval_count"),
            completion_tokens_estimate=final.get("eval_count"),
            tool_calls=calls,
            finish_reason=final.get("done_reason"),
            model=final.get("model"),
            reasoning="".join(thoughts) or None,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response
