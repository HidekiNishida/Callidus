"""
Arquivo: src/agent/orchestrator/inference_usage.py
Nome: inference_usage.py
Propósito: classificar e somar o uso de tokens de uma inferência sem tratar ausência como zero.
Responsabilidade: camada de aplicação — leitura do uso informado pelo provedor e da estimativa local.
Componentes: ParsedUsage, usage_from_response, fold_usage, spend_of, estimate_messages, estimate_cost.
Dependências: agent.context.budget, agent.providers.base.
Observações: cache e raciocínio ficam de fora do total de entrada e de saída.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context.budget import estimate_tokens
from agent.providers.base import ChatCompletionResponse, ChatMessage


def _opt_int(value: Any) -> int | None:
    """Converte um número informado pelo provedor, preservando a ausência.

    Args:
        value: valor bruto; `None` e texto vazio continuam ausentes.

    Returns:
        O inteiro não negativo, ou `None` quando o provedor não informou o campo.
    """
    if value is None or value is False or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def provider_details(raw: dict[str, Any] | None) -> dict[str, int | None]:
    """Lê cache e raciocínio do corpo bruto, sem inventar o que o provedor não mandou.

    Args:
        raw: corpo devolvido pela API do provedor.

    Returns:
        Contagens opcionais de raciocínio, cache de leitura e cache de escrita.
    """
    body = raw or {}
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    completion_details = (
        usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    )
    gemini = body.get("usageMetadata") if isinstance(body.get("usageMetadata"), dict) else {}
    reasoning = _opt_int(completion_details.get("reasoning_tokens"))
    if reasoning is None:
        reasoning = _opt_int(usage.get("reasoning_tokens"))
    if reasoning is None:
        reasoning = _opt_int(gemini.get("thoughtsTokenCount"))
    cache_read = _opt_int(prompt_details.get("cached_tokens"))
    if cache_read is None:
        cache_read = _opt_int(usage.get("cache_read_input_tokens"))
    if cache_read is None:
        cache_read = _opt_int(gemini.get("cachedContentTokenCount"))
    cache_write = _opt_int(usage.get("cache_creation_input_tokens"))
    return {
        "reasoning_tokens": reasoning,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


@dataclass
class ParsedUsage:
    """Uso de uma resposta, com a qualidade da medição explícita.

    Atributos:
        measurement: `exact`, `estimate`, `partial` ou `unavailable`.
        prompt_tokens: entrada informada; `None` quando o provedor não mandou.
        completion_tokens: saída informada; `None` quando o provedor não mandou.
        reasoning_tokens: raciocínio, quando o provedor o separa.
        cache_read_tokens: entrada atendida por cache, quando informada.
        cache_write_tokens: escrita de cache, quando informada.
        estimated_prompt_tokens: estimativa local da entrada, anterior à resposta.
        estimated_completion_tokens: estimativa local da saída reservada.
        status: `completed`, `truncated`, `failed` ou `timeout`.
    """

    measurement: str
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    estimated_prompt_tokens: int | None
    estimated_completion_tokens: int | None
    status: str


def usage_from_response(
    response: ChatCompletionResponse,
    *,
    usage_reporting: bool,
    estimated_prompt: int | None,
    estimated_completion: int | None,
    failed: bool = False,
    timeout: bool = False,
) -> ParsedUsage:
    """Classifica a resposta. Número ausente continua ausente; zero informado continua zero.

    Args:
        response: resposta do provedor.
        usage_reporting: o provedor declara informar uso real.
        estimated_prompt: estimativa local da entrada, feita antes da chamada.
        estimated_completion: reserva local de saída.
        failed: a chamada terminou em erro.
        timeout: a chamada estourou o tempo.

    Returns:
        O uso classificado. Cache e raciocínio não são somados à entrada nem à saída.
    """
    prompt = _opt_int(getattr(response, "prompt_tokens_estimate", None))
    completion = _opt_int(getattr(response, "completion_tokens_estimate", None))
    details = provider_details(getattr(response, "raw", None))
    finish = getattr(response, "finish_reason", None)
    if timeout:
        status = "timeout"
    elif failed:
        status = "failed"
    elif finish in {"length", "max_tokens", "MAX_TOKENS"}:
        status = "truncated"
    else:
        status = "completed"
    if prompt is None and completion is None:
        measurement = "unavailable"
    elif not usage_reporting:
        measurement = "estimate"
    elif prompt is None or completion is None:
        measurement = "partial"
    else:
        measurement = "exact"
    return ParsedUsage(
        measurement=measurement,
        prompt_tokens=prompt,
        completion_tokens=completion,
        reasoning_tokens=details["reasoning_tokens"],
        cache_read_tokens=details["cache_read_tokens"],
        cache_write_tokens=details["cache_write_tokens"],
        estimated_prompt_tokens=estimated_prompt,
        estimated_completion_tokens=estimated_completion,
        status=status,
    )


def estimate_messages(messages: list[ChatMessage]) -> int:
    """Estima o tamanho da entrada a partir do texto que será enviado.

    Args:
        messages: mensagens da requisição.

    Returns:
        A estimativa local, em tokens. Mensagem vazia contribui zero de verdade.
    """
    total = 0
    for message in messages:
        total += estimate_tokens(message.content or "") if message.content else 0
        if message.tool_calls:
            total += estimate_tokens(str(message.tool_calls))
    return total


def estimate_cost(
    prices: dict[str, Any] | None,
    provider: str,
    prompt: int | None,
    completion: int | None,
) -> tuple[float | None, str]:
    """Estima o custo só quando há preço configurado e tokens conhecidos.

    Args:
        prices: tabela `preços por milhão` do run, por nome de provedor.
        provider: provedor da chamada.
        prompt: tokens de entrada conhecidos.
        completion: tokens de saída conhecidos.

    Returns:
        O custo em dólares e a qualidade (`exact`, `partial` ou `unavailable`).
        Sem tabela de preço, o custo é indisponível — não é zero.
    """
    table = (prices or {}).get(provider)
    if not isinstance(table, dict):
        return None, "unavailable"
    prompt_price = table.get("prompt_per_million")
    completion_price = table.get("completion_per_million")
    cost = 0.0
    priced = 0
    expected = 0
    if prompt is not None:
        expected += 1
        if prompt_price is not None:
            cost += prompt * float(prompt_price) / 1_000_000
            priced += 1
    if completion is not None:
        expected += 1
        if completion_price is not None:
            cost += completion * float(completion_price) / 1_000_000
            priced += 1
    if priced == 0 or expected == 0:
        return None, "unavailable"
    quality = "exact" if priced == expected else "partial"
    return round(cost, 8), quality


def _known(value: int | None, fallback: int | None) -> tuple[int, str] | None:
    """Escolhe o número do provedor ou, na falta dele, a estimativa local.

    Args:
        value: contagem informada.
        fallback: estimativa correspondente.

    Returns:
        O par (quantidade, qualidade), ou `None` quando os dois faltam.
    """
    if value is not None:
        return value, "reported"
    if fallback is not None:
        return fallback, "estimate"
    return None


def spend_of(row: Any) -> tuple[int, str]:
    """Gasto de um registro para o controle de orçamento.

    Usa o número do provedor quando existe. Quando não existe, usa a estimativa
    guardada na mesma linha. Não soma cache nem raciocínio de novo.

    Args:
        row: registro de inferência ou objeto com os mesmos campos.

    Returns:
        A quantidade considerada e a qualidade (`exact`, `estimate`, `partial`, `unavailable`).
    """
    prompt = _known(getattr(row, "prompt_tokens", None), getattr(row, "estimated_prompt_tokens", None))
    completion = _known(getattr(row, "completion_tokens", None), getattr(row, "estimated_completion_tokens", None))
    parts = [item for item in (prompt, completion) if item is not None]
    if not parts:
        return 0, "unavailable"
    qualities = {item[1] for item in parts}
    if qualities == {"reported"} and getattr(row, "measurement", None) == "exact":
        quality = "exact"
    elif qualities == {"estimate"}:
        quality = "estimate"
    else:
        quality = "partial"
    return sum(item[0] for item in parts), quality


def fold_usage(rows: list[Any]) -> dict[str, Any]:
    """Soma registros individuais. Campo ausente não entra como zero.

    Args:
        rows: registros de inferência.

    Returns:
        Totais separados, com a qualidade de cada um e a lista do que faltou.
    """

    def accumulate(attr: str) -> dict[str, Any]:
        """Soma um campo opcional, contando quantas linhas não o informaram."""
        known: list[int] = []
        missing = 0
        for row in rows:
            value = getattr(row, attr, None)
            if value is None:
                missing += 1
            else:
                known.append(int(value))
        if not rows:
            measurement = "unavailable"
        elif missing == 0:
            measurement = "exact"
        elif known:
            measurement = "partial"
        else:
            measurement = "unavailable"
        return {
            "value": sum(known) if known else None,
            "measurement": measurement,
            "missing": missing,
        }

    spend_values: list[int] = []
    spend_notes: list[str] = []
    for row in rows:
        amount, quality = spend_of(row)
        if quality == "unavailable":
            continue
        spend_values.append(amount)
        spend_notes.append(quality)
    if not spend_values:
        spend_measurement = "unavailable"
        spend_value = None
    elif spend_notes and all(item == "exact" for item in spend_notes) and len(spend_values) == len(rows):
        spend_measurement = "exact"
        spend_value = sum(spend_values)
    elif all(item == "estimate" for item in spend_notes):
        spend_measurement = "estimate"
        spend_value = sum(spend_values)
    else:
        spend_measurement = "partial"
        spend_value = sum(spend_values)
    return {
        "calls": len(rows),
        "prompt": accumulate("prompt_tokens"),
        "completion": accumulate("completion_tokens"),
        "reasoning": accumulate("reasoning_tokens"),
        "cache_read": accumulate("cache_read_tokens"),
        "cache_write": accumulate("cache_write_tokens"),
        "estimated_prompt": accumulate("estimated_prompt_tokens"),
        "estimated_completion": accumulate("estimated_completion_tokens"),
        "spend": {"value": spend_value, "measurement": spend_measurement},
        "failed": sum(1 for row in rows if getattr(row, "status", "") in {"failed", "timeout"}),
        "duration_ms": sum(int(getattr(row, "duration_ms", 0) or 0) for row in rows) or None,
    }
