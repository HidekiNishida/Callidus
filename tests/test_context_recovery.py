# tests/test_context_recovery.py — contexto obrigatório acima do orçamento e recuperação
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.context.budget import ContextBudgetError, ContextComponent, assemble_messages, compact_text
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.domain.state_machine import can_transition
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ContextSnapshotModel, OperationAttemptModel
from agent.providers.base import ModelProfile
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

SMALL = {"provider": "mock", "approve_risky_tools": True, "context_limit": 2048, "input_budget": 1000}


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


class _Recorder:
    name = "mock"
    last_usage = None

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request):
        self.calls += 1

        class _R:
            content = '{"path": "a.txt", "content": "ok"}'

        return _R()


def _running_change(session, tmp_path: Path, objective: str):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Alterar arquivo",
            objective=objective,
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config=SMALL))
    session.commit()
    return run, change


def test_overflow_error_carries_breakdown_and_is_a_value_error():
    profile = ModelProfile(model_id="tiny", context_limit=1000, input_budget=50, output_reserve=50)
    with pytest.raises(ValueError) as caught:
        assemble_messages(profile, [ContextComponent(name="big", text="z" * 500, required=True)])
    exc = caught.value
    assert isinstance(exc, ContextBudgetError)
    assert exc.required_tokens == 125
    assert exc.breakdown == [{"name": "big", "tokens": 125, "required": True}]


def test_compact_text_keeps_content_and_indentation():
    text = "def f():\n    return  1   +   2\n\n\n\nlinha\nlinha\n"
    assert compact_text(text) == "def f():\n    return 1 + 2\n\nlinha"


def test_running_task_can_block():
    assert can_transition(TaskStatus.RUNNING, TaskStatus.BLOCKED)


@pytest.mark.asyncio
async def test_required_context_over_budget_blocks_without_calling_the_model(session, tmp_path, monkeypatch):
    run, change = _running_change(session, tmp_path, "Implemente: " + "requisito distinto " * 1200)
    provider = _Recorder()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "blocked_context"
    assert out["failure"]["cause"] == "context_budget"
    assert provider.calls == 0
    stored = TaskService(session).get_task(change.id)
    assert stored.status == TaskStatus.BLOCKED.value
    assert "objetivo" in stored.metadata_json["last_failure"]["detail"]
    snaps = session.scalars(select(ContextSnapshotModel).where(ContextSnapshotModel.task_id == change.id)).all()
    assert len(snaps) == 2
    assert all(s.strategy_notes_json[0].startswith("estouro") for s in snaps)
    attempt = session.scalars(select(OperationAttemptModel).where(OperationAttemptModel.task_id == change.id)).one()
    assert attempt.success is False
    assert attempt.request_json["context_snapshot_id"] == str(snaps[-1].id)

    again = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    assert again["action"] != "blocked_context"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_compaction_recovers_context_that_only_overflowed_by_whitespace(session, tmp_path, monkeypatch):
    run, change = _running_change(session, tmp_path, "Escreva a.txt com ok." + " " * 6000 + "Fim.")
    provider = _Recorder()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] != "blocked_context"
    assert provider.calls == 1
    snaps = session.scalars(select(ContextSnapshotModel).where(ContextSnapshotModel.task_id == change.id)).all()
    assert any("contexto compactado" in note for s in snaps for note in (s.strategy_notes_json or []))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ok"
