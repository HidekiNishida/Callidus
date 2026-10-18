# src/agent/providers/observed.py — chamada ao modelo acompanhada em tempo real
from __future__ import annotations

import asyncio
import time
import uuid

from agent.observability import current, emit
from agent.observability.batching import DeltaBatcher
from agent.providers.base import ChatCompletionRequest, ChatCompletionResponse, LLMProvider

_PARTIAL_KEEP = 4_000


async def observed_chat(
    provider: LLMProvider,
    request: ChatCompletionRequest,
    *,
    purpose: str,
    stream: bool = True,
) -> ChatCompletionResponse:
    """Chama o modelo emitindo `agent.started`, fragmentos (`agent.output.delta`) quando o provedor transmite de
    verdade, e `agent.output.completed` com a resposta inteira, ou `agent.output.failed` em erro/cancelamento.
    Provedor sem streaming: `streaming: false` e estado `waiting_full_response`; nenhum fragmento é inventado.
    Fora de uma run, só chama o provedor."""
    if current() is None:
        return await provider.chat(request)
    streaming = bool(stream and getattr(provider, "supports_streaming", False))
    output_id = uuid.uuid4().hex[:12]
    model = request.profile.model_id
    started = time.monotonic()
    emit(
        "agent.started",
        {"output_id": output_id, "provider": provider.name, "model": model, "streaming": streaming, "purpose": purpose},
        commit=True,
    )
    emit("agent.status", {"output_id": output_id, "status": "waiting_first_token" if streaming else "waiting_full_response"})
    received: list[str] = []
    offset = 0

    def publish(text: str) -> None:
        nonlocal offset
        emit("agent.output.delta", {"output_id": output_id, "text": text, "offset": offset})
        offset += len(text)

    batcher = DeltaBatcher(publish)

    def on_delta(piece: str) -> None:
        received.append(piece)
        batcher.add(piece)

    def failed(error: str, *, cancelled: bool = False) -> None:
        batcher.flush()
        partial = "".join(received)
        emit(
            "agent.output.failed",
            {
                "output_id": output_id,
                "error": error,
                "cancelled": cancelled,
                "partial_chars": len(partial),
                "partial_tail": partial[-_PARTIAL_KEEP:],
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            commit=True,
        )

    try:
        if streaming:
            response = await provider.chat_streaming(request, on_delta)
        else:
            response = await provider.chat(request)
    except asyncio.CancelledError:
        failed("cancelado", cancelled=True)
        raise
    except Exception as exc:
        failed(str(exc) or type(exc).__name__)
        raise
    batcher.flush()
    content = response.content or ""
    emit(
        "agent.output.completed",
        {
            "output_id": output_id,
            "content": content,
            "chars": len(content),
            "streamed": streaming,
            "deltas": batcher.batches,
            "prompt_tokens": getattr(response, "prompt_tokens_estimate", None),
            "completion_tokens": getattr(response, "completion_tokens_estimate", None),
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return response
