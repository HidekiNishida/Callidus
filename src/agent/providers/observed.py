"""
Arquivo: src/agent/providers/observed.py
Nome: observed.py
Propósito: envolver a chamada ao modelo para que ela seja acompanhada em tempo real pelos eventos.
Responsabilidade: camada de aplicação — emissão dos eventos de início, fragmentos e desfecho da inferência.
Componentes: observed_chat.
Dependências: agent.observability, agent.observability.batching, agent.providers.base.
Observações: provedor sem streaming não inventa fragmentos: marca `streaming: false` e publica a resposta inteira.
"""
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
    Fora de uma run, só chama o provedor.

    Args:
        provider: provedor que faz a inferência.
        request: requisição do Callidus.
        purpose: finalidade da chamada, usada nos eventos.
        stream: quando `True`, usa streaming se o provedor oferecer.

    Returns:
        A resposta do provedor.

    Raises:
        Exception: qualquer erro do provedor é propagado depois de emitir o evento de falha.
    """
    if request.purpose is None:
        # A finalidade viaja na requisição: o provedor escolhe padrões de geração por ela.
        request = request.model_copy(update={"purpose": purpose})
    obs = current()
    if obs is None:
        return await provider.chat(request)
    from agent.orchestrator.budget_gate import (
        BudgetExhausted,
        assess_inference,
        mark_pressure,
    )
    from agent.orchestrator.inference_usage import estimate_messages, usage_from_response
    from agent.orchestrator.ledger import record_inference

    estimated_prompt = estimate_messages(request.messages)
    estimated_completion = int(request.profile.output_reserve or 0)
    decision = assess_inference(
        obs.session,
        obs.run_id,
        purpose=purpose,
        estimated_prompt=estimated_prompt,
        estimated_completion=estimated_completion,
        provider=getattr(provider, "name", "") or "",
    )
    if decision.action == "pause":
        raise BudgetExhausted(decision)
    if decision.action in {"reduce", "warn"}:
        mark_pressure(obs.session, obs.task_id, "reduce" if decision.action == "reduce" else "elevated")
    streaming = bool(stream and getattr(provider, "supports_streaming", False))
    output_id = uuid.uuid4().hex[:12]
    model = request.profile.model_id
    started = time.monotonic()
    if decision.action == "reduce":
        emit("budget.pressure", {"level": decision.level, "purpose": purpose})
    emit(
        "agent.started",
        {"output_id": output_id, "provider": provider.name, "model": model, "streaming": streaming, "purpose": purpose},
        commit=True,
    )
    emit("agent.status", {"output_id": output_id, "status": "waiting_first_token" if streaming else "waiting_full_response"})
    received: list[str] = []
    offset = 0

    def publish(text: str) -> None:
        """Publica um fragmento do texto recebido, com o deslocamento acumulado.

        Args:
            text: trecho recebido do modelo.
        """
        nonlocal offset
        emit("agent.output.delta", {"output_id": output_id, "text": text, "offset": offset})
        offset += len(text)

    batcher = DeltaBatcher(publish)

    def on_delta(piece: str) -> None:
        """Acumula um fragmento e agenda sua publicação em lote.

        Args:
            piece: trecho recebido do modelo.
        """
        received.append(piece)
        batcher.add(piece)

    def failed(error: str, *, cancelled: bool = False) -> None:
        """Publica o desfecho de falha, preservando o texto parcial recebido.

        Args:
            error: mensagem do erro.
            cancelled: quando `True`, marca a falha como cancelamento.
        """
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

    def _account(response: ChatCompletionResponse | None, *, failed_call: bool = False, timeout: bool = False, error: str = "") -> None:
        """Grava a inferência assim que a resposta ou a falha existe.

        Args:
            response: resposta do provedor, quando chegou.
            failed_call: a chamada não produziu resposta utilizável.
            timeout: o provedor estourou o tempo.
            error: motivo curto, sem o texto do prompt.
        """
        reporting = False
        capabilities = getattr(provider, "capabilities", None)
        if callable(capabilities):
            try:
                reporting = bool(capabilities().usage_reporting)
            except Exception:
                reporting = False
        if response is None:
            parsed_prompt = None
            parsed_completion = None
            reasoning = cache_read = cache_write = None
            measurement = "unavailable"
            status = "timeout" if timeout else "failed"
            finish = None
        else:
            parsed = usage_from_response(
                response,
                usage_reporting=reporting,
                estimated_prompt=estimated_prompt,
                estimated_completion=estimated_completion,
                failed=failed_call,
                timeout=timeout,
            )
            parsed_prompt = parsed.prompt_tokens
            parsed_completion = parsed.completion_tokens
            reasoning = parsed.reasoning_tokens
            cache_read = parsed.cache_read_tokens
            cache_write = parsed.cache_write_tokens
            measurement = parsed.measurement
            status = parsed.status
            finish = getattr(response, "finish_reason", None)
        raw = getattr(response, "raw", None) if response is not None else None
        # Decisões do adaptador (janela pedida, saturação, correções de formato): é o que
        # permite dizer, depois, se uma resposta ruim veio de um prompt cortado pelo servidor.
        adapter_meta = raw.get("callidus") if isinstance(raw, dict) and isinstance(raw.get("callidus"), dict) else None
        from agent.orchestrator.inference_usage import estimate_cost
        from agent.persistence.models import ExecutionRunModel

        run = obs.session.get(ExecutionRunModel, obs.run_id)
        prices = (run.config_json or {}).get("prices") if run is not None and isinstance(run.config_json, dict) else {}
        cost, cost_quality = estimate_cost(prices if isinstance(prices, dict) else {}, provider.name, parsed_prompt, parsed_completion)
        try:
            record_inference(
                obs.session,
                idempotency_key=f"{obs.run_id}:{output_id}",
                run_id=obs.run_id,
                task_id=obs.task_id,
                project_id=obs.project_id,
                agent=obs.agent,
                purpose=purpose,
                provider=provider.name,
                model_id=model,
                status=status,
                failure_reason=(error or None),
                duration_ms=int((time.monotonic() - started) * 1000),
                measurement=measurement,
                prompt_tokens=parsed_prompt,
                completion_tokens=parsed_completion,
                reasoning_tokens=reasoning,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                estimated_prompt_tokens=estimated_prompt,
                estimated_completion_tokens=estimated_completion,
                cost_usd=cost,
                provider_meta_json={
                    "finish_reason": finish,
                    "cost_measurement": cost_quality,
                    "usage_reporting": reporting,
                    **({"adapter": adapter_meta} if adapter_meta else {}),
                },
            )
        except Exception:
            # A resposta já foi paga. Perder a linha é ruim; repetir a chamada ao modelo seria pior.
            return
        try:
            obs.session.commit()
        except Exception:
            return

    try:
        if streaming:
            response = await provider.chat_streaming(request, on_delta)
        else:
            response = await provider.chat(request)
    except asyncio.CancelledError:
        failed("cancelado", cancelled=True)
        _account(None, failed_call=True, error="cancelado")
        raise
    except Exception as exc:
        from agent.providers.base import ProviderTimeoutError

        failed(str(exc) or type(exc).__name__)
        _account(None, failed_call=True, timeout=isinstance(exc, ProviderTimeoutError), error=type(exc).__name__)
        raise
    batcher.flush()
    content = response.content or ""
    tool_calls = [call.model_dump() for call in (getattr(response, "tool_calls", None) or [])]
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
            "tool_calls": tool_calls,
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )
    _account(response)
    return response
