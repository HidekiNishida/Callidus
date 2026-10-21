"""
Arquivo: src/agent/orchestrator/narration.py
Nome: narration.py
Propósito: explicações curtas do que o orquestrador decidiu, sem uma inferência extra.
Responsabilidade: camada de aplicação — texto do feed a partir de fatos já registrados.
Componentes: explain_quality, safe_explanation.
Dependências: agent.observability.sanitize.
Observações: se o texto não puder ser montado, a função devolve vazio e a execução segue.
"""

from __future__ import annotations

from typing import Any

from agent.observability.sanitize import redact_text

_CATEGORIES = {"activity", "decision", "result", "alert", "error"}


def safe_explanation(text: str | None, *, limit: int = 400) -> str:
    """Limpa e trunca uma explicação antes de publicá-la.

    Args:
        text: frase candidata.
        limit: tamanho máximo.

    Returns:
        O texto redigido, ou vazio quando não há o que dizer.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    try:
        cleaned = redact_text(cleaned)
    except Exception:
        return ""
    return cleaned[:limit]


def explain_quality(contract: dict[str, Any] | None) -> str:
    """Resume o contrato de qualidade em uma frase para o feed.

    Separa o que o usuário escreveu do que foi inferido como piso profissional.
    Não afirma que um critério já foi verificado.

    Args:
        contract: contrato de qualidade.

    Returns:
        A frase, ou vazio quando não há contrato.
    """
    if not isinstance(contract, dict):
        return ""
    explicit = contract.get("explicit") or []
    first = explicit[0].get("text") if explicit and isinstance(explicit[0], dict) else ""
    first = " ".join(str(first).split())[:140]
    effort = contract.get("effort") or "moderate"
    ceiling = contract.get("scope_ceiling") or "professional"
    inferred = [
        str(item.get("text"))
        for item in (contract.get("inferred") or [])
        if isinstance(item, dict) and item.get("text")
    ]
    if ceiling == "prototype":
        body = f"Vou tratar «{first}» como protótipo: demonstrar o pedido, sem infraestrutura extra."
    elif not inferred:
        body = f"Vou atender «{first}» como pedido {effort}, sem acrescentar critério de outro domínio."
    else:
        body = (
            f"O pedido é «{first}». Além disso, o piso desta entrega inclui: {inferred[0]}."
        )
    uncertainty = (contract.get("uncertainties") or [None])[0]
    if uncertainty:
        body = f"{body} Pendência: {uncertainty}."
    return safe_explanation(body)


def explanation_event(category: str, text: str, *, phase: str) -> dict[str, str] | None:
    """Payload do evento `work.explained`.

    Args:
        category: `activity`, `decision`, `result`, `alert` ou `error`.
        text: frase já redigida.
        phase: etapa do ciclo (`quality`, `plan`, `investigate`, `execute`).

    Returns:
        O payload, ou `None` quando a categoria ou o texto não servem.
    """
    cleaned = safe_explanation(text)
    if category not in _CATEGORIES or not cleaned:
        return None
    return {"category": category, "text": cleaned, "phase": phase[:40]}
