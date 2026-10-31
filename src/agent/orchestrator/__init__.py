"""
Arquivo: src/agent/orchestrator/__init__.py
Nome: __init__.py
Propósito: exporta símbolos públicos do pacote de orquestração.
Responsabilidade: camada de aplicação — ponto de entrada estável para componentes do orquestrador.
Componentes: RunOrchestrator, TaskIR, IRSchema, ArtifactRef, RequirementLink, ContextBudget, ExecutionConstraint, to_ir, from_ir, apply_ir_to_task.
Dependências: agent.orchestrator.runner, agent.orchestrator.task_ir.
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""

from __future__ import annotations

from agent.orchestrator.task_ir import (
    ArtifactRef,
    ContextBudget,
    ExecutionConstraint,
    IRSchema,
    RequirementLink,
    TaskIR,
    apply_ir_to_task,
    from_ir,
    to_ir,
)

from agent.orchestrator.runner import RunOrchestrator  # noqa: F401

