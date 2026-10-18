# src/agent/domain/state_machine.py — transições válidas de TaskStatus
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
        {TaskStatus.COMPLETED, TaskStatus.RETRY_PENDING, TaskStatus.RUNNING, TaskStatus.PLANNING}
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
        super().__init__(f"Transição inválida: {current.value} → {target.value}")
        self.current = current
        self.target = target


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    validate_transition(current, target)
    return target
