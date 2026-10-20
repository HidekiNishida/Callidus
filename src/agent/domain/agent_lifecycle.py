# src/agent/domain/agent_lifecycle.py — transições válidas do agente e da execução
"""Máquina de estados da hierarquia de agentes.

O estado da **tarefa** já tem sua máquina em
[`agent.domain.state_machine`][agent.domain.state_machine]. Aqui ficam os estados do
**agente lógico** e da **execução**, que são coisas diferentes:

| Conceito | Onde vive | Sobrevive a |
|----------|-----------|-------------|
| Tarefa | [`tasks`][agent.persistence.models.TaskModel] | fim da execução |
| Agente lógico | [`agents`][agent.persistence.models.AgentModel] | fim da tarefa e da execução |
| Execução | [`agent_executions`][agent.persistence.models.AgentExecutionModel] | nada: termina com a execução |

Transições inválidas levantam [`InvalidAgentTransition`][agent.domain.agent_lifecycle.InvalidAgentTransition]:
um estado inconsistente é erro, nunca um estado "corrigido" em silêncio.
"""
from __future__ import annotations

from agent.domain.agent_enums import AgentStatus, ExecutionStatus


class InvalidAgentTransition(ValueError):
    """Transição de estado de agente ou execução não permitida."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Transição inválida: {current} → {target}")
        self.current = current
        self.target = target


AGENT_TRANSITIONS: dict[AgentStatus, frozenset[AgentStatus]] = {
    AgentStatus.IDLE: frozenset(
        {
            AgentStatus.ACTIVE,
            AgentStatus.SUSPENDED,
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.DISCARDED,
        }
    ),
    AgentStatus.ACTIVE: frozenset(
        {
            AgentStatus.IDLE,
            AgentStatus.WAITING,
            AgentStatus.SUSPENDED,
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.DISCARDED,
        }
    ),
    AgentStatus.WAITING: frozenset(
        {
            AgentStatus.ACTIVE,
            AgentStatus.IDLE,
            AgentStatus.SUSPENDED,
            AgentStatus.FAILED,
            AgentStatus.DISCARDED,
        }
    ),
    AgentStatus.SUSPENDED: frozenset(
        {
            AgentStatus.ACTIVE,
            AgentStatus.IDLE,
            AgentStatus.FAILED,
            AgentStatus.DISCARDED,
        }
    ),
    AgentStatus.COMPLETED: frozenset({AgentStatus.DISCARDED, AgentStatus.ACTIVE}),
    AgentStatus.FAILED: frozenset(
        {
            AgentStatus.ACTIVE,
            AgentStatus.SUSPENDED,
            AgentStatus.IDLE,
            AgentStatus.DISCARDED,
        }
    ),
    AgentStatus.DISCARDED: frozenset(),
}

EXECUTION_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.PENDING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.SUSPENDING,
            ExecutionStatus.WAITING_FOR_CHILD,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.SUSPENDING: frozenset(
        {
            ExecutionStatus.SUSPENDED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.SUSPENDED: frozenset(
        {
            ExecutionStatus.RESUMING,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.RESUMING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.WAITING_FOR_CHILD: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.SUSPENDING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.COMPLETED: frozenset({ExecutionStatus.DISCARDED}),
    ExecutionStatus.FAILED: frozenset(
        {
            ExecutionStatus.RESUMING,
            ExecutionStatus.SUSPENDING,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.DISCARDED,
        }
    ),
    ExecutionStatus.CANCELLED: frozenset(),
    ExecutionStatus.DISCARDED: frozenset(),
}

TERMINAL_AGENT_STATUSES = frozenset({AgentStatus.DISCARDED})
TERMINAL_EXECUTION_STATUSES = frozenset(
    {ExecutionStatus.CANCELLED, ExecutionStatus.DISCARDED}
)


def can_transition_agent(current: AgentStatus, target: AgentStatus) -> bool:
    return target in AGENT_TRANSITIONS.get(current, frozenset())


def can_transition_execution(current: ExecutionStatus, target: ExecutionStatus) -> bool:
    return target in EXECUTION_TRANSITIONS.get(current, frozenset())


def validate_agent_transition(current: AgentStatus, target: AgentStatus) -> None:
    if not can_transition_agent(current, target):
        raise InvalidAgentTransition(current.value, target.value)


def validate_execution_transition(current: ExecutionStatus, target: ExecutionStatus) -> None:
    if not can_transition_execution(current, target):
        raise InvalidAgentTransition(current.value, target.value)


def transition_agent(current: AgentStatus, target: AgentStatus) -> AgentStatus:
    validate_agent_transition(current, target)
    return target


def transition_execution(current: ExecutionStatus, target: ExecutionStatus) -> ExecutionStatus:
    validate_execution_transition(current, target)
    return target
