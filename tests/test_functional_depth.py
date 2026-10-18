# tests/test_functional_depth.py — dividir não depende de profundidade fixa; proteção contra recursão é separada
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import children_of
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


def _chain(session, tmp_path: Path, depth: int, leaf_objective: str):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Nível 0", objective="Sistema de pedidos completo"))
    root.status = TaskStatus.PLANNING.value
    parent = root
    for level in range(1, depth):
        parent = tasks.create_task(
            project.id,
            TaskCreate(title=f"Nível {level}", objective=f"Parte {level} do sistema", parent_id=parent.id, kind="subsystem"),
        )
        parent.status = TaskStatus.PLANNING.value
    leaf = tasks.create_task(
        project.id, TaskCreate(title="Folha", objective=leaf_objective, parent_id=parent.id, kind="subsystem")
    )
    leaf.status = TaskStatus.PLANNING.value
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    session.commit()
    return run, leaf


@pytest.mark.asyncio
async def test_task_deeper_than_the_old_limit_is_still_decomposed(session, tmp_path):
    run, leaf = _chain(session, tmp_path, depth=7, leaf_objective="Implementar o cálculo de frete em frete.py")

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "decomposed"
    assert out["task_id"] == str(leaf.id)
    assert children_of(session, leaf.id)


@pytest.mark.asyncio
async def test_objective_repeated_from_an_ancestor_triggers_the_guard(session, tmp_path):
    run, leaf = _chain(session, tmp_path, depth=3, leaf_objective="Parte 1 do sistema")

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] in {"operation_ready", "operation_wait_deps"}
    meta = TaskService(session).get_task(leaf.id).metadata_json
    assert "repete" in meta["recursion_guard"]
    assert meta["model_operation"] is True


@pytest.mark.asyncio
async def test_task_budget_is_a_protection_not_a_depth_rule(session, tmp_path):
    run, leaf = _chain(session, tmp_path, depth=2, leaf_objective="Escrever frete.py")

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data", max_tasks_per_run=3)).step(run.id)

    assert out["action"] in {"operation_ready", "operation_wait_deps"}
    assert "limite de 3 tarefas" in TaskService(session).get_task(leaf.id).metadata_json["recursion_guard"]
