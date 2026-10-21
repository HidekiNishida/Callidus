"""
Arquivo: src/agent/context/assembler.py
Nome: assembler.py
Propósito: montar os componentes de contexto de uma operação do agente.
Responsabilidade: camada de aplicação — definição do que compõe o prompt de cada operação.
Componentes: build_operation_context.
Dependências: agent.context.budget, agent.providers.base.
Observações: a compactação nunca altera `arquivos-alvo`, que precisa casar com o disco.
"""
from __future__ import annotations

from agent.context.budget import (
    BudgetResult,
    ContextComponent,
    assemble_messages,
    compact_for_pressure,
    compact_text,
)
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
    operational: str = "",
    compact: bool = False,
    pressure: bool = False,
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
        ContextComponent(name="regras-globais", text=global_rules, required=True, priority=100, category="instructions"),
        ContextComponent(name="objetivo", text=objective, required=True, priority=99, category="objective"),
        ContextComponent(name="requisitos", text=requirements, required=True, priority=98, category="objective"),
        ContextComponent(name="critérios", text=acceptance, required=True, priority=97, category="objective"),
        ContextComponent(name="formato-saída", text=output_format, required=True, priority=96, category="objective"),
        ContextComponent(name="objetivo-global", text=global_objective, required=True, priority=92, category="objective"),
        ContextComponent(name="regras-projeto", text=project_rules, required=True, priority=90, category="project_rules"),
        ContextComponent(name="memória-operacional", text=operational, required=False, priority=94, category="memory"),
        ContextComponent(name="skills", text=skills, required=False, priority=75, category="skills"),
        ContextComponent(name="contexto-técnico", text=technical, required=False, priority=70, category="files"),
        ContextComponent(name="ferramentas", text=tools_summary, required=False, priority=60, category="tools"),
    ]
    optional = [
        ("tentativas-anteriores", previous_failures, True, 95, "history"),
        ("contrato", contract, True, 94, "objective"),
        ("arquivos-alvo", target_files, True, 93, "files"),
        ("inspeção-anterior", previous_inspection, False, 88, "tool_results"),
        ("resultados-dependências", dependency_results, False, 85, "summaries"),
    ]
    for name, text, required, priority, category in optional:
        if text:
            components.append(
                ContextComponent(name=name, text=text, required=required, priority=priority, category=category)
            )
    if compact or pressure:
        for comp in components:
            if comp.name not in _EXACT:
                comp.text = compact_text(comp.text)
            if pressure and comp.name not in _EXACT:
                comp.text = compact_for_pressure(comp.name, comp.text)
    result = assemble_messages(profile, components)
    if compact:
        result.strategy_notes.append("contexto compactado (espaços e linhas repetidas)")
    if pressure:
        result.strategy_notes.append("contexto reduzido por pressão de orçamento; critérios e requisitos preservados")
    return result
