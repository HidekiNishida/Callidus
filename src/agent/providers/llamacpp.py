"""
Arquivo: src/agent/providers/llamacpp.py
Nome: llamacpp.py
Propósito: integrar o agente com o servidor llama.cpp pela API compatível com OpenAI.
Responsabilidade: camada de infraestrutura — inferência, streaming e listagem de modelos no llama-server.
Componentes: LlamaCppProvider, read_api_key_file.
Dependências: agent.providers.base, agent.providers.http, httpx.
Observações: a chave pode vir de arquivo (`--api-key-file`); o que o servidor não devolve não é prometido.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

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


def _data_url(encoded: str) -> str:
    """Monta a URL de dados de uma imagem base64.

    Args:
        encoded: imagem em base64.

    Returns:
        A URL de dados com o tipo de mídia deduzido.
    """
    mime = "image/jpeg" if encoded.startswith("/9j/") else "image/png"
    return f"data:{mime};base64,{encoded}"


def _openai_message(message) -> dict:
    """Mesma tradução da API compatível com OpenAI (inclusive a conversa de ferramentas).

    Args:
        message: mensagem do histórico.

    Returns:
        O dicionário aceito pelo endpoint do llama-server.
    """
    from agent.providers.openai_compatible import openai_message

    return openai_message(message)


def _tool_calls(message: dict) -> list[ToolCall] | None:
    """Extrai as chamadas de ferramenta de uma mensagem do llama-server.

    Args:
        message: mensagem devolvida pelo servidor.

    Returns:
        A lista de chamadas, ou `None` quando a mensagem não pede ferramenta.
    """
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


def read_api_key_file(path: str) -> str:
    """`llama-server --api-key-file` guarda a chave em arquivo; o conteúdo vira o bearer token.

    Args:
        path: caminho do arquivo de credencial.

    Returns:
        A credencial lida, sem espaços nas pontas.

    Raises:
        ProviderError: quando o arquivo não pode ser lido ou está vazio.
    """
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProviderError(f"não foi possível ler o arquivo de credencial: {exc}") from exc
    if not token:
        raise ProviderError("arquivo de credencial está vazio")
    return token


class LlamaCppProvider(LLMProvider):
    """`llama-server` local ou remoto. Usa a API compatível com OpenAI (`/v1/chat/completions`),
    que o servidor expõe por padrão; recursos que a versão do servidor não implementa não são
    prometidos — o que o servidor não devolve simplesmente não aparece na resposta."""

    name = "llamacpp"
    supports_streaming = True

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        *,
        api_key: str | None = None,
        api_key_file: str | None = None,
        headers: dict[str, str] | None = None,
        max_retries: int = 1,
        allow_private_hosts: bool = True,
        verify_tls: bool = True,
        default_model: str | None = None,
    ) -> None:
        """Configura o provedor com a URL do llama-server e a credencial.

        Args:
            base_url: URL base do servidor.
            timeout: tempo limite das requisições, em segundos.
            api_key: credencial de autenticação.
            api_key_file: arquivo com a credencial, usado quando `api_key` não é informada.
            headers: cabeçalhos adicionais enviados em cada requisição.
            max_retries: número de retentativas em falha transitória.
            allow_private_hosts: permite endereços privados (servidores locais).
            verify_tls: valida o certificado TLS do servidor.
            default_model: modelo padrão usado quando o run não escolhe um.

        Raises:
            ProviderError: quando o arquivo de credencial não pode ser lido.
            ProviderConfigError: quando a URL base é inválida.
        """
        key = api_key
        if not key and api_key_file:
            key = read_api_key_file(api_key_file)
        self._http = HttpClientConfig(
            base_url=base_url,
            timeout=timeout,
            api_key=key,
            headers=dict(headers or {}),
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
        )
        self._base_url = self._http.resolved_base_url()
        self._timeout = timeout
        self.default_model = default_model

    def capabilities(self) -> ProviderCapabilities:
        """Recursos declarados pelo provedor.

        Returns:
            As capacidades do endpoint compatível com OpenAI do llama-server.
        """
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
        """Cliente HTTP configurado para o provedor.

        Returns:
            Um `httpx.AsyncClient` com os mesmos parâmetros de transporte da configuração.
        """
        return httpx.AsyncClient(**client_kwargs(self._http))

    async def list_models(self) -> list[str]:
        """Lista os modelos expostos pelo llama-server.

        Returns:
            A lista de identificadores de modelo.

        Raises:
            ProviderError: quando o servidor não pode ser consultado.
        """
        url = f"{self._base_url}/v1/models"
        try:
            async with self._client() as client:
                data = await get_json(
                    client,
                    url,
                    label="llama.cpp",
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"llama.cpp server indisponível: {exc}") from exc
        items = (data or {}).get("data") or []
        return [item.get("id", "") for item in items if item.get("id")]


    def _body(self, request: ChatCompletionRequest) -> dict:
        """Monta o corpo da requisição de inferência no formato do llama-server.

        Args:
            request: requisição do Callidus.

        Returns:
            O corpo JSON aceito pelo endpoint.
        """
        body = {
            "model": request.profile.model_id,
            "messages": [_openai_message(m) for m in request.messages],
            "max_tokens": request.profile.output_reserve,
            **request.profile.generation,
        }
        if request.response_format is not None:
            body["response_format"] = request.response_format
        if request.tools:
            body["tools"] = request.tools
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice
        return body

    async def _chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """`stream: true` no endpoint OpenAI: eventos `data: {...}` com `choices[0].delta.content` até `[DONE]`;
        o uso de tokens vem no último bloco quando o servidor suporta `include_usage`.

        Args:
            request: requisição do Callidus.
            on_delta: callback que recebe cada fragmento do texto.

        Returns:
            A resposta completa, montada ao final do stream.

        Raises:
            ProviderError: quando o stream falha, traz um bloco inválido ou termina antes do fim.
        """
        url = f"{self._base_url}/v1/chat/completions"
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
                    label="llama.cpp",
                    secrets=self._http.secrets(),
                ):
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        done = True
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(
                            f"Falha na inferência llama.cpp (stream): bloco inválido ({exc})"
                        ) from exc
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
            finish_reason=finish,
        )
        from agent.orchestrator.usage import remember_usage

        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response

    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Executa uma inferência completa pelo llama-server.

        Args:
            request: requisição do Callidus.

        Returns:
            A resposta normalizada do provedor.

        Raises:
            ProviderError: quando a chamada HTTP falha.
        """
        url = f"{self._base_url}/v1/chat/completions"
        body = self._body(request)

        try:
            async with self._client() as client:
                data = await post_json(
                    client,
                    url,
                    body,
                    label="llama.cpp",
                    secrets=self._http.secrets(),
                    max_retries=self._http.max_retries,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha na inferência llama.cpp: {exc}") from exc

        choices = (data or {}).get("choices") or []
        content = ""
        tool_calls: list[ToolCall] | None = None
        finish: str | None = None
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            tool_calls = _tool_calls(message)
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
