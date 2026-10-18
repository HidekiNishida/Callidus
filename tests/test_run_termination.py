# tests/test_run_termination.py — pai nunca conclui com filho falho; run parado termina explicado, sem laço
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import children_of, consolidate_parent
from agent.orchestrator.replan import REPLAN_BUDGET, replan_decision
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, ExecutionRunModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _tree(session, tmp_path: Path, *, replans: int = 0):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Pedido", objective="Criar e testar", metadata={"replan_count": replans}),
    )
    root.status = TaskStatus.PLANNING.value
    done = tasks.create_task(
        project.id, TaskCreate(title="Escrever código", objective="x", parent_id=root.id, metadata={"atomic": True})
    )
    done.status = TaskStatus.COMPLETED.value
    broken = tasks.create_task(
        project.id,
        TaskCreate(
            title="Rodar testes",
            objective="y",
            parent_id=root.id,
            metadata={
                "atomic": True,
                "last_failure": {"category": "configuration", "cause": "missing_executable", "detail": "pytest ausente"},
            },
        ),
    )
    broken.status = TaskStatus.FAILED.value
    session.flush()
    return project, root, done, broken


def test_failed_child_never_completes_the_parent(session, tmp_path):
    _, root, done, broken = _tree(session, tmp_path)
    root.status = TaskStatus.VERIFYING.value
    session.flush()

    report = consolidate_parent(session, root.id)

    assert report["achieved"] is False
    assert [item["title"] for item in report["pending"]] == ["Rodar testes"]
    assert report["pending"][0]["reason"] == "pytest ausente"
    assert TaskService(session).get_task(root.id).status == TaskStatus.VERIFYING.value
    assert TaskService(session).get_task(done.id).status == TaskStatus.COMPLETED.value


def test_running_parent_completes_through_valid_transitions(session, tmp_path):
    _, root, _, broken = _tree(session, tmp_path)
    broken.status = TaskStatus.CANCELLED.value
    root.status = TaskStatus.RUNNING.value
    session.flush()

    report = consolidate_parent(session, root.id)

    assert report["achieved"] is True
    assert TaskService(session).get_task(root.id).status == TaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_stalled_run_ends_explained_and_keeps_finished_work(session, tmp_path):
    project, root, done, broken = _tree(session, tmp_path, replans=2)
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()

    log = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=10)
    session.commit()

    assert log[-1]["action"] == "run_stalled"
    assert len(log) == 1
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.FAILED.value
    stored_root = TaskService(session).get_task(root.id)
    assert stored_root.status == TaskStatus.BLOCKED.value
    report = stored_root.consolidated_result_json
    assert report["achieved"] is False
    assert "## Não concluído" in report["final_answer"]
    assert "Conclusão" not in report["final_answer"]
    assert "pytest ausente" in report["final_answer"]
    assert [item["title"] for item in report["pending"]] == ["Rodar testes"]
    assert TaskService(session).get_task(done.id).status == TaskStatus.COMPLETED.value
    events = session.query(EventLogModel).filter(EventLogModel.event_type == "run.stalled").all()
    assert len(events) == 1

    again = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    assert again["action"] == "run_terminal"


@pytest.mark.asyncio
async def test_configuration_failure_is_not_replanned_and_the_stop_says_why(session, tmp_path):
    project, root, done, broken = _tree(session, tmp_path, replans=0)
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "run_stalled"
    assert "precisa de ação externa (configuration)" in out["reason"]
    assert len(children_of(session, root.id)) == 2


@pytest.mark.asyncio
async def test_replanned_failure_no_longer_blocks_the_parent(session, tmp_path):
    project, root, done, broken = _tree(session, tmp_path, replans=0)
    broken.metadata_json = {
        "atomic": True,
        "last_failure": {"category": "operational_limit", "cause": "attempts_exhausted", "detail": "limite de tentativas"},
    }
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()
    orchestrator = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    first = await orchestrator.step(run.id)
    session.commit()

    assert first["action"] == "replanned"
    assert TaskService(session).get_task(done.id).status == TaskStatus.COMPLETED.value
    assert TaskService(session).get_task(broken.id).metadata_json["superseded_by_replan"] is True
    added = [kid for kid in children_of(session, root.id) if (kid.metadata_json or {}).get("replan")]
    follow = next(kid for kid in added if kid.title == "Seguir com o plano corrigido")
    assert follow.kind == "subsystem"
    assert follow.metadata_json["replan_count"] == 1
    assert "limite de tentativas" in follow.objective

    for kid in added:
        kid.status = TaskStatus.COMPLETED.value
    session.commit()
    log = await orchestrator.run_until_idle(run.id, max_steps=10)
    session.commit()

    assert log[-1]["action"] == "run_completed"
    assert TaskService(session).get_task(root.id).status == TaskStatus.COMPLETED.value


def test_replan_policy_needs_budget_and_progress(session, tmp_path):
    _, root, _, broken = _tree(session, tmp_path)
    broken.metadata_json = {"last_failure": {"category": "change_strategy", "cause": "context_budget", "detail": "grande"}}
    assert replan_decision({}, broken, completed=1).replan
    assert not replan_decision({"replan_count": REPLAN_BUDGET}, broken, completed=1).replan
    stale = {"replan_count": 1, "replan_history": [{"completed": 1, "reason": "grande"}]}
    assert replan_decision(stale, broken, completed=1).reason == "o replanejamento anterior não trouxe progresso"
    assert replan_decision(stale, broken, completed=2).replan
