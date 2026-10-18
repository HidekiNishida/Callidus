# src/agent/context/assembler.py — montagem de contexto por operação
from __future__ import annotations

from agent.context.budget import ContextComponent, BudgetResult, assemble_messages, compact_text
from agent.providers.base import ModelProfile


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
    compact: bool = False,
) -> BudgetResult:
    components = [
        ContextComponent(name="regras-globais", text=global_rules, required=True, priority=100),
        ContextComponent(name="objetivo", text=objective, required=True, priority=99),
        ContextComponent(name="critérios", text=acceptance, required=True, priority=98),
        ContextComponent(name="formato-saída", text=output_format, required=True, priority=97),
        ContextComponent(name="regras-projeto", text=project_rules, required=False, priority=80),
        ContextComponent(name="contexto-técnico", text=technical, required=False, priority=70),
        ContextComponent(name="ferramentas", text=tools_summary, required=False, priority=60),
    ]
    if compact:
        for comp in components:
            comp.text = compact_text(comp.text)
    result = assemble_messages(profile, components)
    if compact:
        result.strategy_notes.append("contexto compactado (espaços e linhas repetidas)")
    return result
