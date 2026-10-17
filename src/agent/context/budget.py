# src/agent/context/budget.py — orçamento de contexto por chamada
from __future__ import annotations

from dataclasses import dataclass, field

from agent.providers.base import ChatMessage, ModelProfile


@dataclass
class ContextComponent:
    name: str
    text: str
    priority: int = 50
    required: bool = False


@dataclass
class BudgetResult:
    messages: list[ChatMessage]
    estimated_tokens: int
    dropped: list[str] = field(default_factory=list)
    strategy_notes: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Heurística conservadora (~4 chars/token em PT/EN misto)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def assemble_messages(
    profile: ModelProfile,
    components: list[ContextComponent],
    *,
    safety_margin: int = 256,
) -> BudgetResult:
    budget = min(profile.input_budget, profile.context_limit - profile.output_reserve - safety_margin)
    if budget <= 0:
        raise ValueError("Orçamento de contexto inválido para o perfil do modelo")

    sorted_components = sorted(components, key=lambda c: (-int(c.required), -c.priority, c.name))
    selected: list[ContextComponent] = []
    dropped: list[str] = []
    used = 0

    for comp in sorted_components:
        cost = estimate_tokens(comp.text)
        if comp.required or used + cost <= budget:
            if not comp.required and used + cost > budget:
                dropped.append(comp.name)
                continue
            selected.append(comp)
            used += cost
        else:
            dropped.append(comp.name)

    if used > budget:
        raise ValueError("Componentes obrigatórios excedem o orçamento; decomponha a tarefa")

    body = "\n\n".join(f"## {c.name}\n{c.text}" for c in selected)
    messages = [
        ChatMessage(role="system", content="Siga o objetivo e o formato pedido. Responda de forma concisa."),
        ChatMessage(role="user", content=body),
    ]
    notes: list[str] = []
    if dropped:
        notes.append("Removidos componentes de baixa prioridade: " + ", ".join(dropped))
    return BudgetResult(
        messages=messages,
        estimated_tokens=used + estimate_tokens(messages[0].content) + estimate_tokens(messages[1].content),
        dropped=dropped,
        strategy_notes=notes,
    )
