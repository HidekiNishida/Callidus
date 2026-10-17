# tests/test_decomposition.py
import pytest

from agent.config import Settings
from agent.orchestrator.decomposition import resolve_decomposition_plan


@pytest.mark.asyncio
async def test_resolve_builtin_e2e():
    settings = Settings(allow_mock_fallback=True)
    plan, source = await resolve_decomposition_plan(
        settings=settings,
        run_config={"provider": "mock"},
        objective="rodar e2e no calc",
        project_root="/tmp/x",
    )
    assert plan is not None
    assert source == "builtin-e2e"
    assert len(plan.subtasks) == 3
