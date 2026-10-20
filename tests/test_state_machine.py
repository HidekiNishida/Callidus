"""
Arquivo: tests/test_state_machine.py
Nome: test_state_machine.py
Propósito: verificar quais transições de estado de tarefa são aceitas e quais são recusadas.
Responsabilidade: camada de testes — comportamento observável da máquina de estados de tarefa.
Componentes: tabela parametrizada de transições válidas e inválidas entre estados de tarefa.
Dependências: agent.domain.enums.TaskStatus, agent.domain.state_machine (can_transition, transition, InvalidTransitionError), pytest.
Observações: caso puramente determinístico, sem banco, disco ou rede.
"""
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
        (TaskStatus.PLANNING, TaskStatus.VERIFYING, True),
    ],
)
def test_transitions(current, target, ok):
    """As transições marcadas como válidas são aceitas e avançam o estado; as inválidas levantam InvalidTransitionError."""
    assert can_transition(current, target) is ok
    if ok:
        assert transition(current, target) == target
    else:
        with pytest.raises(InvalidTransitionError):
            transition(current, target)
