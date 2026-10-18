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


class ChatCompletionResponse(BaseModel):
    content: str
    raw: dict[str, Any] | None = None
    prompt_tokens_estimate: int | None = None
    completion_tokens_estimate: int | None = None


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str
    # Só é `True` em provedores que recebem a resposta em fragmentos do servidor (`chat_streaming`).
    supports_streaming: bool = False

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise NotImplementedError

    async def chat_streaming(
        self, request: ChatCompletionRequest, on_delta: Callable[[str], None]
    ) -> ChatCompletionResponse:
        """Recebe a resposta em fragmentos, chama `on_delta` a cada um e devolve a resposta completa (com uso
        de tokens). Provedores sem streaming real não implementam: quem chama usa `chat`."""
        raise NotImplementedError
