"""
Arquivo: src/agent/providers/gemini.py
Nome: gemini.py
Propósito: implementar o provedor da API nativa do Google Gemini (generateContent).
Responsabilidade: camada de infraestrutura — adaptação entre o contrato do Callidus e a API do Gemini.
Componentes: GeminiProvider, gemini_contents, gemini_tools.
Dependências: agent.providers.base, agent.providers.http, httpx.
Observações: a API não é compatível com OpenAI: usa `contents`/`parts`, `x-goog-api-key` e `generationConfig`.
"""
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


def _media_type(encoded: str) -> str:
    """Deduz o tipo de mídia de uma imagem codificada em base64.

    Args:
        encoded: imagem em base64, com ou sem prefixo `data:`.

    Returns:
        O tipo de mídia correspondente.
    """
    if encoded.startswith("data:"):
        head = encoded.split(",", 1)[0]
        if "image/png" in head:
            return "image/png"
        if "image/webp" in head:
            return "image/webp"
        if "image/jpeg" in head:
            return "image/jpeg"
        encoded = encoded.split(",", 1)[-1]
    return "image/jpeg" if encoded.startswith("/9j/") else "image/png"


def _image_part(encoded: str) -> dict[str, Any]:
    """Monta a parte de imagem aceita pela API do Gemini.

    Args:
        encoded: imagem em base64, com ou sem prefixo `data:`.

    Returns:
        A parte `inline_data` com o mime type e os dados.
    """
    if encoded.startswith("data:"):
        head, _, data = encoded.partition(",")
        mime = head.split(";")[0].removeprefix("data:") or "image/png"
    else:
        mime = _media_type(encoded)
        data = encoded
    return {"inline_data": {"mime_type": mime, "data": data}}


def gemini_contents(messages) -> tuple[str | None, list[dict[str, Any]]]:
    """Separa a instrução de sistema e monta `contents` (papel `model` no lugar de `assistant`).

    Args:
        messages: mensagens do histórico.

    Returns:
        Tupla com o texto de sistema (ou `None`) e a lista de `contents`.
    """
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system.append(message.content)
            continue
        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"text": message.content})
        for image in message.images or []:
            parts.append(_image_part(image))
        if not parts:
            continue
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": parts})
    system_text = "\n\n".join(system) or None
    return system_text, contents


def gemini_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Converte o formato de ferramenta do Callidus (OpenAI) para `functionDeclarations`.

    Args:
        tools: ferramentas no formato OpenAI.

    Returns:
        A lista com as declarações de função, ou `None` quando não há ferramentas válidas.
    """
    if not tools:
        return None
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if tool.get("type") == "function" else tool
        name = function.get("name")
        if not name:
            continue
        declarations.append(
            {
                "name": name,
                "description": function.get("description") or "",
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return [{"functionDeclarations": declarations}] if declarations else None


class GeminiProvider(LLMProvider):
    """Gemini (`/v1beta/models/{model}:generateContent`). A API não é compatível com OpenAI:
    usa `contents`/`parts`, `x-goog-api-key` e `generationConfig`."""

    name = "gemini"
    supports_streaming = True
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

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
        models_cache_ttl: float = 300.0,
    ) -> None:
        """Configura o provedor e resolve a URL base e os cabeçalhos de autenticação.

        Args:
            base_url: URL base da API; por padrão, a URL pública do Gemini.
            model: modelo padrão usado quando o run não escolhe um.
            api_key: credencial enviada em `x-goog-api-key`.
            headers: cabeçalhos adicionais enviados em cada requisição.
            timeout: tempo limite das requisições, em segundos.
            max_retries: número de retentativas em falha transitória.
            allow_private_hosts: permite endereços privados (servidores locais).
            verify_tls: valida o certificado TLS do servidor.
            models_cache_ttl: tempo de vida do cache de modelos, em segundos.

        Raises:
            ProviderError: quando a URL base é vazia.
        """
        resolved = base_url or self.default_base_url
        if not resolved:
            raise ProviderError("URL base é obrigatória para o provedor 'gemini'")
        self._http = HttpClientConfig(
            base_url=resolved,
            timeout=timeout,
            api_key=api_key,
            headers=dict(headers or {}),
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
            auth_header="x-goog-api-key",
            auth_scheme="",
        )
        self._base_url = self._http.resolved_base_url()
        self.default_model = model
        self._models_cache: list[str] | None = None
        self._models_cached_at = 0.0
        self._models_cache_ttl = max(0.0, models_cache_ttl)

    def capabilities(self) -> ProviderCapabilities:
        """Recursos declarados pelo provedor.

        Returns:
            As capacidades da API do Gemini.
        """
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
        """Cliente HTTP configurado para o provedor.

        Returns:
            Um `httpx.AsyncClient` com os mesmos parâmetros de transporte da configuração.
        """
        return httpx.AsyncClient(**client_kwargs(self._http))

    def _model_path(self, model_id: str) -> str:
        """Normaliza o identificador do modelo para o caminho da API.

        Args:
            model_id: identificador do modelo, com ou sem o prefixo `models/`.

        Returns:
            O identificador sem o prefixo.
        """
        return model_id.removeprefix("models/")

    async def list_models(self, *, force: bool = False) -> list[str]:
        """Lista os modelos disponíveis na API, com cache curto.

        Args:
            force: quando `True`, ignora o cache e consulta o servidor.

        Returns:
            A lista de identificadores de modelo.

        Raises:
            ProviderError: quando o servidor não pode ser consultado.
        """
        if not force and self._models_cache is not None:
            if time.monotonic() - self._models_cached_at <= self._models_cache_ttl:
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
        items = (data or {}).get("models") or []
        models = [self._model_path(item.get("name", "")) for item in items if item.get("name")]
        self._models_cache = models
        self._models_cached_at = time.monotonic()
        return models


    def _body(self, request: ChatCompletionRequest) -> dict:
        """Monta o corpo da requisição de inferência no formato da API do Gemini.

        Args:
            request: requisição do Callidus.

        Returns:
            O corpo JSON aceito pela API.
        """
        system, contents = gemini_contents(request.messages)
        generation = dict(request.profile.generation or {})
        generation.pop("think", None)
        config: dict[str, Any] = {}
        for source, target in (
            ("temperature", "temperature"),
            ("top_p", "topP"),
            ("top_k", "topK"),
            ("seed", "seed"),
            ("stop", "stopSequences"),
        ):
            if source in generation:
                config[target] = generation[source]
        max_tokens = generation.get("max_tokens") or generation.get("num_predict") or request.profile.output_reserve
        if max_tokens:
            config["maxOutputTokens"] = int(max_tokens)
        if request.response_format is not None:
            schema = request.response_format.get("schema") or request.response_format
            config["responseMimeType"] = "application/json"
            if isinstance(schema, dict):
                config["responseSchema"] = schema
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if config:
            body["generationConfig"] = config
        tools = gemini_tools(request.tools)
        if tools:
            body["tools"] = tools
        return body

    @staticmethod
    def _parse(data: dict[str, Any]) -> tuple[str, list[ToolCall] | None, str | None]:
        """Extrai texto, chamadas de função e motivo de término da resposta do Gemini.

        Args:
            data: corpo JSON devolvido pela API.

        Returns:
            Tupla com o texto, as chamadas de ferramenta (ou `None`) e o motivo de término.
        """
        parts: list[str] = []
        calls: list[ToolCall] = []
        candidates = (data or {}).get("candidates") or []
        finish: str | None = None
        if candidates:
            candidate = candidates[0]
            finish = candidate.get("finishReason")
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    parts.append(part["text"])
                call = part.get("functionCall")
                if call and call.get("name"):
                    arguments = call.get("args")
                    calls.append(
                        ToolCall(
                            id=call.get("id"),
                            name=call["name"],
                            arguments=arguments if isinstance(arguments, dict) else {},
                        )
                    )
        return "".join(parts), (calls or None), finish

    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Executa uma inferência completa pela API do Gemini.

        Args:
            request: requisição do Callidus.

        Returns:
            A resposta normalizada do provedor.

        Raises:
            ProviderError: quando a chamada HTTP falha.
        """
        url = f"{self._base_url}/models/{self._model_path(request.profile.model_id)}:generateContent"
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
        content, tool_calls, finish = self._parse(data)
        usage = (data or {}).get("usageMetadata") or {}
        response = ChatCompletionResponse(
            content=content,
            raw=data,
            prompt_tokens_estimate=usage.get("promptTokenCount"),
            completion_tokens_estimate=usage.get("candidatesTokenCount"),
            tool_calls=tool_calls,
            finish_reason=finish,
            model=(data or {}).get("modelVersion"),
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def _chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """Executa uma inferência em streaming pela API do Gemini.

        Args:
            request: requisição do Callidus.
            on_delta: callback que recebe cada fragmento do texto.

        Returns:
            A resposta completa, montada ao final do stream.

        Raises:
            ProviderError: quando o stream falha ou traz um bloco inválido.
        """
        model = self._model_path(request.profile.model_id)
        url = f"{self._base_url}/models/{model}:streamGenerateContent?alt=sse"
        body = self._body(request)
        parts: list[str] = []
        usage: dict = {}
        finish: str | None = None
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
                            data = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                f"Falha na inferência {self.name} (stream): bloco inválido ({exc})"
                            ) from exc
                        if data.get("error"):
                            error = data["error"]
                            message = error.get("message") if isinstance(error, dict) else str(error)
                            raise ProviderError(f"Falha na inferência {self.name}: {message}")
                        text, _, candidate_finish = self._parse(data)
                        if text:
                            parts.append(text)
                            on_delta(text)
                        finish = candidate_finish or finish
                        if data.get("usageMetadata"):
                            usage = data["usageMetadata"]
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência {self.name}: {exc}") from exc
        content = "".join(parts)
        response = ChatCompletionResponse(
            content=content,
            raw={"candidates": [{"content": {"parts": [{"text": content}]}, "finishReason": finish}], "usageMetadata": usage},
            prompt_tokens_estimate=usage.get("promptTokenCount"),
            completion_tokens_estimate=usage.get("candidatesTokenCount"),
            finish_reason=finish,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response
