# src/agent/providers/base.py — contrato de provedores de inferência
from __future__ import annotations

from abc import ABC, abstractmethod
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

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise NotImplementedError

    async def chat_stream(self, request: ChatCompletionRequest):
        """Stream chat completion chunks. Default implementation falls back to chat."""
        # Non-streaming provider: yield the whole response as one chunk.
        response = await self.chat(request)
        yield response.content or ""
