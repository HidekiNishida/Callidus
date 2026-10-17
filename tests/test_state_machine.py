# tests/test_state_machine.py
import pytest

from agent.domain.enums import TaskStatus
from agent.domain.state_machine import InvalidTransitionError, can_transition, transition


@pytest.mark.parametrize(
    "current,target,ok",
    [
        (TaskStatus.PENDING, TaskStatus.PLANNING, True),
        (TaskStatus.PENDING, TaskStatus.RUNNING, False),
        (TaskStatus.RUNNING, TaskStatus.VERIFYING, True),
        (TaskStatus.VERIFYING, TaskStatus.COMPLETED, True),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING, False),
        (TaskStatus.BLOCKED, TaskStatus.PLANNING, True),
    ],
)
def test_transitions(current, target, ok):
    assert can_transition(current, target) is ok
    if ok:
        assert transition(current, target) == target
    else:
        with pytest.raises(InvalidTransitionError):
            transition(current, target)
