# tests/test_atomizer.py
from agent.domain.enums import TaskKind
from agent.orchestrator.atomizer import micro_decompose_operation, should_decompose_further


def test_atomic_tool_skips_decompose():
    assert not should_decompose_further(
        objective="long objective " * 20,
        metadata={"tool": "read_file"},
        kind=TaskKind.OPERATION.value,
        attempt_count=0,
        has_children=False,
    )


def test_micro_plan_has_three_steps():
    plan = micro_decompose_operation("Implementar serviço X")
    assert len(plan.subtasks) == 3
    assert plan.subtasks[1].metadata.get("model_operation")


def test_decompose_after_retries():
    assert should_decompose_further(
        objective="x" * 200,
        metadata={},
        kind=TaskKind.OBJECTIVE.value,
        attempt_count=3,
        has_children=False,
    )
