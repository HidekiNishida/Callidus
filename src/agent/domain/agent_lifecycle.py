"""
Arquivo: src/agent/domain/agent_lifecycle.py
Nome: agent_lifecycle.py
Propósito: definir e validar as transições válidas do agente lógico e da execução.
Responsabilidade: camada de domínio — máquina de estados da hierarquia de agentes.
Componentes: InvalidAgentTransition, AGENT_TRANSITIONS, EXECUTION_TRANSITIONS, TERMINAL_AGENT_STATUSES, TERMINAL_EXECUTION_STATUSES, can_transition_agent, can_transition_execution, validate_agent_transition, validate_execution_transition, transition_agent, transition_execution.
Dependências: agent.domain.agent_enums.
Observações: a tarefa tem máquina própria em `agent.domain.state_machine`; um estado inconsistente é erro, nunca corrigido em silêncio.

Máquina de estados da hierarquia de agentes.

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
        """Monta o registro de ciclo de vida do agente."""
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
    """Indica se a mudança de estado do agente lógico é permitida.

    Args:
        current: estado atual do agente.
        target: estado pretendido.

    Returns:
        `True` quando a transição é válida.
    """
    return target in AGENT_TRANSITIONS.get(current, frozenset())


def can_transition_execution(current: ExecutionStatus, target: ExecutionStatus) -> bool:
    """Indica se a mudança de estado da execução é permitida.

    Args:
        current: estado atual da execução.
        target: estado pretendido.

    Returns:
        `True` quando a transição é válida.
    """
    return target in EXECUTION_TRANSITIONS.get(current, frozenset())


def validate_agent_transition(current: AgentStatus, target: AgentStatus) -> None:
    """Valida a mudança de estado do agente, levantando erro quando inválida.

    Args:
        current: estado atual do agente.
        target: estado pretendido.

    Raises:
        InvalidAgentTransition: quando a transição não existe na tabela.
    """
    if not can_transition_agent(current, target):
        raise InvalidAgentTransition(current.value, target.value)


def validate_execution_transition(current: ExecutionStatus, target: ExecutionStatus) -> None:
    """Valida a mudança de estado da execução, levantando erro quando inválida.

    Args:
        current: estado atual da execução.
        target: estado pretendido.

    Raises:
        InvalidAgentTransition: quando a transição não existe na tabela.
    """
    if not can_transition_execution(current, target):
        raise InvalidAgentTransition(current.value, target.value)


def transition_agent(current: AgentStatus, target: AgentStatus) -> AgentStatus:
    """Devolve o novo estado do agente após validar a transição.

    Args:
        current: estado atual do agente.
        target: estado pretendido.

    Returns:
        O estado de destino, quando a transição é válida.

    Raises:
        InvalidAgentTransition: quando a transição não é permitida.
    """
    validate_agent_transition(current, target)
    return target


def transition_execution(current: ExecutionStatus, target: ExecutionStatus) -> ExecutionStatus:
    """Devolve o novo estado da execução após validar a transição.

    Args:
        current: estado atual da execução.
        target: estado pretendido.

    Returns:
        O estado de destino, quando a transição é válida.

    Raises:
        InvalidAgentTransition: quando a transição não é permitida.
    """
    validate_execution_transition(current, target)
    return target
