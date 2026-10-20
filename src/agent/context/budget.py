# src/agent/context/budget.py — orçamento de contexto por chamada
from __future__ import annotations

import re
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


class ContextBudgetError(ValueError):
    """Partes obrigatórias não cabem no orçamento. Leva o custo de cada componente para diagnóstico."""

    def __init__(self, budget: int, required_tokens: int, breakdown: list[dict]) -> None:
        super().__init__(
            f"Componentes obrigatórios excedem o orçamento ({required_tokens} > {budget} tokens); decomponha a tarefa"
        )
        self.budget = budget
        self.required_tokens = required_tokens
        self.breakdown = breakdown
        self.snapshot_id: str | None = None


def estimate_tokens(text: str) -> int:
    """Heurística conservadora (~4 chars/token em PT/EN misto)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}")
_BLANK_RUNS = re.compile(r"\n{3,}")


def compact_text(text: str) -> str:
    """Encolhe sem perder conteúdo: espaços internos repetidos, linhas em branco seguidas e linhas duplicadas
    consecutivas. Preserva a indentação inicial (código)."""
    lines: list[str] = []
    for line in (text or "").splitlines():
        line = _INNER_SPACES.sub(" ", line.rstrip())
        if lines and line and line == lines[-1]:
            continue
        lines.append(line)
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def assemble_messages(
    profile: ModelProfile,
    components: list[ContextComponent],
    *,
    safety_margin: int = 256,
) -> BudgetResult:
    budget = min(profile.input_budget, profile.context_limit - profile.output_reserve - safety_margin)
    if budget <= 0:
        raise ValueError("Orçamento de contexto inválido para o perfil do modelo")

    sorted_components = sorted(
        [c for c in components if c.text and c.text.strip()],
        key=lambda c: (-int(c.required), -c.priority, c.name),
    )
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
        breakdown = [
            {"name": c.name, "tokens": estimate_tokens(c.text), "required": c.required}
            for c in sorted_components
        ]
        raise ContextBudgetError(budget, used, breakdown)

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
