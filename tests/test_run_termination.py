"""
Arquivo: tests/test_run_termination.py
Nome: test_run_termination.py
Propósito: verificar que o pai nunca conclui com filho falho e que uma run parada termina explicada, sem laço.
Responsabilidade: camada de testes — comportamento da consolidação do pai, do término da run e da política de replanejamento.
Componentes: filho falho impede a conclusão, cancelamento previsto libera o pai, cancelamento não previsto mantém pendência, run parada explicada, falha de configuração não replanejada, falha replanejada que não bloqueia o pai e política de replanejamento.
Dependências: agent.orchestrator (consolidation, replan, runner), agent.services (project, run, task), agent.persistence (database, models), pytest.
Observações: banco temporário por teste e provedor de modelo mock.

pai nunca conclui com filho falho; run parado termina explicado, sem laço
"""
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
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _tree(session, tmp_path: Path, *, replans: int = 0):
    """Monta uma árvore com uma etapa concluída e outra falhada, com a contagem de replanejamentos desejada."""
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
    """Uma etapa filha que falhou mantém o pai pendente e não é esquecida na consolidação."""
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
    """Com a etapa cancelada por replanejamento, o pai consolida e conclui."""
    _, root, _, broken = _tree(session, tmp_path)
    # Cancelamento previsto: a etapa foi substituída por outra (replanejamento ou correção
    # do plano). O trabalho dela não é pendência e o pai pode seguir.
    broken.status = TaskStatus.CANCELLED.value
    broken.metadata_json = {**(broken.metadata_json or {}), "superseded_by_replan": True}
    root.status = TaskStatus.RUNNING.value
    session.flush()

    report = consolidate_parent(session, root.id)

    assert report["achieved"] is True
    assert TaskService(session).get_task(root.id).status == TaskStatus.COMPLETED.value


def test_cancelled_child_without_replacement_leaves_the_parent_incomplete(session, tmp_path):
    """Etapa cancelada sem previsão é trabalho que não foi feito: o pai não pode concluir como se
    o plano inteiro tivesse sido cumprido."""
    _, root, _, broken = _tree(session, tmp_path)
    broken.status = TaskStatus.CANCELLED.value
    root.status = TaskStatus.RUNNING.value
    session.flush()

    report = consolidate_parent(session, root.id)

    assert report["achieved"] is False
    assert [item["title"] for item in report["pending"]] == ["Rodar testes"]
    assert TaskService(session).get_task(root.id).status != TaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_stalled_run_ends_explained_and_keeps_finished_work(session, tmp_path):
    """Uma run parada termina com o motivo explicado, preserva o trabalho concluído e não repete o laço."""
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
    events = session.query(EventLogModel).filter(EventLogModel.event_type == "run.failed").all()
    assert len(events) == 1 and events[0].payload_json["kind"] == "stalled"

    again = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    assert again["action"] == "run_terminal"


@pytest.mark.asyncio
async def test_configuration_failure_is_not_replanned_and_the_stop_says_why(session, tmp_path):
    """Uma falha de configuração não é replanejada e a parada informa que exige ação externa."""
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
    """Depois do replanejamento, a etapa que falhou é marcada como substituída e não bloqueia mais o pai."""
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
    """O replanejamento só acontece com orçamento disponível e quando o anterior trouxe progresso."""
    _, root, _, broken = _tree(session, tmp_path)
    broken.metadata_json = {"last_failure": {"category": "change_strategy", "cause": "context_budget", "detail": "grande"}}
    assert replan_decision({}, broken, completed=1).replan
    assert not replan_decision({"replan_count": REPLAN_BUDGET}, broken, completed=1).replan
    stale = {"replan_count": 1, "replan_history": [{"completed": 1, "reason": "grande"}]}
    assert replan_decision(stale, broken, completed=1).reason == "o replanejamento anterior não trouxe progresso"
    assert replan_decision(stale, broken, completed=2).replan
