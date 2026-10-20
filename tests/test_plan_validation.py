"""
Arquivo: tests/test_plan_validation.py
Nome: test_plan_validation.py
Propósito: verificar a validação do plano antes da execução: cobertura de requisitos, dependências e reparo das falhas.
Responsabilidade: camada de testes — comportamento do veredito do plano, do reparo automático e do replanejamento.
Componentes: cobertura completa, requisito não coberto, tarefa sem critério verificável, dependências circulares ou inexistentes, dependência de tarefa cancelada, dependência externa, replanejamento e bloqueio por plano inviável.
Dependências: agent.orchestrator (plan_validation, decomposition, requirements, replan, runner), agent.services (project, run, task), agent.persistence (database, models), pytest.
Observações: banco SQLite temporário por teste (tmp_path) e provedor de modelo mock; nenhum serviço externo é chamado.

validação do plano antes da execução (cenários 1–9 da especificação)
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec, apply_decomposition
from agent.orchestrator.plan_validation import (
    PlanVerdict,
    active_children,
    sanitize_spec,
    validate_and_repair,
    validate_children,
)
from agent.orchestrator.requirements import ensure_requirements
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, TaskDependencyModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

TWO = "Pedido:\n- criar a.py\n- criar b.py"


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _root(session, tmp_path, objective=TWO):
    """Cria o projeto e a tarefa raiz em planejamento, já com os requisitos garantidos."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective=objective))
    root.status = TaskStatus.PLANNING.value
    ensure_requirements(session, root)
    return project, root


def _write(title, req, path):
    """Monta a especificação de uma subtarefa que cobre um requisito e tem verificação por arquivo."""
    return SubTaskSpec(
        title=title,
        objective=f"criar {path}",
        metadata={
            "model_operation": True,
            "covers": [req] if req else [],
            "verification": {"type": "file_contains", "path": path, "contains": "x"},
        },
    )


FINAL = SubTaskSpec(title="Resposta", objective="resumir", metadata={"final_answer": True, "model_operation": True, "covers": []})


def _apply(session, project, parent, specs, **kwargs):
    """Sanitiza e aplica a decomposição, e devolve o resultado da validação com o reparo."""
    plan, issues = sanitize_spec(DecompositionResult(subtasks=specs))
    apply_decomposition(session, project.id, parent.id, plan)
    session.flush()
    return validate_and_repair(
        session, parent, project_root=project.root_path, run_config=kwargs.get("config"),
        max_tasks=kwargs.get("max_tasks"), run_id=None, extra_issues=issues,
    )


def test_full_coverage_is_valid(session, tmp_path):
    """Um plano que cobre todos os requisitos é considerado válido e cada requisito tem um único responsável."""
    project, root = _root(session, tmp_path)
    result = _apply(session, project, root, [_write("A", "R1", "a.py"), _write("B", "R2", "b.py"), FINAL])

    assert result.verdict == PlanVerdict.VALID
    assert all(len(owners) == 1 for owners in result.coverage.values())
    assert root.metadata_json["plan_validation"]["version"] == 1


def test_uncovered_requirement_is_fixed_before_running(session, tmp_path):
    """Um requisito sem cobertura gera uma etapa que o atende, e a resposta final passa a depender dela."""
    project, root = _root(session, tmp_path)
    result = _apply(session, project, root, [_write("A", "R1", "a.py"), FINAL])

    assert result.initial_verdict == PlanVerdict.INCOMPLETE.value
    assert result.runnable
    added = next(k for k in active_children(session, root.id) if k.title == "Atender R2")
    assert added.metadata_json["covers"] == ["R2"] and added.kind == TaskKind.SUBSYSTEM.value
    final = next(k for k in active_children(session, root.id) if k.title == "Resposta")
    deps = session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id == final.id)).all()
    assert added.id in {d.depends_on_task_id for d in deps}


def test_task_without_verifiable_criteria_is_flagged(session, tmp_path):
    """Uma tarefa sem critério verificável é sinalizada e reparada antes da execução."""
    project, root = _root(session, tmp_path, "- criar a.py")
    look = SubTaskSpec(title="Olhar", objective="listar", metadata={"tool": "list_dir", "tool_args": {"path": "."}, "covers": ["R1"]})
    plan, issues = sanitize_spec(DecompositionResult(subtasks=[look, FINAL]))
    apply_decomposition(session, project.id, root.id, plan)
    session.flush()

    first = validate_children(session, root, project_root=str(tmp_path))
    assert first.verdict == PlanVerdict.INCOMPLETE
    assert "criteria_unverifiable" in {i.code for i in first.issues}

    fixed = validate_and_repair(session, root, project_root=str(tmp_path), run_config=None, max_tasks=None, run_id=None)
    assert fixed.runnable
    assert {k.title for k in active_children(session, root.id)} >= {"Olhar", "Atender R1"}


def test_circular_and_missing_dependencies_are_removed_and_recorded(session, tmp_path):
    """Dependências circulares, inexistentes e sobre si mesma são removidas e registradas nos reparos."""
    project, root = _root(session, tmp_path)
    a = _write("A", "R1", "a.py").model_copy(update={"depends_on_indices": [1, 7]})
    b = _write("B", "R2", "b.py").model_copy(update={"depends_on_indices": [0, 1]})

    result = _apply(session, project, root, [a, b, FINAL])

    assert result.initial_verdict == PlanVerdict.INCONSISTENT.value
    assert result.runnable
    assert any("circular" in fix for fix in result.fixes)
    assert any("não existe" in fix for fix in result.fixes)
    assert any("si mesma" in fix for fix in result.fixes)


def test_dependency_on_cancelled_task_is_inconsistent(session, tmp_path):
    """Depender de uma tarefa cancelada torna o plano inconsistente e o reparo devolve um plano executável."""
    project, root = _root(session, tmp_path)
    _apply(session, project, root, [_write("A", "R1", "a.py"), _write("B", "R2", "b.py"), FINAL])
    tasks = TaskService(session)
    ghost = tasks.create_task(project.id, TaskCreate(title="Velha", objective="x"))
    ghost.status = TaskStatus.CANCELLED.value
    a = next(k for k in active_children(session, root.id) if k.title == "A")
    tasks.add_dependency(a.id, TaskDependencyCreate(depends_on_task_id=ghost.id))
    session.flush()

    assert validate_children(session, root, project_root=str(tmp_path)).verdict == PlanVerdict.INCONSISTENT
    repaired = validate_and_repair(session, root, project_root=str(tmp_path), run_config=None, max_tasks=None, run_id=None)
    assert repaired.runnable and repaired.fixes


def test_external_dependency_is_identified_but_plan_still_runs(session, tmp_path):
    """Uma dependência externa é identificada e sinalizada, mas o plano continua executável."""
    project, root = _root(session, tmp_path)
    shell = SubTaskSpec(
        title="Deploy",
        objective="publicar",
        metadata={"tool": "run_command", "tool_args": {"command": "make deploy"}, "covers": ["R2"], "verification": {"type": "command", "command": "true"}},
    )
    result = _apply(session, project, root, [_write("A", "R1", "a.py"), shell, FINAL])

    assert result.verdict == PlanVerdict.WARNINGS
    assert len(result.blocked) == 1
    assert "requirement_blocked" in {i.code for i in result.issues}


def test_decomposition_cannot_drop_an_inherited_requirement(session, tmp_path):
    """A decomposição não pode descartar um requisito herdado: a etapa que o atendia é recriada."""
    project, root = _root(session, tmp_path)
    sub = TaskService(session).create_task(
        project.id, TaskCreate(title="Parte B", objective="b", parent_id=root.id, kind="subsystem", metadata={"covers": ["R2"]})
    )
    sub.status = TaskStatus.PLANNING.value
    session.flush()

    result = _apply(session, project, sub, [_write("Só A", "R1", "a.py"), _write("Lixo", "R9", "c.py")])

    assert result.initial_verdict == PlanVerdict.INCONSISTENT.value
    assert result.runnable
    titles = {k.title for k in active_children(session, sub.id)}
    assert "Atender R2" in titles


def test_inconclusive_when_coverage_cannot_be_proven(session, tmp_path):
    """Sem cobertura comprovável, o veredito é inconclusivo, mas o plano permanece executável."""
    project, root = _root(session, tmp_path)
    plain = [SubTaskSpec(title="Fazer", objective="fazer tudo", metadata={"model_operation": True}), FINAL.model_copy(update={"metadata": {"final_answer": True}})]
    result = _apply(session, project, root, plain)

    assert result.verdict == PlanVerdict.INCONCLUSIVE
    assert result.runnable


def test_replanning_carries_the_requirements_of_the_stopped_step(session, tmp_path):
    """O replanejamento carrega para a nova etapa os requisitos da etapa que parou."""
    from agent.orchestrator.replan import replan_parent

    project, root = _root(session, tmp_path)
    _apply(session, project, root, [_write("A", "R1", "a.py"), _write("B", "R2", "b.py"), FINAL])
    a, b = (next(k for k in active_children(session, root.id) if k.title == t) for t in ("A", "B"))
    a.status = TaskStatus.COMPLETED.value
    b.status = TaskStatus.BLOCKED.value
    b.metadata_json = {**b.metadata_json, "last_failure": {"category": "recoverable", "cause": "tool_error", "detail": "x"}}
    session.flush()

    assert replan_parent(session, root)["action"] == "replanned"

    follow = next(k for k in active_children(session, root.id) if k.title == "Seguir com o plano corrigido")
    assert [c["req"] for c in follow.metadata_json["covers"]] == ["R2"]
    assert validate_children(session, root, project_root=str(tmp_path)).coverage["R2"] == [str(follow.id)]


@pytest.mark.asyncio
async def test_plan_change_is_revalidated_before_the_next_step(session, tmp_path):
    """Antes do passo seguinte, o plano alterado é revalidado e a nova versão fica registrada."""
    project, root = _root(session, tmp_path)
    _apply(session, project, root, [_write("A", "R1", "a.py"), _write("B", "R2", "b.py"), FINAL])
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    tasks = TaskService(session)
    ghost = tasks.create_task(project.id, TaskCreate(title="Velha", objective="x"))
    ghost.status = TaskStatus.CANCELLED.value
    b = next(k for k in active_children(session, root.id) if k.title == "B")
    tasks.add_dependency(b.id, TaskDependencyCreate(depends_on_task_id=ghost.id))
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "plan_revalidated"
    assert out["fixes"]
    assert root.metadata_json["plan_validation"]["version"] == 2
    events = session.scalars(select(EventLogModel).where(EventLogModel.event_type == "plan.validated")).all()
    assert len(events) == 2 and events[-1].payload_json["plan"]


@pytest.mark.asyncio
async def test_unfixable_plan_blocks_without_running_anything(session, tmp_path):
    """Um plano irrecuperável bloqueia a tarefa e cancela as etapas filhas, sem executar nada."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="Criar o arquivo app.py"))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    session.commit()
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data", max_tasks_per_run=3))

    await orch.step(run.id)
    out = await orch.step(run.id)

    assert out["action"] == "plan_invalid"
    assert out["plan"] == PlanVerdict.INFEASIBLE.value
    assert out["failure"]["cause"] == "invalid_plan"
    assert TaskService(session).get_task(root.id).status == TaskStatus.BLOCKED.value
    kids = [k for k in TaskService(session).list_tasks(project.id) if k.parent_id == root.id]
    assert kids
    assert all(k.status == TaskStatus.CANCELLED.value and k.metadata_json["invalid_plan"] for k in kids)
