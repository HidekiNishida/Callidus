# tests/test_resume_integrity.py — retomada após reabrir o banco e evidência que fica desatualizada
import shutil
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.orchestrator.consolidation import collect_evidences, verification_evidence_ok
from agent.orchestrator.global_verify import evaluate_global_acceptance, reopen_verification_gaps
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, ExecutionRunModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.verification.fingerprint import fingerprint, is_current, snapshot


def test_fingerprint_follows_files_and_ignores_the_database(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "agent.db").write_text("a")
    first = fingerprint(str(tmp_path), ["."])

    (tmp_path / "agent.db").write_text("b")
    assert fingerprint(str(tmp_path), ["."]) == first

    (tmp_path / "app.py").write_text("x = 22\n")
    assert fingerprint(str(tmp_path), ["."]) != first

    art = snapshot(str(tmp_path), {"type": "file_contains", "path": "app.py", "contains": "x"})
    assert is_current(art)
    (tmp_path / "app.py").unlink()
    assert not is_current(art)
    assert is_current(None)
    assert snapshot(str(tmp_path), {"type": "acceptance_manual"}) is None


@pytest.mark.asyncio
async def test_run_resumes_after_reopening_the_database(tmp_path: Path):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    settings = Settings(data_dir=tmp_path / "data")

    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="e2e", root_path=str(workspace)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Objetivo E2E", objective="e2e corrigir calc.py e validar")
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    first = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=4)
    session.commit()
    assert "run_completed" not in [x.get("action") for x in first]
    run_id, root_id = run.id, root.id
    session.close()
    engine.dispose()

    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    rest = await RunOrchestrator(session, settings).run_until_idle(run_id, max_steps=80)
    session.commit()

    assert rest[-1]["action"] == "run_completed"
    assert session.get(ExecutionRunModel, run_id).status == RunStatus.COMPLETED.value
    assert TaskService(session).get_task(root_id).status == TaskStatus.COMPLETED.value
    assert "return a + b" in (workspace / "calc.py").read_text(encoding="utf-8")
    session.close()
    engine.dispose()


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _verified_tree(session, tmp_path: Path):
    (tmp_path / "frete.py").write_text("def frete():\n    return 10\n")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="Frete"))
    spec = {"type": "file_contains", "path": "frete.py", "contains": "return 10"}
    leaf = tasks.create_task(
        project.id,
        TaskCreate(title="Escrever frete", objective="frete.py", parent_id=root.id, metadata={"verification": spec}),
    )
    for task in (leaf, root):
        for status in (TaskStatus.PLANNING, TaskStatus.VERIFYING, TaskStatus.COMPLETED):
            tasks.update_status(task.id, TaskStatusUpdate(status=status))
    session.add(
        EvidenceModel(
            task_id=leaf.id,
            verifier="file_contains",
            passed=True,
            summary="trecho encontrado",
            detail_json={"artifacts": snapshot(str(tmp_path), spec)},
        )
    )
    session.commit()
    return project, root, leaf


def test_external_change_makes_evidence_stale_and_is_never_deleted(session, tmp_path):
    _, root, leaf = _verified_tree(session, tmp_path)
    assert verification_evidence_ok(session, leaf)
    assert evaluate_global_acceptance(session, root.id)[0]

    (tmp_path / "frete.py").write_text("def frete():\n    return 120\n")

    assert not verification_evidence_ok(session, leaf)
    ok, reason = evaluate_global_acceptance(session, root.id)
    assert not ok and "desatualizada" in reason

    assert reopen_verification_gaps(session, root.id) == [leaf.id]
    reopened = TaskService(session).get_task(leaf.id)
    assert reopened.status == TaskStatus.VERIFYING.value
    assert reopened.metadata_json["last_failure"]["cause"] == "stale_evidence"
    assert len(collect_evidences(session, leaf.id)) == 1


def test_latest_failed_evidence_overrides_an_older_pass(session, tmp_path):
    _, _, leaf = _verified_tree(session, tmp_path)
    session.add(EvidenceModel(task_id=leaf.id, verifier="file_contains", passed=False, summary="trecho ausente"))
    session.commit()
    assert not verification_evidence_ok(session, leaf)


@pytest.mark.asyncio
async def test_stale_evidence_is_rechecked_before_repeating_the_operation(session, tmp_path, monkeypatch):
    project, root, leaf = _verified_tree(session, tmp_path)
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={}))
    session.commit()

    class _NoModel:
        name = "mock"
        last_usage = None

        async def chat(self, request):
            raise AssertionError("não deveria chamar o modelo")

    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: _NoModel())
    (tmp_path / "frete.py").write_text("# comentário novo\ndef frete():\n    return 10\n")
    reopen_verification_gaps(session, root.id)
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verified_ok"
    assert verification_evidence_ok(session, TaskService(session).get_task(leaf.id))
    assert len(collect_evidences(session, leaf.id)) == 2
