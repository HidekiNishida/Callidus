# tests/test_guides_and_closing.py
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.guides.discover import discover_guides, reply_capabilities
from agent.orchestrator.closing import compose_final_markdown, ensure_closing_stages, usable_markdown
from agent.orchestrator.decomposition import GENERIC_TEMPLATE, resolve_decomposition_plan
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


def test_discovers_common_agent_guides(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Guia\n\nRode pytest.\n", encoding="utf-8")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("Prefira funções pequenas.\n", encoding="utf-8")
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "estilo.mdc").write_text("---\nalwaysApply: true\n---\n\nUse aspas duplas.\n", encoding="utf-8")
    skill = tmp_path / "skills" / "revisar"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: revisar\ndescription: Revisar um diff\n---\n\npassos\n", encoding="utf-8")
    (tmp_path / "llms.txt").write_text("# Docs\n- [API](docs/api.md)\n", encoding="utf-8")
    outside = tmp_path / "node_modules"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("não ler\n", encoding="utf-8")

    hits = discover_guides(tmp_path, objective="olhar o pacote")
    kinds = {hit.kind for hit in hits}
    assert {"agents", "claude", "cursor-rule", "skill", "llms"} <= kinds
    rule = next(hit for hit in hits if hit.kind == "cursor-rule")
    assert "aspas duplas" in rule.text
    assert "alwaysApply" not in rule.text
    assert all("não ler" not in hit.text for hit in hits)
    assert reply_capabilities("qwen3-vl:8b")["vision"] is True
    assert reply_capabilities("gpt-oss:20b")["vision"] is False
    assert reply_capabilities("gpt-oss:20b")["tables"] is True


@pytest.mark.asyncio
async def test_generic_plan_ends_with_final_answer(tmp_path: Path):
    settings = Settings(allow_mock_fallback=False, use_generic_decomposition_template=True)
    plan, source = await resolve_decomposition_plan(
        settings=settings,
        run_config={"provider": "mock", "use_generic_template": True},
        objective="documentar o módulo",
        project_root=str(tmp_path),
    )
    assert source == "generic-template"
    assert any((item.metadata or {}).get("verification") for item in plan.subtasks)
    assert (plan.subtasks[-1].metadata or {}).get("final_answer") is True
    again = ensure_closing_stages(plan)
    assert len(again.subtasks) == len(plan.subtasks)
    assert len(GENERIC_TEMPLATE.subtasks) == 3


def test_fallback_answer_uses_table_and_sources():
    text = compose_final_markdown(
        objective="Criar a calculadora",
        stages=[{"title": "Testes", "status": "COMPLETED", "sources": ["calculator.py"]}],
    )
    assert usable_markdown(text)
    assert "| Etapa | Estado |" in text
    assert "`calculator.py`" in text


@pytest.mark.asyncio
async def test_run_writes_final_answer(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Projeto\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Pedido", objective="Explicar o resultado"))
    TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Resposta final",
            objective="Concluir",
            parent_id=root.id,
            metadata={"final_answer": True, "model_operation": True},
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "model_id": "mock-model"}),
    )
    session.commit()
    await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=8)
    session.commit()
    parent = TaskService(session).get_task(root.id)
    answer = (parent.consolidated_result_json or {}).get("final_answer", "")
    assert "Conclusão" in answer
    assert "| Etapa | Estado |" in answer
    child = [t for t in TaskService(session).list_tasks(project.id) if t.parent_id == root.id][0]
    assert child.status == TaskStatus.COMPLETED.value
    session.close()
