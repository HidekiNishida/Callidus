# src/agent/context/assembler.py — montagem de contexto por operação
from __future__ import annotations

from agent.context.budget import ContextComponent, BudgetResult, assemble_messages, compact_text
from agent.providers.base import ModelProfile

_EXACT = {"arquivos-alvo"}


def build_operation_context(
    profile: ModelProfile,
    *,
    global_rules: str,
    project_rules: str,
    objective: str,
    technical: str,
    acceptance: str,
    tools_summary: str,
    output_format: str,
    previous_failures: str = "",
    previous_inspection: str = "",
    contract: str = "",
    target_files: str = "",
    global_objective: str = "",
    dependency_results: str = "",
    skills: str = "",
    requirements: str = "",
    compact: bool = False,
) -> BudgetResult:
    """Componentes do prompt da operação. Obrigatórios nunca são cortados: se não couberem, o orçamento
    lança `ContextBudgetError`. A compactação não mexe em `arquivos-alvo`, que precisa ficar idêntico ao
    disco para `old_string` casar.

    São obrigatórios também o **objetivo global** (o porquê da etapa dentro do pedido) e as
    **regras do projeto** (as restrições canônicas): são eles que o modelo não pode perder sem
    fazer a coisa errada. O que é grande e dispensável (skills, contexto técnico, ferramentas) é
    o que sai quando falta espaço.
    """
    components = [
        ContextComponent(name="regras-globais", text=global_rules, required=True, priority=100),
        ContextComponent(name="objetivo", text=objective, required=True, priority=99),
        ContextComponent(name="requisitos", text=requirements, required=True, priority=98),
        ContextComponent(name="critérios", text=acceptance, required=True, priority=97),
        ContextComponent(name="formato-saída", text=output_format, required=True, priority=96),
        ContextComponent(name="objetivo-global", text=global_objective, required=True, priority=92),
        ContextComponent(name="regras-projeto", text=project_rules, required=True, priority=90),
        ContextComponent(name="skills", text=skills, required=False, priority=75),
        ContextComponent(name="contexto-técnico", text=technical, required=False, priority=70),
        ContextComponent(name="ferramentas", text=tools_summary, required=False, priority=60),
    ]
    optional = [
        ("tentativas-anteriores", previous_failures, True, 95),
        ("contrato", contract, True, 94),
        ("arquivos-alvo", target_files, True, 93),
        ("inspeção-anterior", previous_inspection, False, 88),
        ("resultados-dependências", dependency_results, False, 85),
    ]
    for name, text, required, priority in optional:
        if text:
            components.append(ContextComponent(name=name, text=text, required=required, priority=priority))
    if compact:
        for comp in components:
            if comp.name not in _EXACT:
                comp.text = compact_text(comp.text)
    result = assemble_messages(profile, components)
    if compact:
        result.strategy_notes.append("contexto compactado (espaços e linhas repetidas)")
    return result
