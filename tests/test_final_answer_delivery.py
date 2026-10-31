"""
Arquivo: tests/test_final_answer_delivery.py
Nome: test_final_answer_delivery.py
Propósito: verificar que a resposta final escrita chega à raiz e que um plano atrasado não é aplicado.
Responsabilidade: camada de testes — publicação da resposta, run cancelado e descarte de decomposição obsoleta.
Componentes: resposta copiada com irmão pendente, run cancelado que publica o texto já escrito, plano que chega depois do cancelamento.
Dependências: agent.orchestrator.runner, agent.orchestrator.consolidation, agent.services e pytest.
Observações: banco temporário por teste; o provedor de modelo é substituído e não há chamada de rede.
"""

import asyncio
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import children_of, remember_final_answer
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ExecutionRunModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Sessão sobre um banco temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    engine = init_db(settings=settings)
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _project(session, tmp_path: Path):
    """Projeto e serviço de tarefas no diretório temporário."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    return project, TaskService(session), Settings(data_dir=tmp_path / "data", enable_background_worker=False)


def test_remember_final_answer_copies_text_without_completing_the_parent(session, tmp_path: Path):
    """O markdown da etapa final vai para a raiz mesmo com um irmão ainda pendente.

    A raiz não muda de estado: a resposta fica visível sem declarar o plano cumprido.
    """
    project, tasks, _settings = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Pedido", objective="Explicar o resultado"))
    root.status = TaskStatus.PLANNING.value
    answer = tasks.create_task(
        project.id,
        TaskCreate(
            title="Responder",
            objective="Escrever a resposta",
            parent_id=root.id,
            metadata={"final_answer": True, "model_operation": True},
        ),
    )
    answer.status = TaskStatus.COMPLETED.value
    answer.consolidated_result_json = {"final_answer": True, "markdown": "O jogo está na pasta."}
    pending = tasks.create_task(
        project.id,
        TaskCreate(title="Etapa sobrando", objective="não executar", parent_id=root.id, metadata={"tool": "list_dir"}),
    )
    pending.status = TaskStatus.PENDING.value
    session.commit()

    assert remember_final_answer(session, answer) is True
    session.commit()

    stored = tasks.get_task(root.id)
    assert stored.status == TaskStatus.PLANNING.value
    assert stored.consolidated_result_json["final_answer"] == "O jogo está na pasta."
    assert tasks.get_task(pending.id).status == TaskStatus.PENDING.value


@pytest.mark.asyncio
async def test_cancelled_run_surfaces_the_written_answer_and_stays_cancelled(session, tmp_path: Path):
    """Um passo em run cancelado publica a resposta já escrita e não conclui a raiz."""
    project, tasks, settings = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Pedido", objective="Explicar o resultado"))
    root.status = TaskStatus.PLANNING.value
    answer = tasks.create_task(
        project.id,
        TaskCreate(
            title="Responder",
            objective="Escrever a resposta",
            parent_id=root.id,
            metadata={"final_answer": True, "model_operation": True},
        ),
    )
    answer.status = TaskStatus.COMPLETED.value
    answer.consolidated_result_json = {
        "final_answer": True,
        "markdown": "O jogo está na pasta.",
        "sources": ["index.html"],
    }
    pending = tasks.create_task(
        project.id,
        TaskCreate(title="Etapa sobrando", objective="não executar", parent_id=root.id, metadata={"tool": "list_dir"}),
    )
    pending.status = TaskStatus.PENDING.value
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    run.status = RunStatus.CANCELLED.value
    session.commit()

    out = await RunOrchestrator(session, settings).step(run.id)
    session.commit()

    assert out["action"] == "run_terminal"
    assert out["status"] == RunStatus.CANCELLED.value
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.CANCELLED.value
    stored = tasks.get_task(root.id)
    assert stored.status == TaskStatus.PLANNING.value
    assert stored.consolidated_result_json["final_answer"] == "O jogo está na pasta."
    assert stored.consolidated_result_json["sources"] == ["index.html"]
    assert tasks.get_task(pending.id).status == TaskStatus.PENDING.value


@pytest.mark.asyncio
async def test_decomposition_that_returns_after_cancel_is_not_applied(session, tmp_path: Path, monkeypatch):
    """O plano que volta depois do cancelamento não cria etapas novas."""
    project, tasks, settings = _project(session, tmp_path)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Pedido", objective="Crie a pasta do jogo e os arquivos da interface web"),
    )
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "autonomous": True})
    )
    session.commit()
    orchestrator = RunOrchestrator(session, settings)
    opened = await orchestrator.step(run.id)
    assert opened["action"] == "started_planning"

    async def late_plan(**_kwargs):
        run.status = RunStatus.CANCELLED.value
        tasks.create_task(
            project.id,
            TaskCreate(title="Já no plano", objective="etapa que já existia", parent_id=root.id),
        )
        session.commit()
        return (
            DecompositionResult(subtasks=[SubTaskSpec(title="Não deve nascer", objective="plano atrasado")]),
            "late",
        )

    monkeypatch.setattr("agent.orchestrator.runner.resolve_decomposition_plan", late_plan)
    out = await orchestrator.step(run.id)
    session.commit()

    assert out["action"] == "run_terminal"
    assert out.get("discarded") == "decomposition"
    titles = [child.title for child in children_of(session, root.id)]
    assert "Já no plano" in titles
    assert "Não deve nascer" not in titles
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_overlapping_steps_apply_the_plan_once(session, tmp_path: Path, monkeypatch):
    """Dois passos simultâneos no mesmo run esperam um ao outro e o plano entra uma vez."""
    project, tasks, settings = _project(session, tmp_path)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Pedido", objective="Crie a pasta do jogo e os arquivos da interface web"),
    )
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()
    orchestrator = RunOrchestrator(session, settings)
    await orchestrator.step(run.id)

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_plan(**_kwargs):
        started.set()
        await release.wait()
        return (
            DecompositionResult(subtasks=[SubTaskSpec(title="Do plano lento", objective="única etapa")]),
            "slow",
        )

    monkeypatch.setattr("agent.orchestrator.runner.resolve_decomposition_plan", slow_plan)
    holder = asyncio.create_task(orchestrator.step(run.id))
    await asyncio.wait_for(started.wait(), timeout=5)
    other = asyncio.create_task(orchestrator.step(run.id))
    await asyncio.sleep(0.05)
    assert holder.done() is False
    assert other.done() is False
    release.set()
    first = await holder
    await other
    session.commit()

    assert first["action"] == "decomposed"
    titles = [child.title for child in children_of(session, root.id)]
    assert titles.count("Do plano lento") == 1
