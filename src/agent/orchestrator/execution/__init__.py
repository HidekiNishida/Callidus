"""
Arquivo: src/agent/orchestrator/execution/__init__.py
Nome: __init__.py
Propósito: expor a fachada pública da execução de uma tarefa do orquestrador.
Responsabilidade: camada de aplicação — ponto de entrada do pacote de execução; não implementa regras.
Componentes: TaskExecutor, ExecutionRuntime, e os utilitários de guarda, provedor e escrita.
Dependências: agent.orchestrator.execution.executor, agent.orchestrator.execution.runtime.
Observações: a fachada não duplica lógica — só reexporta o que o orquestrador precisa.
"""

from agent.orchestrator.execution.executor import TaskExecutor
from agent.orchestrator.execution.guards import (
    compact_inspection,
    evidence_state,
    operation_tools_for,
    payload_is_usable,
    write_refusal_reason,
)
from agent.orchestrator.execution.journal import note_thought, remember_failure
from agent.orchestrator.execution.providers import (
    apply_provider_usage,
    default_provider_name,
    profile_from_config,
    select_provider,
    supports_tool_loop,
)
from agent.orchestrator.execution.runtime import ExecutionRuntime
from agent.orchestrator.execution.tool_results import (
    is_informative_test_result,
    test_summary,
)
from agent.orchestrator.execution.workspace import work_root
from agent.orchestrator.execution.writes import (
    implicit_spec,
    model_refusal_result,
    tool_refusal_result,
    write_tool_from_payload,
)

__all__ = [
    "ExecutionRuntime",
    "TaskExecutor",
    "apply_provider_usage",
    "compact_inspection",
    "evidence_state",
    "default_provider_name",
    "implicit_spec",
    "is_informative_test_result",
    "note_thought",
    "operation_tools_for",
    "payload_is_usable",
    "profile_from_config",
    "model_refusal_result",
    "remember_failure",
    "select_provider",
    "supports_tool_loop",
    "test_summary",
    "tool_refusal_result",
    "work_root",
    "write_refusal_reason",
    "write_tool_from_payload",
]
