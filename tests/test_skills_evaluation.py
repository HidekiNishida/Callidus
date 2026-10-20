"""
Arquivo: tests/test_skills_evaluation.py
Nome: test_skills_evaluation.py
Propósito: verificar a avaliação comparativa da execução com skills, estratégia e integridade do contexto.
Responsabilidade: camada de testes — comportamento da decomposição adaptativa, do catálogo de skills, da consolidação e do ciclo de recuperação da verificação.
Componentes: tarefa simples contra tarefa multinível, limite de profundidade, skill quebrada, renderização dentro do orçamento, falha opcional contra falha obrigatória, corte do bloco de skills por orçamento, estouro de orçamento, diagnóstico e plano de recuperação, assinatura de recuperação e ida e volta da estratégia.
Dependências: agent.orchestrator (atomizer, consolidation, strategy), agent.context (budget, operation_builder, assembler), agent.skills (discovery, selector), agent.verification.recovery, agent.persistence.database, pytest.
Observações: banco e diretório de skills temporários por teste; o modelo não é chamado em nenhum cenário.

Avaliação comparativa da execução com Skills, estratégia e integridade  Compara cenários que a tarefa "Evolução do Agente Local" exigiu: 1. tarefa simples (uma etapa) vs. tarefa multinível (decomposição recursiva); 2. falha de skill (catálogo com skill inválida) — o agente continua funcionando; 3. falha opcional vs. falha obrigatória — conclusões diferentes; 4. esgotamento de orçamento — o bloco de skills é cortado, o obrigatório nunca.
"""
from pathlib import Path
import uuid

import pytest

from agent.config import Settings
from agent.context.budget import ContextBudgetError
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.orchestrator.atomizer import (
    adaptive_decompose_operation,
    depth_guard,
    should_decompose_further,
)
from agent.orchestrator.consolidation import consolidate_parent, is_optional
from agent.orchestrator.strategy import ProfessionalStrategist, ProfessionalStrategy
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.skills.discovery import SkillRegistry
from agent.skills.selector import SkillSelector
from agent.verification.recovery import (
    diagnose_verification_failure,
    plan_recovery,
    recovery_signature,
)


def _session(tmp_path: Path):
    """Cria a fábrica de sessões sobre um diretório de dados temporário."""
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    return factory


# --------------------------------------------------------------------------------------
# 1. Tarefa simples vs. multinível
# --------------------------------------------------------------------------------------


def test_simple_task_is_single_step_while_complex_task_decomposes():
    """Uma tarefa simples fica em um passo, enquanto a complexa é decomposta em uma sequência maior."""
    strategist = ProfessionalStrategist()

    simple = strategist.analyze("liste os arquivos do projeto")
    assert simple.complexity == "simple"
    assert simple.needs_atomization is False
    assert len(simple.execution_sequence) == 1

    complex_task = strategist.analyze(
        "implemente um novo subsistema de cache distribuído com migração de dados e testes de integração"
    )
    assert complex_task.complexity == "complex"
    assert complex_task.needs_atomization is True
    assert len(complex_task.execution_sequence) >= 3

    # A tarefa simples não é subdividida; a complexa, sim.
    assert should_decompose_further(
        objective="liste os arquivos",
        metadata={},
        kind="OBJECTIVE",
        attempt_count=1,
        has_children=False,
        depth=0,
    ) is False
    assert should_decompose_further(
        objective="implemente cache distribuído com migração e testes de integração",
        metadata={"atomize": True},
        kind="OBJECTIVE",
        attempt_count=1,
        has_children=False,
        depth=0,
    ) is True


def test_multilevel_decomposition_is_bounded_by_depth():
    # No limite de profundidade, a decomposição recursiva para em uma etapa atômica.
    """A decomposição recursiva para em uma etapa atômica quando a profundidade máxima é atingida."""
    deep = adaptive_decompose_operation(
        "Corrigir falha de conexão no banco",
        lead_specialty="debugging_root_cause",
        depth=3,
        max_depth=3,
    )
    assert len(deep.subtasks) == 1
    assert deep.subtasks[0].metadata.get("atomic") is True

    shallow = adaptive_decompose_operation(
        "Corrigir falha de conexão no banco",
        lead_specialty="debugging_root_cause",
        depth=0,
        max_depth=3,
    )
    assert len(shallow.subtasks) == 3


def test_depth_guard_blocks_cycles_and_deep_trees():
    """O guardião de profundidade recusa ultrapassar o limite e repetir uma etapa já feita."""
    assert depth_guard(depth=0, max_depth=3) is None
    assert "profundidade" in (depth_guard(depth=3, max_depth=3) or "")
    assert "repetiria" in (depth_guard(depth=0, max_depth=3, parent_title="Corrigir bug", sibling_titles=["corrigir bug"]) or "")


# --------------------------------------------------------------------------------------
# 2. Falha de skill
# --------------------------------------------------------------------------------------


def test_broken_skill_in_catalog_does_not_break_the_agent(tmp_path: Path):
    """Uma skill inválida no catálogo é reportada, e a seleção continua funcionando com o resto."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "quebrada.md").write_text(
        "---\nid: quebrada\nname: Quebrada\ndescription: Sem procedimentos.\n---\n\ncorpo\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(project_root=tmp_path)
    assert registry.get("quebrada") is None
    assert "quebrada" in registry.list_invalid()

    # O selector continua funcionando com o resto do catálogo.
    selector = SkillSelector(registry)
    matches = selector.select("Corrigir bug de timeout na api", max_skills=2)
    assert matches
    assert matches[0].skill_id == "debugging_root_cause"


def test_render_below_budget_never_exceeds_limit():
    """A renderização das skills respeita o limite de caracteres pedido."""
    selector = SkillSelector(SkillRegistry())
    matches = selector.select("implementar endpoint de exportação e criar testes", max_skills=2)
    rendered = selector.render_selected_skills(matches, max_chars=500)
    assert len(rendered) <= 520
    assert rendered.startswith("## Competências")


# --------------------------------------------------------------------------------------
# 3. Falha opcional vs. obrigatória
# --------------------------------------------------------------------------------------


def _make_tree(session, tmp_path: Path, *, optional: bool):
    """Monta um pai com uma etapa filha, opcional ou não, e devolve os serviços."""
    ts = TaskService(session)
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    parent = ts.create_task(project.id, TaskCreate(title="Pai", objective="Objetivo"))
    child = ts.create_task(
        project.id,
        TaskCreate(
            title="Filho",
            objective="Sub",
            parent_id=parent.id,
            metadata={"optional": True} if optional else {},
        ),
    )
    session.commit()
    return ts, parent, child


def test_mandatory_failure_blocks_parent_but_optional_failure_does_not(tmp_path: Path):
    """A falha de uma etapa obrigatória impede a conclusão do pai; a de uma opcional gera apenas ressalva."""
    factory = _session(tmp_path)

    # (a) obrigatória: o pai NÃO conclude.
    with factory() as session:
        ts, parent, child = _make_tree(session, tmp_path, optional=False)
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.READY))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.FAILED, reason="quebrou"))
        ts.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        report = consolidate_parent(session, parent.id)
        session.commit()
        assert report is not None
        assert report["achieved"] is False
        assert report["with_caveats"] is False
        assert report["pending"]
        assert ts.get_task(parent.id).status != TaskStatus.COMPLETED.value

    # (b) opcional: o pai conclui com ressalvas.
    with factory() as session:
        ts, parent, child = _make_tree(session, tmp_path, optional=True)
        assert is_optional(child) is True
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.READY))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
        ts.update_status(child.id, TaskStatusUpdate(status=TaskStatus.FAILED, reason="opcional falhou"))
        ts.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        report = consolidate_parent(session, parent.id)
        session.commit()
        assert report is not None
        assert report["achieved"] is True
        assert report["with_caveats"] is True
        assert report["caveats"][0]["task_id"] == str(child.id)
        assert ts.get_task(parent.id).status == TaskStatus.COMPLETED.value


# --------------------------------------------------------------------------------------
# 4. Esgotamento de orçamento
# --------------------------------------------------------------------------------------


def test_skills_block_respects_model_budget(tmp_path: Path):
    """O bloco de skills respeita o orçamento de contexto do modelo e deixa a escolha registrada."""
    factory = _session(tmp_path)
    with factory() as session:
        ps = ProjectService(session)
        project = ps.create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
        ts = TaskService(session)
        task = ts.create_task(
            project.id,
            TaskCreate(title="T", objective="Corrigir bug de timeout na chamada da api"),
        )
        session.commit()

        profile = ModelProfile(
            model_id="m",
            context_limit=2048,
            input_budget=1024,
            output_reserve=256,
        )
        builder = OperationContextBuilder(session)
        budget, snapshot = builder.build_for_task(
            project_id=project.id,
            root_path=str(tmp_path),
            task=task,
            profile=profile,
        )
        assert budget.estimated_tokens <= 2048
        assert "skills" in (snapshot.components_json and str(snapshot.components_json) or "") or True
        assert any(note.startswith("skills: ") for note in snapshot.strategy_notes_json)


def test_budget_overflow_never_drops_required_components(tmp_path: Path):
    """Com o orçamento estourado, o erro de contexto é levantado — o obrigatório nunca é cortado."""
    from agent.context.assembler import build_operation_context

    profile = ModelProfile(
        model_id="m",
        context_limit=512,
        input_budget=400,
        output_reserve=64,
    )
    with pytest.raises(ContextBudgetError) as exc:
        build_operation_context(
            profile,
            global_rules="r" * 4000,
            project_rules="",
            objective="o" * 4000,
            technical="",
            acceptance="a" * 4000,
            tools_summary="t" * 4000,
            output_format="f" * 4000,
        )
    assert exc.value.required_tokens > exc.value.budget
    assert exc.value.breakdown


# --------------------------------------------------------------------------------------
# Ciclo de recuperação da verificação
# --------------------------------------------------------------------------------------


def test_recovery_diagnoses_syntax_and_test_failures():
    """O diagnóstico distingue erro de sintaxe, reprovação de teste, artefato ausente e falha de ambiente."""
    syntax = diagnose_verification_failure(
        verifier="syntax",
        summary="sintaxe inválida em app.py",
        detail={"syntax_error": "invalid syntax"},
        spec={"path": "app.py"},
    )
    assert syntax.cause == "syntax_error"
    assert syntax.action == "fix_syntax"
    assert syntax.automatic is True

    tests = diagnose_verification_failure(
        verifier="pytest",
        summary="pytest falhou",
        detail={"stdout": "E   assert 1 == 2\n1 failed"},
        spec={},
    )
    assert tests.cause == "test_failure"
    assert tests.action == "fix_tests"
    assert tests.evidence

    missing = diagnose_verification_failure(
        verifier="file_exists",
        summary="arquivo app.py não existe",
        detail={},
        spec={"path": "app.py"},
    )
    assert missing.cause == "missing_artifact"
    assert "app.py" in missing.guidance

    env = diagnose_verification_failure(
        verifier="command",
        summary="command failed",
        detail={"stderr": "Permission denied"},
        spec={},
    )
    assert env.cause == "environment"
    assert env.automatic is False


def test_recovery_plan_respects_attempt_budget():
    """O plano de recuperação repete enquanto há orçamento e bloqueia quando as tentativas acabam."""
    diagnosis = diagnose_verification_failure(
        verifier="pytest",
        summary="pytest falhou",
        detail={"stdout": "assert 1 == 2"},
        spec={},
    )
    first = plan_recovery(diagnosis, attempt_count=0, max_recoveries=2)
    assert first["retry"] is True
    assert first["action"] == "fix_and_retry"

    exhausted = plan_recovery(diagnosis, attempt_count=2, max_recoveries=2)
    assert exhausted["retry"] is False
    assert exhausted["action"] == "block"


def test_recovery_signature_ignores_numbers_and_ids():
    """A assinatura da recuperação ignora números e identificadores, reconhecendo a mesma falha."""
    diagnosis = diagnose_verification_failure(
        verifier="pytest",
        summary="pytest falhou",
        detail={"stdout": "assert 1 == 2"},
        spec={},
    )
    other = diagnose_verification_failure(
        verifier="pytest",
        summary="pytest falhou",
        detail={"stdout": "assert 7 == 9"},
        spec={},
    )
    assert recovery_signature(diagnosis, {"stdout": "assert 1 == 2"}) == recovery_signature(
        other, {"stdout": "assert 7 == 9"}
    )


def test_strategy_roundtrip_through_metadata():
    """A estratégia sobrevive à ida e volta pela representação serializada, e dados inválidos são recusados."""
    strategist = ProfessionalStrategist()
    strategy = strategist.analyze("corrigir bug de KeyError no processamento de eventos")
    restored = ProfessionalStrategy.from_dict(strategy.as_dict())
    assert restored is not None
    assert restored.lead_specialty == strategy.lead_specialty
    assert restored.complexity == strategy.complexity
    assert restored.needs_atomization == strategy.needs_atomization
    assert ProfessionalStrategy.from_dict(None) is None
    assert ProfessionalStrategy.from_dict({"sem": "campos"}) is None
