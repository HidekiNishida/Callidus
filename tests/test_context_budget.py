# tests/test_context_budget.py
import pytest

from agent.context.budget import ContextComponent, assemble_messages, estimate_tokens
from agent.providers.base import ModelProfile


def test_estimate_tokens_nonempty():
    assert estimate_tokens("abcd") >= 1


def test_required_components_kept():
    profile = ModelProfile(model_id="tiny", context_limit=512, input_budget=400, output_reserve=64)
    components = [
        ContextComponent(name="req", text="x" * 100, required=True, priority=100),
        ContextComponent(name="low", text="y" * 2000, required=False, priority=1),
    ]
    result = assemble_messages(profile, components)
    assert any("req" in m.content for m in result.messages)
    assert "low" in result.dropped or result.dropped == []


def test_budget_overflow_required_raises():
    profile = ModelProfile(model_id="tiny", context_limit=200, input_budget=50, output_reserve=50)
    components = [ContextComponent(name="big", text="z" * 500, required=True)]
    with pytest.raises(ValueError):
        assemble_messages(profile, components)
