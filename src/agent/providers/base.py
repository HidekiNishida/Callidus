# src/agent/providers/base.py — contrato de provedores de inferência
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str
    images: list[str] | None = None
    # Historical do ciclo de ferramentas: a mensagem do assistente que pediu a ferramenta e a
    # mensagem de resultado. Sem as duas pontas o modelo não consegue continuar a conversa.
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    """Chamada de ferramenta pedida pelo modelo. `arguments` é o objeto já decodificado."""

    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProviderCapabilities(BaseModel):
    """O que o provedor realmente oferece. Recurso ausente é declarado, nunca simulado."""

    streaming: bool = False
    tools: bool = False
    # O provedor sabe manter a conversa de ferramentas (mensagem do assistente com a chamada e
    # mensagem de resultado). Sem isso, o modelo não pode inspecionar o projeto antes de responder.
    tool_loop: bool = False
    structured_output: bool = False
    vision: bool = False
    model_listing: bool = True
    usage_reporting: bool = True
    cancellation: bool = True


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


class ModelProfile(BaseModel):
    model_id: str
    context_limit: int = 8192
    input_budget: int = 6000
    output_reserve: int = 1024
    supports_tools: bool = False
    supports_vision: bool = False
    generation: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionRequest(BaseModel):
    messages: list[ChatMessage]
    profile: ModelProfile
    response_format: dict[str, Any] | None = None
    stream: bool = False
    # Ferramentas no formato OpenAI (`{"type": "function", "function": {...}}`).
    # Provedores sem suporte recusam com `ProviderNotSupportedError` — nada é descartado em silêncio.
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None


class ChatCompletionResponse(BaseModel):
    content: str
    raw: dict[str, Any] | None = None
    prompt_tokens_estimate: int | None = None
    completion_tokens_estimate: int | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    model: str | None = None
    # Raciocínio do modelo (canal `thinking` do Ollama). Serve para diagnosticar resposta vazia:
    # sem ele não há como saber se o modelo gastou o orçamento pensando ou pediu uma ferramenta.
    reasoning: str | None = None


class ProviderError(RuntimeError):
    """Falha do provedor. A mensagem carrega o motivo em português para a classificação de falhas."""


class ProviderConnectionError(ProviderError):
    """O servidor não respondeu (recusou a conexão, DNS falhou, host inacessível)."""


class ProviderTimeoutError(ProviderError):
    """A operação estourou o tempo limite configurado."""


class ProviderAuthError(ProviderError):
    """Credencial ausente, inválida ou sem permissão."""


class ProviderRateLimitError(ProviderError):
    """Limite de uso do provedor atingido (HTTP 429)."""


class ProviderConfigError(ProviderError):
    """Configuração inválida ou incompleta do provedor (URL, tipo, credencial)."""


class ProviderNotSupportedError(ProviderError):
    """O recurso pedido não existe na API deste provedor."""


class ProviderResponseError(ProviderError):
    """A resposta chegou, mas não pôde ser lida (JSON inválido, corpo inesperado)."""


class LLMProvider(ABC):
    name: str
    # Só é `True` em provedores que recebem a resposta em fragmentos do servidor (`chat_streaming`).
    supports_streaming: bool = False
    # Modelo padrão do provedor (usado quando o run não escolhe um modelo).
    default_model: str | None = None

    def capabilities(self) -> ProviderCapabilities:
        """Recursos declarados pelo provedor. O padrão assume apenas o que a classe implementa."""
        return ProviderCapabilities(streaming=self.supports_streaming)

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Inferência. Toda chamada passa pelo executor compartilhado do processo: é aqui que
        a exclusividade de inferência ativa é garantida, e não por convenção dos chamadores.

        O provedor concreto implementa `_chat`; quem chama continua usando `chat`.
        """
        from agent.services.executor import get_executor

        executor = get_executor()
        slot = await executor.acquire(
            purpose="chat",
            provider=self.name,
            model=request.profile.model_id,
        )
        try:
            response = await self._chat(request)
        except BaseException as exc:
            executor.release(error=exc, slot=slot)
            raise
        executor.release(slot=slot)
        return response

    @abstractmethod
    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Implementação da inferência pelo provedor. Sempre chamada por `chat`."""
        raise NotImplementedError

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """Recebe a resposta em fragmentos, chama `on_delta` a cada um e devolve a resposta completa (com uso
        de tokens). Provedor sem streaming real não implementa: quem chama usa `chat`."""
        from agent.services.executor import get_executor

        executor = get_executor()
        slot = await executor.acquire(
            purpose="chat_streaming",
            provider=self.name,
            model=request.profile.model_id,
        )
        try:
            response = await self._chat_streaming(request, on_delta)
        except BaseException as exc:
            executor.release(error=exc, slot=slot)
            raise
        executor.release(slot=slot)
        return response

    async def _chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """Implementação do streaming pelo provedor. Sempre chamada por `chat_streaming`."""
        raise ProviderNotSupportedError(f"O provedor '{self.name}' não transmite a resposta em fragmentos.")


    async def health_check(self) -> ProviderHealth:
        """Verificação de conectividade barata: lista os modelos do servidor, sem inferência.

        Nunca levanta: servidor fora do ar, credencial inválida ou timeout viram
        `ok=False` com o motivo — o diagnóstico não pode virar erro 500.
        """
        import time

        started = time.monotonic()
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                detail=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # pragma: no cover - rede inesperada
            return ProviderHealth(
                provider=self.name,
                ok=False,
                detail=str(exc) or type(exc).__name__,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return ProviderHealth(
            provider=self.name,
            ok=True,
            detail="ok",
            models=models,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def close(self) -> None:
        """Libera recursos do provedor (nenhum por padrão)."""
        return None
