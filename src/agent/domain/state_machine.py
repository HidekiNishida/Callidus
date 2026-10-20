"""
Arquivo: src/agent/domain/state_machine.py
Nome: state_machine.py
Propósito: definir e validar as transições válidas entre os estados de `TaskStatus`.
Responsabilidade: camada de domínio — fonte única das regras de transição do ciclo de vida da tarefa.
Componentes: ALLOWED_TRANSITIONS, TERMINAL_STATUSES, InvalidTransitionError, can_transition, validate_transition, transition.
Dependências: agent.domain.enums.
Observações: transições inválidas levantam `InvalidTransitionError`; a tabela é a única autoridade.
"""
from __future__ import annotations

from agent.domain.enums import TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.PLANNING, TaskStatus.CANCELLED}),
    TaskStatus.PLANNING: frozenset(
        {TaskStatus.READY, TaskStatus.VERIFYING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.BLOCKED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.VERIFYING,
            TaskStatus.RETRY_PENDING,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.VERIFYING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.RETRY_PENDING, TaskStatus.RUNNING, TaskStatus.PLANNING, TaskStatus.BLOCKED}
    ),
    TaskStatus.RETRY_PENDING: frozenset({TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.PLANNING, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset({TaskStatus.VERIFYING}),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class InvalidTransitionError(ValueError):
    """Transição de estado não permitida."""

    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        """Monta o erro de transição com o estado atual e o estado pedido."""
        super().__init__(f"Transição inválida: {current.value} → {target.value}")
        self.current = current
        self.target = target


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Indica se a mudança de estado é permitida pela tabela de transições.

    Args:
        current: estado atual da tarefa.
        target: estado pretendido.

    Returns:
        `True` quando a transição é válida.
    """
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Valida a mudança de estado, levantando erro quando a transição não é permitida.

    Args:
        current: estado atual da tarefa.
        target: estado pretendido.

    Raises:
        InvalidTransitionError: quando a transição não existe na tabela.
    """
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    """Devolve o novo estado após validar a transição.

    Args:
        current: estado atual da tarefa.
        target: estado pretendido.

    Returns:
        O estado de destino, quando a transição é válida.

    Raises:
        InvalidTransitionError: quando a transição não é permitida.
    """
    validate_transition(current, target)
    return target
