# tests/test_decompose_loop.py — alteração não vira o mesmo plano de novo
from pathlib import Path

import pytest

from agent.api.main import _mark_repeated_thought
from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.closing import ensure_closing_stages
from agent.orchestrator.consolidation import children_of
from agent.orchestrator.decomposition import (
    GENERIC_TEMPLATE,
    DecompositionResult,
    SubTaskSpec,
    plan_copies_siblings,
    seal_repeated_steps,
)
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.mark.asyncio
async def test_page_request_checks_html_instead_of_pytest(tmp_path: Path):
    from agent.config import Settings
    from agent.orchestrator.decomposition import resolve_decomposition_plan

    plan, source = await resolve_decomposition_plan(
        settings=Settings(use_generic_decomposition_template=True, allow_mock_fallback=False),
        run_config={"provider": "mock", "use_generic_template": True},
        objective="Crie um modelo de site de vendas",
        project_root=str(tmp_path),
    )
    assert source == "page-template"
    checks = [(item.metadata or {}).get("verification") for item in plan.subtasks]
    assert any(isinstance(item, dict) and item.get("type") == "file_contains" for item in checks)
    assert not any(isinstance(item, dict) and item.get("type") == "pytest" for item in checks)
    write = next(item for item in plan.subtasks if (item.metadata or {}).get("prompt_key") == "page")
    assert "index.html" in write.objective


@pytest.mark.asyncio
async def test_model_timeout_is_recorded_and_does_not_stay_running(session, tmp_path: Path, monkeypatch):
    from agent.providers.base import ProviderError

    project = ProjectService(session).create_project(ProjectCreate(name="site", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Crie um modelo de site de vendas", objective="Crie um modelo de site de vendas"),
    )
    root.status = TaskStatus.COMPLETED.value
    change = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Escrever a página",
            objective="Escreva index.html",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True, "prompt_key": "page"},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    class _Down:
        name = "mock"

        async def chat(self, request):
            raise ProviderError("tempo esgotado")

    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: _Down())
    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "model_operation_error"
    assert TaskService(session).get_task(change.id).status == TaskStatus.RETRY_PENDING.value


def test_usage_adds_prompt_and_completion():
    from agent.orchestrator.usage import accumulate_usage

    meta = accumulate_usage(None, 120, 30)
    meta = accumulate_usage(meta, 10, 5)
    assert meta["usage"] == {"prompt": 130, "completion": 35, "total": 165}


def test_same_title_becomes_a_leaf_change():
    plan = seal_repeated_steps(
        "Aplicar alterações",
        DecompositionResult(
            subtasks=[
                SubTaskSpec(title="Inspecionar código", objective="ver", metadata={"tool": "list_dir"}),
                SubTaskSpec(title="Aplicar alterações", objective="fazer"),
            ]
        ),
    )
    assert plan.subtasks[1].metadata["model_operation"] is True
    assert plan.subtasks[1].metadata["atomic"] is True
    assert "model_operation" not in (plan.subtasks[0].metadata or {})


def test_copied_plan_matches_sibling_titles():
    titles = [item.title for item in GENERIC_TEMPLATE.subtasks]
    assert plan_copies_siblings(titles, list(reversed(titles)), "Aplicar alterações")
    assert not plan_copies_siblings(titles, ["Outra coisa", "Aplicar alterações"], "Aplicar alterações")


def test_repeated_thought_is_marked():
    thoughts: list[dict] = []
    _mark_repeated_thought(thoughts, {"text": "Pensando em como dividir «Aplicar alterações»."})
    _mark_repeated_thought(thoughts, {"text": "Vou fazer: Inspecionar código."})
    _mark_repeated_thought(thoughts, {"text": "Pensando em como dividir «Aplicar alterações»."})
    assert thoughts[0]["repeat"] == 1
    assert thoughts[2]["repeat"] == 2
    assert "igual" not in thoughts[0]["text"]


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    factory = build_session_factory(engine)
    opened = factory()
    yield opened
    opened.close()


@pytest.mark.asyncio
async def test_model_operation_is_not_decomposed_again(session, tmp_path: Path):
    project = ProjectService(session).create_project(ProjectCreate(name="site", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Crie um modelo de site de vendas", objective="Crie um modelo de site de vendas"),
    )
    root.status = TaskStatus.PLANNING.value
    change = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Aplicar alterações",
            objective="Implementar a mudança pedida no objetivo pai",
            parent_id=root.id,
            metadata={"model_operation": True, "prompt_key": "implement"},
        ),
    )
    change.status = TaskStatus.PLANNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "operation_ready"
    assert out["task_id"] == str(change.id)
    assert children_of(session, change.id) == []
    assert TaskService(session).get_task(change.id).status == TaskStatus.READY.value


@pytest.mark.asyncio
async def test_same_plan_is_executed_instead_of_nested(session, tmp_path: Path):
    project = ProjectService(session).create_project(ProjectCreate(name="site", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Crie um modelo de site de vendas", objective="Crie um modelo de site de vendas"),
    )
    root.status = TaskStatus.PLANNING.value
    tasks = TaskService(session)
    created = []
    closed = ensure_closing_stages(GENERIC_TEMPLATE.model_copy(deep=True))
    for spec in closed.subtasks:
        task = tasks.create_task(
            project.id,
            TaskCreate(title=spec.title, objective=spec.objective, parent_id=root.id, metadata={}),
        )
        created.append(task)
    for task in created:
        if task.title != "Aplicar alterações":
            task.status = TaskStatus.COMPLETED.value
        else:
            task.status = TaskStatus.PLANNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    target = next(task for task in created if task.title == "Aplicar alterações")
    fresh = tasks.get_task(target.id)
    assert out["action"] == "operation_ready"
    assert children_of(session, target.id) == []
    assert fresh.metadata_json["model_operation"] is True
    assert fresh.metadata_json["atomic"] is True
