"""
Arquivo: src/agent/providers/base.py
Nome: base.py
Propósito: definir o contrato comum dos provedores de inferência do Callidus.
Responsabilidade: camada de domínio — tipos de mensagens, requisição, resposta, capacidades e erros.
Componentes: ChatMessage, ToolCall, ProviderCapabilities, ProviderHealth, ModelProfile, ChatCompletionRequest, ChatCompletionResponse, LLMProvider e a taxonomia de ProviderError.
Dependências: pydantic.
Observações: recurso ausente é declarado, nunca simulado; a exclusividade de inferência é garantida pelo executor.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Mensagem do histórico de conversa enviada ao modelo.

    Atributos:
        role: papel da mensagem (`system`, `user`, `assistant`, `tool`).
        content: texto da mensagem.
        images: imagens anexadas, em base64, quando o modelo aceita visão.
        tool_calls: chamadas de ferramenta pedidas pelo assistente.
        tool_call_id: identificador da chamada a que esta mensagem responde.
    """

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
    """Diagnóstico de conectividade de um provedor.

    Atributos:
        provider: nome do provedor avaliado.
        ok: indica se o servidor respondeu.
        detail: detalhe do resultado ou da falha.
        models: modelos listados pelo servidor.
        latency_ms: latência da verificação, em milissegundos.
    """

    provider: str
    ok: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


class ModelProfile(BaseModel):
    """Perfil do modelo usado para dimensionar o contexto e as requisições.

    Atributos:
        model_id: identificador do modelo.
        context_limit: janela de contexto total do modelo.
        input_budget: orçamento de tokens reserved para a entrada.
        output_reserve: tokens reservados para a resposta.
        supports_tools: indica se o modelo aceita chamadas de ferramenta.
        supports_vision: indica se o modelo aceita imagens.
        generation: parâmetros extras de geração (temperatura, top_p, etc.).
    """

    model_id: str
    context_limit: int = 8192
    input_budget: int = 6000
    output_reserve: int = 1024
    supports_tools: bool = False
    supports_vision: bool = False
    generation: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionRequest(BaseModel):
    """Requisição de inferência enviada ao provedor.

    Atributos:
        messages: histórico da conversa.
        profile: perfil do modelo que vai responder.
        response_format: formato de resposta pedido (ex.: JSON schema).
        stream: indica se o cliente quer os fragmentos durante a geração.
        tools: ferramentas oferecidas, no formato OpenAI.
        tool_choice: política de escolha de ferramenta.
    """

    messages: list[ChatMessage]
    profile: ModelProfile
    response_format: dict[str, Any] | None = None
    stream: bool = False
    # Ferramentas no formato OpenAI (`{"type": "function", "function": {...}}`).
    # Provedores sem suporte recusam com `ProviderNotSupportedError` — nada é descartado em silêncio.
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None


class ChatCompletionResponse(BaseModel):
    """Resposta de inferência devolvida pelo provedor.

    Atributos:
        content: texto da resposta.
        raw: corpo bruto devolvido pela API do provedor.
        prompt_tokens_estimate: estimativa de tokens da entrada.
        completion_tokens_estimate: estimativa de tokens da saída.
        tool_calls: chamadas de ferramenta pedidas pelo modelo.
        finish_reason: motivo de término informado pelo provedor.
        model: modelo que respondeu.
        reasoning: canal de raciocínio do modelo, quando existe.
    """

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
    """Contrato do provedor de inferência: `chat`, `stream` e as capacidades declaradas."""
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
        """Lista os modelos disponíveis no servidor.

        Returns:
            A lista de identificadores de modelo.

        Raises:
            ProviderError: quando o servidor não pode ser consultado.
        """
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
        """Implementação da inferência pelo provedor. Sempre chamada por `chat`.

        Args:
            request: requisição de inferência.

        Returns:
            A resposta do provedor.

        Raises:
            ProviderError: quando a inferência falha.
        """
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
        """Implementação do streaming pelo provedor. Sempre chamada por `chat_streaming`.

        Args:
            request: requisição de inferência.
            on_delta: callback que recebe cada fragmento do texto.

        Returns:
            A resposta completa ao final do streaming.

        Raises:
            ProviderNotSupportedError: quando o provedor não transmite a resposta em fragmentos.
        """
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
