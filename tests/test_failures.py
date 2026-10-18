# tests/test_failures.py — taxonomia de falhas e registro no orquestrador
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
    classify_context_error,
    classify_model_output,
    classify_provider_error,
    classify_tool_result,
    classify_verification,
    looks_truncated,
)
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import OperationAttemptModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


@pytest.mark.parametrize(
    ("out", "category", "cause"),
    [
        ({"success": False, "error": "executável indisponível: x", "category": "configuration"},
         FailureCategory.CONFIGURATION, FailureCause.MISSING_EXECUTABLE),
        ({"success": False, "error": "approval_required"},
         FailureCategory.EXTERNAL_UNAVAILABLE, FailureCause.APPROVAL_REQUIRED),
        ({"success": False, "error": "ferramenta desconhecida: foo"},
         FailureCategory.CHANGE_STRATEGY, FailureCause.UNKNOWN_TOOL),
        ({"success": False, "error": "navegador desligado no compositor"},
         FailureCategory.CONFIGURATION, FailureCause.FEATURE_DISABLED),
        ({"success": False, "error": "timeout"},
         FailureCategory.OPERATIONAL_LIMIT, FailureCause.TIMEOUT),
        ({"success": False, "error": "trecho não encontrado"},
         FailureCategory.RECOVERABLE, FailureCause.TOOL_INPUT),
        ({"success": False, "exit_code": 1, "stderr": "AssertionError"},
         FailureCategory.RECOVERABLE, FailureCause.TOOL_ERROR),
    ],
)
def test_tool_results_are_categorized(out, category, cause):
    failure = classify_tool_result(out)
    assert failure is not None
    assert (failure.category, failure.cause) == (category, cause)


def test_successful_tool_is_not_a_failure():
    assert classify_tool_result({"success": True}) is None


def test_provider_errors_separate_timeout_from_unavailable():
    assert classify_provider_error("tempo esgotado").cause == FailureCause.TIMEOUT
    down = classify_provider_error("Ollama indisponível em http://x: refused")
    assert down.category == FailureCategory.EXTERNAL_UNAVAILABLE
    assert classify_provider_error("modelo respondeu 500").category == FailureCategory.RECOVERABLE


def test_truncated_output_differs_from_malformed_json():
    cut = classify_model_output('{"path": "a.py", "content": "def f(', "JSON inválido")
    assert cut.cause == FailureCause.TRUNCATED_OUTPUT
    assert cut.category == FailureCategory.CHANGE_STRATEGY
    bad = classify_model_output("não sei", "JSON inválido")
    assert bad.cause == FailureCause.INVALID_OUTPUT
    assert bad.retry_same_strategy
    missing = classify_model_output('{"content": "x"}', None, ["path"])
    assert "path" in missing.detail
    assert classify_model_output('{"path": "a"}', None) is None
    assert looks_truncated("```python\nprint(1)")
    assert not looks_truncated('{"a": {"b": 1}}')


def test_context_and_verification_categories():
    assert classify_context_error("estouro").cause == FailureCause.CONTEXT_BUDGET
    assert classify_verification(True, "ok") is None
    inconclusive = classify_verification(None, "manual")
    assert inconclusive.cause == FailureCause.VERIFICATION_INCONCLUSIVE
    assert not inconclusive.retry_same_strategy
    assert classify_verification(False, "pytest falhou").cause == FailureCause.VERIFICATION_FAILED


def test_failure_roundtrip():
    failure = Failure(FailureCategory.RECOVERABLE, FailureCause.TOOL_ERROR, "x")
    assert Failure.from_dict(failure.as_dict()) == failure
    assert Failure.from_dict({"category": "nope", "cause": "x"}) is None
    assert Failure.from_dict(None) is None


@pytest.mark.asyncio
async def test_invalid_model_json_is_a_failed_attempt_with_category(session, tmp_path: Path, monkeypatch):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Alterar arquivo",
            objective="Escreva a.py",
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

    class _Prose:
        name = "mock"
        last_usage = None

        async def chat(self, request):
            class _R:
                content = "Claro! Vou escrever o arquivo agora."

            return _R()

    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: _Prose())
    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "model_operation_invalid"
    assert out["failure"]["cause"] == FailureCause.INVALID_OUTPUT.value
    attempt = session.scalars(
        select(OperationAttemptModel).where(OperationAttemptModel.task_id == change.id)
    ).one()
    assert attempt.success is False
    assert "invalid_output" in (attempt.error_message or "")
    stored = tasks.get_task(change.id)
    assert stored.status == TaskStatus.RETRY_PENDING.value
    assert stored.metadata_json["last_failure"]["cause"] == "invalid_output"
