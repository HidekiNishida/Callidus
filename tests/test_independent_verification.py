# tests/test_independent_verification.py — evidência independente: estados, critério, comando, código de saída
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import verification_evidence_ok
from agent.orchestrator.global_verify import reopen_verification_gaps
from agent.orchestrator.requirements import ensure_requirements
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.verification.runner import syntax_problem


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _project(tmp_path: Path, body: str = "return a + b") -> Path:
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text(f"def add(a, b):\n    {body}\n")
    (root / "tests" / "test_calc.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    return root


def _verifying(session, root_path: Path, spec: dict | None, *, approve=False, status=TaskStatus.VERIFYING, meta=None):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(root_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="- corrigir calc.py"))
    root.status = TaskStatus.PLANNING.value
    ensure_requirements(session, root)
    metadata = {"covers": ["R1"], **({"verification": spec} if spec else {}), **(meta or {})}
    leaf = tasks.create_task(
        project.id,
        TaskCreate(title="Corrigir", objective="corrigir calc.py", acceptance_criteria="soma correta", parent_id=root.id, metadata=metadata),
    )
    leaf.status = status.value
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": approve})
    )
    session.commit()
    return run, leaf


def _evidence(session, task_id):
    return session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == task_id)).all()


@pytest.mark.asyncio
async def test_valid_code_with_passing_tests_records_full_evidence(session, tmp_path):
    run, leaf = _verifying(session, _project(tmp_path), {"type": "pytest", "path": "tests"})

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verified_ok"
    [ev] = _evidence(session, leaf.id)
    assert ev.passed is True and ev.attempt_id is not None
    assert ev.detail_json["state"] == "aprovado"
    assert ev.detail_json["exit_code"] == 0
    assert ev.detail_json["command"] == {"type": "pytest", "path": "tests"}
    assert ev.detail_json["criteria"]["requirements"] == ["R1"]
    assert ev.detail_json["criteria"]["acceptance"] == "soma correta"
    assert ev.detail_json["artifacts"]["fingerprint"]


@pytest.mark.asyncio
async def test_failing_tests_after_implementation_are_a_failure_to_fix(session, tmp_path):
    run, leaf = _verifying(session, _project(tmp_path, "return a - b"), {"type": "pytest", "path": "tests"})

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_failed"
    [ev] = _evidence(session, leaf.id)
    assert ev.passed is False and ev.detail_json["state"] == "reprovado"
    assert ev.detail_json["exit_code"] == 1
    assert TaskService(session).get_task(leaf.id).status == TaskStatus.RETRY_PENDING.value


def test_syntax_checker_is_deterministic():
    assert syntax_problem("a.py", "def f(:\n") .startswith("linha 1")
    assert syntax_problem("a.py", "def f():\n    return 1\n") is None
    assert syntax_problem("d.json", "{") is not None
    assert syntax_problem("n.txt", "def f(:") is None


class _Writer:
    name = "mock"
    last_usage = None

    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def chat(self, request):
        reply = self.reply

        class _R:
            content = reply

        return _R()


@pytest.mark.asyncio
async def test_invalid_code_is_caught_by_the_syntax_verifier_not_by_the_model(session, tmp_path, monkeypatch):
    root = _project(tmp_path)
    run, leaf = _verifying(session, root, None, status=TaskStatus.RUNNING, meta={"model_operation": True, "atomic": True})
    provider = _Writer('{"path": "calc.py", "content": "def add(a, b:\\n    return a + b\\n", "summary": "pronto, corrigido"}')
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_failed"
    [ev] = _evidence(session, leaf.id)
    assert ev.detail_json["state"] == "reprovado"
    assert "sintaxe inválida" in ev.summary
    task = TaskService(session).get_task(leaf.id)
    assert task.status == TaskStatus.RETRY_PENDING.value
    assert "sintaxe" in task.metadata_json["last_failure"]["detail"]


@pytest.mark.asyncio
async def test_missing_tool_blocks_the_verification_instead_of_failing_the_code(session, tmp_path):
    run, leaf = _verifying(
        session, _project(tmp_path), {"type": "command", "command": ["programa-que-nao-existe-xyz"]}, approve=True
    )

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_blocked"
    [ev] = _evidence(session, leaf.id)
    assert ev.passed is None and ev.detail_json["state"] == "bloqueado"
    assert "executável" in ev.detail_json["reason"]
    task = TaskService(session).get_task(leaf.id)
    assert task.status == TaskStatus.BLOCKED.value
    assert task.metadata_json["last_failure"]["category"] == "configuration"


@pytest.mark.asyncio
async def test_unapproved_command_is_blocked_not_failed(session, tmp_path):
    run, leaf = _verifying(session, _project(tmp_path), {"type": "command", "command": ["true"]}, approve=False)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_blocked"
    assert TaskService(session).get_task(leaf.id).metadata_json["last_failure"]["cause"] == "approval_required"


@pytest.mark.asyncio
async def test_inconclusive_verification_is_never_success(session, tmp_path):
    run, leaf = _verifying(session, _project(tmp_path), {"type": "acceptance_manual"})

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_inconclusive"
    [ev] = _evidence(session, leaf.id)
    assert ev.passed is None and ev.detail_json["state"] == "inconclusivo"
    assert not verification_evidence_ok(session, TaskService(session).get_task(leaf.id))


@pytest.mark.asyncio
async def test_later_change_marks_old_evidence_stale_without_deleting_it(session, tmp_path):
    root = _project(tmp_path)
    run, leaf = _verifying(session, root, {"type": "pytest", "path": "tests"})
    await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    (root / "tests" / "test_calc.py").write_text((root / "tests" / "test_calc.py").read_text() + "\n# novo\n")
    task = TaskService(session).get_task(leaf.id)
    parent = TaskService(session).get_task(task.parent_id)
    parent.status = TaskStatus.COMPLETED.value
    session.flush()

    assert reopen_verification_gaps(session, parent.id) == [leaf.id]
    [ev] = _evidence(session, leaf.id)
    assert ev.detail_json["state"] == "desatualizado"
    assert ev.detail_json["previous_state"] == "aprovado"
    assert ev.detail_json["invalidated_at"] and "mudaram" in ev.detail_json["invalidated_reason"]
    assert not verification_evidence_ok(session, TaskService(session).get_task(leaf.id))
