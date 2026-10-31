"""
Arquivo: src/agent/context/budget.py
Nome: budget.py
Propósito: aplicar o orçamento de contexto por chamada, definindo o que entra no prompt do modelo.
Responsabilidade: camada de aplicação — seleção e ordem dos componentes sob um limite de tokens.
Componentes: ContextComponent, BudgetResult, ContextBudgetError, estimate_tokens, compact_text, fit_window, assemble_messages.
Dependências: agent.providers.base.
Observações: componentes obrigatórios nunca são descartados; se não couberem, o erro manda decompor a tarefa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.providers.base import ChatMessage, ModelProfile, estimate_text_tokens


@dataclass
class ContextComponent:
    """Trecho de contexto candidato a entrar no prompt.

    Atributos:
        name: nome do componente (aparece no prompt e no diagnóstico).
        text: conteúdo do componente.
        priority: prioridade de manutenção; maior é preservado por mais tempo.
        required: quando `True`, o componente nunca é descartado.
        category: categoria do painel de contexto; um componente entra em uma só categoria.
    """

    name: str
    text: str
    priority: int = 50
    required: bool = False
    category: str = "other"


@dataclass
class BudgetResult:
    """Resultado da montagem do contexto: mensagens, custo estimado e componentes descartados.

    Atributos:
        messages: mensagens prontas para o modelo.
        estimated_tokens: custo estimado do prompt montado.
        dropped: nomes dos componentes que não couberam no orçamento.
        strategy_notes: observações sobre as decisões de montagem.
        selected: componentes que entraram, com a estimativa de cada um.
    """

    messages: list[ChatMessage]
    estimated_tokens: int
    dropped: list[str] = field(default_factory=list)
    strategy_notes: list[str] = field(default_factory=list)
    selected: list[dict] = field(default_factory=list)


class ContextBudgetError(ValueError):
    """Partes obrigatórias não cabem no orçamento. Leva o custo de cada componente para diagnóstico."""

    def __init__(self, budget: int, required_tokens: int, breakdown: list[dict]) -> None:
        """Monta o resultado do orçamento com as mensagens e o consumo estimado."""
        super().__init__(
            f"Componentes obrigatórios excedem o orçamento ({required_tokens} > {budget} tokens); decomponha a tarefa"
        )
        self.budget = budget
        self.required_tokens = required_tokens
        self.breakdown = breakdown
        self.snapshot_id: str | None = None


def estimate_tokens(text: str) -> int:
    """Estimativa local de tokens do texto (ver `providers.base.CHARS_PER_TOKEN`, calibrada contra o Ollama).

    Args:
        text: texto do componente.

    Returns:
        A estimativa em tokens; texto vazio vale zero.
    """
    return estimate_text_tokens(text)


_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}")
_BLANK_RUNS = re.compile(r"\n{3,}")


# Obrigatórios de significado: a compactação por pressão não os resume.
_PROTECTED = {
    "regras-globais",
    "regras-projeto",
    "objetivo",
    "objetivo-global",
    "requisitos",
    "critérios",
    "formato-saída",
    "contrato",
    "memória-operacional",
}


def compact_for_pressure(name: str, text: str, *, limit: int = 900) -> str:
    """Encolhe um componente dispensável quando o orçamento da execução aperta.

    Args:
        name: nome do componente.
        text: texto já limpo de espaços repetidos.
        limit: tamanho a partir do qual o meio do texto sai, com a referência do tamanho original.

    Returns:
        O texto integral quando o componente é protegido ou já é curto. Caso contrário,
        o começo, o fim e a contagem original — o conteúdo completo continua no snapshot.
    """
    cleaned = compact_text(text or "")
    if name in _PROTECTED or len(cleaned) <= limit:
        return cleaned
    head = cleaned[: limit // 2].rstrip()
    tail = cleaned[-200:].lstrip()
    return (
        f"{head}\n… [{name}: {len(cleaned)} caracteres; o texto integral permanece no snapshot]\n{tail}"
    )


def group_categories(selected: list[dict]) -> list[dict]:
    """Agrupa os componentes enviados por categoria, sem contar o mesmo texto duas vezes.

    Args:
        selected: componentes escolhidos, cada um com `category` e `tokens`.

    Returns:
        Uma lista de categorias com a soma estimada e os componentes.
    """
    order: list[str] = []
    buckets: dict[str, dict] = {}
    for item in selected:
        category = str(item.get("category") or "other")
        if category not in buckets:
            order.append(category)
            buckets[category] = {
                "category": category,
                "tokens": 0,
                "measurement": "estimate",
                "components": [],
            }
        tokens = int(item.get("tokens") or 0)
        buckets[category]["tokens"] += tokens
        buckets[category]["components"].append(
            {
                "name": item.get("name"),
                "tokens": tokens,
                "required": bool(item.get("required")),
                "measurement": "estimate",
            }
        )
    return [buckets[name] for name in order]


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


# Degrau e teto da janela ampliada (os mesmos da política do Ollama: trocar a janela recarrega o
# modelo, então ela cresce em degraus estáveis; acima do teto, só por configuração explícita).
_WINDOW_STEP = 4096
_WINDOW_CEILING = 32768


def fit_window(profile: ModelProfile, *, safety_margin: int = 256) -> ModelProfile:
    """Faz a janela acompanhar uma reserva de saída ampliada.

    Quando a resposta vem cortada, a operação dobra a reserva de saída para a próxima tentativa.
    Sem ampliar a janela junto, a terceira dobra (8 192) ocupava a janela inteira de 8 192, o
    orçamento de entrada ficava negativo e o run quebrava com exceção — visto com o `qwen3-vl:8b`,
    que raciocina sempre e corta com frequência.

    Args:
        profile: perfil já com a reserva de saída desta tentativa.
        safety_margin: a mesma margem que `assemble_messages` desconta.

    Returns:
        O mesmo perfil quando a entrada já cabe; senão, uma cópia com `context_limit` no menor
        degrau de 4 096 que comporta entrada + reserva + margem, até 32 768.
    """
    needed = int(profile.input_budget) + int(profile.output_reserve) + safety_margin
    if needed <= int(profile.context_limit):
        return profile
    grown = ((needed + _WINDOW_STEP - 1) // _WINDOW_STEP) * _WINDOW_STEP
    return profile.model_copy(update={"context_limit": max(int(profile.context_limit), min(_WINDOW_CEILING, grown))})


def assemble_messages(
    profile: ModelProfile,
    components: list[ContextComponent],
    *,
    safety_margin: int = 256,
) -> BudgetResult:
    """Monta as mensagens do prompt respeitando o orçamento do perfil do modelo.

    Args:
        profile: perfil do modelo, com limite de contexto e orçamentos de entrada e saída.
        components: componentes candidatos, com prioridade e obrigatoriedade.
        safety_margin: margem reservada para a folga entre entrada e saída.

    Returns:
        O `BudgetResult` com as mensagens, o custo estimado e o que foi descartado.

    Raises:
        ValueError: quando o orçamento derivado do perfil é inválido.
        ContextBudgetError: quando os componentes obrigatórios não cabem no orçamento.
    """
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
    chosen: list[dict] = []

    for comp in sorted_components:
        cost = estimate_tokens(comp.text)
        if comp.required or used + cost <= budget:
            if not comp.required and used + cost > budget:
                dropped.append(comp.name)
                continue
            selected.append(comp)
            used += cost
            chosen.append(
                {
                    "name": comp.name,
                    "tokens": cost,
                    "required": comp.required,
                    "category": comp.category or "other",
                    "measurement": "estimate",
                }
            )
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
    system_tokens = estimate_tokens(messages[0].content)
    chosen.insert(
        0,
        {
            "name": "instrução-de-sistema",
            "tokens": system_tokens,
            "required": True,
            "category": "instructions",
            "measurement": "estimate",
        },
    )
    notes: list[str] = []
    if dropped:
        notes.append("Removidos componentes de baixa prioridade: " + ", ".join(dropped))
    return BudgetResult(
        messages=messages,
        estimated_tokens=sum(estimate_tokens(message.content) for message in messages),
        dropped=dropped,
        strategy_notes=notes,
        selected=chosen,
    )
