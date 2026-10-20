"""
Arquivo: tests/test_strategy_and_decomposition.py
Nome: test_strategy_and_decomposition.py
Propósito: verificar a camada estratégica, a decomposição adaptativa e a integridade da consolidação e da verificação.
Responsabilidade: camada de testes — comportamento da análise estratégica, da decomposição por domínio e da consolidação com ressalvas.
Componentes: estratégia por tipo de pedido, decomposição por especialidade, falha de etapa opcional, dependência opcional que falha e novos verificadores de arquivo e análise estática.
Dependências: agent.orchestrator (strategy, atomizer, consolidation), agent.verification.runner, agent.services (project, task), agent.persistence.database, pytest.
Observações: banco e workspace temporários por teste; o modelo não é chamado em nenhum cenário.

Testes da camada estratégica, decomposição adaptativa e integridade
"""
from pathlib import Path
import pytest
import uuid

from agent.orchestrator.strategy import ProfessionalStrategist
from agent.orchestrator.atomizer import adaptive_decompose_operation, should_decompose_further
from agent.orchestrator.consolidation import consolidate_parent, is_optional
from agent.verification.runner import run_verification
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.config import Settings


def test_professional_strategist_preserves_intention_and_selects_specialties():
    """A análise estratégica preserva o pedido original e escolhe o domínio, a especialidade principal e as de revisão."""
    strategist = ProfessionalStrategist()

    # 1. Consulta simples
    simple_req = "como funciona a persistência no sqlite?"
    strat_simple = strategist.analyze(simple_req)
    assert strat_simple.original_request == simple_req
    assert strat_simple.complexity == "simple"
    assert strat_simple.domain == "consultation"
    assert len(strat_simple.execution_sequence) == 1

    # 2. Bugfix
    bug_req = "corrigir bug de KeyError no processamento de eventos ao reiniciar o servidor"
    strat_bug = strategist.analyze(bug_req)
    assert strat_bug.original_request == bug_req
    assert strat_bug.domain == "debugging_and_root_cause"
    assert strat_bug.lead_specialty == "debugging_root_cause"
    assert "testing_quality_assurance" in strat_bug.review_specialties
    assert len(strat_bug.extracted_requirements) >= 2
    assert len(strat_bug.risks) >= 1
    assert len(strat_bug.acceptance_criteria) >= 1
    assert len(strat_bug.execution_sequence) == 3

    # 3. Engenharia de software / Feature
    feat_req = "implementar novo endpoint REST para gerenciar configurações e métricas do worker"
    strat_feat = strategist.analyze(feat_req)
    assert strat_feat.original_request == feat_req
    assert strat_feat.domain == "software_engineering"
    assert strat_feat.lead_specialty == "software_engineering"
    assert "testing_quality_assurance" in strat_feat.review_specialties


def test_adaptive_decompose_operation_produces_domain_specific_subtasks():
    # Bugfix decomposition
    """A decomposição adaptativa gera etapas da especialidade escolhida, encadeadas na ordem certa."""
    plan_bug = adaptive_decompose_operation("Corrigir falha de conexão no banco", lead_specialty="debugging_root_cause")
    assert len(plan_bug.subtasks) == 3
    assert "diagnosticar" in plan_bug.subtasks[0].title.lower() or "reproduzir" in plan_bug.subtasks[0].title.lower()
    assert "correção" in plan_bug.subtasks[1].title.lower() or "corrigir" in plan_bug.subtasks[1].title.lower()
    assert "não-regressão" in plan_bug.subtasks[2].title.lower() or "verificar" in plan_bug.subtasks[2].title.lower()
    assert plan_bug.subtasks[1].depends_on_indices == [0]
    assert plan_bug.subtasks[2].depends_on_indices == [1]

    # Refactor decomposition
    plan_refactor = adaptive_decompose_operation("Refatorar módulo de rotas para reduzir acoplamento", lead_specialty="refactoring_clean_code")
    assert len(plan_refactor.subtasks) == 3
    assert plan_refactor.subtasks[1].depends_on_indices == [0]

    # Atomize flag triggers should_decompose_further
    assert should_decompose_further(objective="x", metadata={"atomize": True}, kind="OPERATION", attempt_count=1, has_children=False)
    # Atomic flag prevents further decomposition
    assert not should_decompose_further(objective="x", metadata={"atomic": True, "atomize": True}, kind="OPERATION", attempt_count=1, has_children=False)


def test_optional_subtask_failure_allows_completion_with_caveats(tmp_path: Path):
    """A falha de uma etapa opcional permite concluir o pai, com a ressalva registrada."""
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    with factory() as session:
        ts = TaskService(session)
        ps = ProjectService(session)
        project = ps.create_project(ProjectCreate(name="test", root_path=str(tmp_path)))

        parent = ts.create_task(project.id, TaskCreate(title="Tarefa Pai", objective="Objetivo principal"))
        child1 = ts.create_task(
            project.id,
            TaskCreate(title="Subtarefa Obrigatória", objective="Sub 1", parent_id=parent.id),
        )
        child2 = ts.create_task(
            project.id,
            TaskCreate(
                title="Subtarefa Opcional (benchmark)",
                objective="Sub 2",
                parent_id=parent.id,
                metadata={"optional": True},
            ),
        )
        session.commit()

        # child1 conclui com sucesso
        ts.update_status(child1.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        ts.update_status(child1.id, TaskStatusUpdate(status=TaskStatus.READY))
        ts.update_status(child1.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
        ts.update_status(child1.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        ts.update_status(child1.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))

        # child2 falha (mas é opcional!)
        ts.update_status(child2.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        ts.update_status(child2.id, TaskStatusUpdate(status=TaskStatus.READY))
        ts.update_status(child2.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
        ts.update_status(child2.id, TaskStatusUpdate(status=TaskStatus.FAILED, reason="benchmark não rodou"))
        session.commit()

        assert is_optional(child2) is True
        assert is_optional(child1) is False

        # Consolidação do pai
        ts.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        report = consolidate_parent(session, parent.id)
        session.commit()

        assert report is not None
        assert report["achieved"] is True  # O pai foi alcançado porque a falha foi opcional!
        assert report["with_caveats"] is True
        assert len(report["caveats"]) == 1
        assert report["caveats"][0]["task_id"] == str(child2.id)

        parent_updated = ts.get_task(parent.id)
        assert parent_updated.status == TaskStatus.COMPLETED.value
        assert parent_updated.metadata_json.get("completed_with_caveats") is True


def test_optional_dependency_failure_does_not_block_downstream_task(tmp_path: Path):
    """A falha de uma dependência opcional não bloqueia a etapa que depende dela."""
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    with factory() as session:
        ts = TaskService(session)
        ps = ProjectService(session)
        project = ps.create_project(ProjectCreate(name="dep_test", root_path=str(tmp_path)))

        optional_dep = ts.create_task(
            project.id,
            TaskCreate(title="Opcional", objective="Gerar cache", metadata={"optional": True}),
        )
        dependent_task = ts.create_task(
            project.id,
            TaskCreate(title="Principal", objective="Rodar funcionalidade"),
        )
        ts.add_dependency(dependent_task.id, TaskDependencyCreate(depends_on_task_id=optional_dep.id))
        session.commit()

        # Antes de rodar: dependência não satisfeita
        assert ts.dependencies_satisfied(dependent_task.id) is False

        # optional_dep falha
        ts.update_status(optional_dep.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        ts.update_status(optional_dep.id, TaskStatusUpdate(status=TaskStatus.READY))
        ts.update_status(optional_dep.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
        ts.update_status(optional_dep.id, TaskStatusUpdate(status=TaskStatus.FAILED, reason="cache indisponível"))
        session.commit()

        # Por ser opcional, a falha não bloqueia dependent_task!
        assert ts.dependencies_satisfied(dependent_task.id) is True


@pytest.mark.asyncio
async def test_new_verifiers_file_exists_and_static_analysis(tmp_path: Path):
    # 1. file_exists
    """Os verificadores de existência de arquivo e de análise estática aprovam e reprovam conforme o conteúdo."""
    target_file = tmp_path / "app.py"
    target_file.write_text("print('hello world')\n", encoding="utf-8")

    res_ok = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "file_exists", "path": "app.py", "min_bytes": 5},
    )
    assert res_ok.passed is True
    assert "existe" in res_ok.summary

    res_fail = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "file_exists", "path": "non_existent.py"},
    )
    assert res_fail.passed is False

    # 2. static_analysis
    res_ast_ok = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "static_analysis", "path": "app.py"},
    )
    assert res_ast_ok.passed is True

    # Introduzir erro sintático
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken_syntax(\n", encoding="utf-8")
    res_ast_fail = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "static_analysis", "path": "."},
    )
    assert res_ast_fail.passed is False
    assert "bad.py" in res_ast_fail.detail.get("problems", {})
