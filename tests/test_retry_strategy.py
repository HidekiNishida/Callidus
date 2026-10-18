# tests/test_retry_strategy.py — nova tentativa leva o motivo da falha e nunca repete o mesmo prompt
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
    classify_verification,
    describe_failures,
)
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


class _Scripted:
    name = "mock"
    last_usage = None

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []
        self.num_predict: list[int | None] = []

    async def chat(self, request):
        self.prompts.append("\n".join(m.content for m in request.messages))
        self.num_predict.append(request.profile.generation.get("num_predict"))
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]

        class _R:
            content = reply

        return _R()


def _change(session, tmp_path: Path, provider, monkeypatch):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Alterar arquivo",
            objective="Escreva a.txt com ok",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, change


def test_failure_summary_has_reason_and_hint():
    history = [Failure(FailureCategory.RECOVERABLE, FailureCause.INVALID_OUTPUT, "JSON inválido").as_dict()]
    text = describe_failures(history)
    assert "invalid_output: JSON inválido" in text
    assert "Responda apenas o objeto JSON" in text
    assert describe_failures([]) == ""


def test_verification_failure_keeps_the_end_of_the_output():
    failure = classify_verification(False, "pytest falhou", "x" * 1000 + "\nE assert 1 == 2")
    assert failure.detail.startswith("pytest falhou: ")
    assert failure.detail.endswith("E assert 1 == 2")
    assert len(failure.detail) < 700


@pytest.mark.asyncio
async def test_retries_carry_the_reason_and_stop_before_an_identical_prompt(session, tmp_path, monkeypatch):
    provider = _Scripted(["Claro, vou escrever o arquivo."])
    run, change = _change(session, tmp_path, provider, monkeypatch)

    log = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=30)
    session.commit()

    assert len(provider.prompts) == len(set(provider.prompts)), "nenhum prompt repetido"
    assert "tentativas-anteriores" not in provider.prompts[0]
    assert "invalid_output" in provider.prompts[1]
    assert "Responda apenas o objeto JSON" in provider.prompts[1]
    assert log[-1]["action"] == "blocked_loop"
    assert log[-1]["failure"]["cause"] == "repeated_prompt"
    assert TaskService(session).get_task(change.id).status == TaskStatus.BLOCKED.value


@pytest.mark.asyncio
async def test_truncated_reply_raises_the_output_limit_on_retry(session, tmp_path, monkeypatch):
    provider = _Scripted(['{"path": "a.txt", "content": "o', '{"path": "a.txt", "content": "ok"}'])
    run, change = _change(session, tmp_path, provider, monkeypatch)

    await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=10)
    session.commit()

    assert len(provider.prompts) == 2
    assert "truncated_output" in provider.prompts[1]
    first = provider.num_predict[0] or 0
    assert provider.num_predict[1] >= max(first, 2048) * 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ok"
