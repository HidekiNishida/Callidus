"""
Arquivo: tests/test_stagnation_limits.py
Nome: test_stagnation_limits.py
Propósito: verificar a detecção de estagnação por assinatura de erro, a mudança de estratégia e os limites com pausa e retomada.
Responsabilidade: camada de testes — comportamento da assinatura de erro, do limite de estagnação, da pausa da run e da retomada.
Componentes: assinatura de erro insensível a números, estratégia diferente reinicia a contagem, estagnação registrada com diagnóstico, nova tentativa com estratégia diferente, replanejamento repetido sem progresso, limites vindos das configurações, pausa com estado recuperável e retomada pela rota.
Dependências: agent.orchestrator (stagnation, replan, runner), agent.services (project, run, task), agent.persistence (database, models), fastapi.testclient, pytest.
Observações: banco temporário por teste; o modelo é substituído por um provedor falso que devolve respostas programadas.

mesmo erro por assinatura, estratégia diferente, limites com pausa e retomada
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.failures import Failure, FailureCategory, FailureCause
from agent.orchestrator.replan import replan_decision
from agent.orchestrator.runner import RunOrchestrator
from agent.orchestrator.stagnation import error_signature, limits_for, normalize_error, repeated_failures
from agent.persistence.models import EventLogModel, ExecutionRunModel
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
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


class _Scripted:
    """Provedor falso que devolve respostas programadas e registra os prompts recebidos."""
    name = "mock"
    last_usage = None

    def __init__(self, replies: list[str]) -> None:
        """Guarda as respostas programadas e prepara o registro de prompts."""
        self.replies = replies
        self.prompts: list[str] = []

    async def chat(self, request):
        """Provedor falso: registra os prompts recebidos e devolve a resposta programada."""
        self.prompts.append("\n".join(m.content for m in request.messages))
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]

        class _R:
            """Resposta falsa que carrega a resposta programada."""
            content = reply

        return _R()


def _change(session, tmp_path: Path, provider, monkeypatch):
    """Prepara uma etapa de alteração de arquivo em execução, com o provedor falso já conectado."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Alterar arquivo",
            objective="Escreva a.txt com ok",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, change


def _failure(detail: str, strategy: str = "s1") -> dict:
    """Monta uma falha com assinatura e estratégia, como o orquestrador as registra."""
    data = Failure(FailureCategory.RECOVERABLE, FailureCause.VERIFICATION_FAILED, detail).as_dict()
    return {**data, "signature": error_signature(data), "strategy": strategy}


def _events(session, run_id, kind):
    """Devolve os eventos de um tipo gravados para a run."""
    return session.scalars(select(EventLogModel).where(EventLogModel.run_id == run_id, EventLogModel.event_type == kind)).all()


def test_same_error_with_different_numbers_has_the_same_signature():
    """Erros que só diferem em números e identificadores têm a mesma assinatura e contam como repetição."""
    assert normalize_error("pytest falhou em 0.31s (3 failed) id 1f0e2d3c-aaaa-bbbb-cccc-123456789abc") == normalize_error(
        "Pytest falhou em 12.9s (7 failed) id 99999999-aaaa-bbbb-cccc-123456789abc"
    )
    runs = [_failure("assert 1 == 2 em 0.1s"), _failure("assert 3 == 4 em 0.7s"), _failure("assert 5 == 6 em 1.2s")]
    assert repeated_failures(runs) == 3
    assert repeated_failures([*runs, _failure("ModuleNotFoundError: calc")]) == 1


def test_a_materially_different_strategy_restarts_the_count():
    """Quando a estratégia muda de verdade, a contagem de repetições recomeça."""
    runs = [_failure("assert 1 == 2", "s1"), _failure("assert 1 == 2", "s1"), _failure("assert 1 == 2", "s2")]
    assert repeated_failures(runs) == 1


@pytest.mark.asyncio
async def test_repeated_error_without_strategy_change_stops_and_records_diagnosis(session, tmp_path, monkeypatch):
    """O mesmo erro sem mudança de estratégia para a execução, registra o diagnóstico e emite o evento de estagnação."""
    provider = _Scripted(["Vou escrever o arquivo 1.", "Vou escrever o arquivo 2.", "Vou escrever o arquivo 3."])
    run, change = _change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    log = [await orch.step(run.id) for _ in range(5)]

    assert [x["action"] for x in log] == [
        "model_operation_invalid",
        "retry_ready",
        "model_operation_invalid",
        "retry_ready",
        "stagnation_replan",
    ]
    task = TaskService(session).get_task(change.id)
    assert task.status == TaskStatus.BLOCKED.value
    record = task.metadata_json["stagnation"]
    assert record["previous_status"] == TaskStatus.RETRY_PENDING.value and record["count"] == 3
    assert record["kind"] == "implementação" and record["automatic"] is True
    assert "mesmo erro" in record["probable_cause"] and record["next_action"].startswith("replanejar")
    assert task.metadata_json["last_failure"]["cause"] == "stagnation"
    [event] = _events(session, run.id, "run.stagnation")
    assert event.payload_json["signature"] == record["signature"]
    assert len(provider.prompts) == 3


@pytest.mark.asyncio
async def test_new_attempt_with_a_different_strategy_is_not_stagnation(session, tmp_path, monkeypatch):
    """Uma tentativa com estratégia diferente não conta como estagnação."""
    provider = _Scripted(["Vou escrever."])
    run, change = _change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))
    for _ in range(4):
        await orch.step(run.id)
    task = TaskService(session).get_task(change.id)
    task.metadata_json = {**task.metadata_json, "strategy": "gravar com write_file em vez de resposta livre"}
    session.commit()

    out = await orch.step(run.id)

    assert out["action"] == "model_operation_invalid"
    assert TaskService(session).get_task(change.id).status == TaskStatus.RETRY_PENDING.value
    assert not _events(session, run.id, "run.stagnation")


def test_repeated_replan_without_fewer_pending_is_refused_even_if_text_differs(session, tmp_path, monkeypatch):
    """Replanejar de novo sem reduzir o pendente é recusado, mesmo com texto de erro diferente."""
    run, change = _change(session, tmp_path, _Scripted(["x"]), monkeypatch)
    task = TaskService(session).get_task(change.id)
    task.status = TaskStatus.BLOCKED.value
    task.metadata_json = {**task.metadata_json, "blocked_reason": "pytest falhou em 0.52s"}
    history = {"replan_count": 1, "replan_history": [{"completed": 0, "reason": "pytest falhou em 0.31s"}]}

    assert replan_decision(history, task, completed=0).replan is False
    assert replan_decision(history, task, completed=1).replan is True
    task.metadata_json = {**task.metadata_json, "blocked_reason": "ModuleNotFoundError: calc"}
    assert replan_decision(history, task, completed=0).replan is True


def test_limits_come_from_settings_and_run_config():
    """Os limites vêm das configurações e podem ser ajustados pela configuração da run."""
    limits = limits_for(Settings(max_model_calls_per_run=7), {"limits": {"tool_calls": 2, "seconds": "x"}})
    assert limits["model_calls"] == 7 and limits["tool_calls"] == 2
    assert limits["seconds"] == Settings().max_run_seconds


@pytest.mark.asyncio
async def test_limit_pauses_with_recoverable_state_and_resume_continues(session, tmp_path, monkeypatch):
    """O limite de chamadas pausa a run com estado recuperável, e a retomada continua de onde parou."""
    provider = _Scripted(["Vou escrever."])
    run, change = _change(session, tmp_path, provider, monkeypatch)
    run = session.get(ExecutionRunModel, run.id)
    run.config_json = {**run.config_json, "limits": {"model_calls": 1}}
    session.commit()
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    assert (await orch.step(run.id))["action"] == "model_operation_invalid"
    paused = await orch.step(run.id)

    assert paused["action"] == "run_paused" and "chamadas ao modelo (1 de 1)" in paused["reason"]
    assert "resume" in paused["next_action"]
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.PAUSED.value
    ts = TaskService(session)
    assert ts.get_task(change.id).status == TaskStatus.RETRY_PENDING.value
    root = ts.get_task(run.root_task_id)
    pause = root.metadata_json["pause"]
    assert pause["limit"] == "model_calls" and pause["pending"][0]["title"] == "Alterar arquivo"
    assert "Próxima ação" in root.consolidated_result_json["final_answer"]
    assert _events(session, run.id, "run.paused")

    again = await orch.step(run.id)
    assert again["action"] == "run_paused" and len(provider.prompts) == 1

    RunService(session).resume_run(run.id)
    session.commit()
    with pytest.raises(ValueError):
        RunService(session).resume_run(run.id)

    assert session.get(ExecutionRunModel, run.id).status == RunStatus.ACTIVE.value
    root = ts.get_task(run.root_task_id)
    assert "pause" not in root.metadata_json and root.metadata_json["pauses"][0]["limit"] == "model_calls"
    assert "paused" not in (root.consolidated_result_json or {})
    assert (await orch.step(run.id))["action"] == "retry_ready"
    assert (await orch.step(run.id))["action"] == "model_operation_invalid"
    assert len(provider.prompts) == 2
    assert (await orch.step(run.id))["action"] == "run_paused"


def test_resume_route_reactivates_only_paused_runs(session, tmp_path, monkeypatch):
    """A rota de retomada reativa apenas runs pausadas e devolve 409 quando a run já está ativa."""
    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.main import app

    run, change = _change(session, tmp_path, _Scripted(["x"]), monkeypatch)
    task = TaskService(session).get_task(change.id)
    task.status = TaskStatus.BLOCKED.value
    RunService(session).pause_run(run.id)
    session.commit()
    app.dependency_overrides[deps.db_session] = lambda: session
    try:
        client = TestClient(app)
        first = client.post(f"/runs/{run.id}/resume", params={"retry_blocked": True})
        second = client.post(f"/runs/{run.id}/resume")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200 and first.json()["status"] == RunStatus.ACTIVE.value
    assert second.status_code == 409
    assert TaskService(session).get_task(change.id).status == TaskStatus.PLANNING.value
    [event] = _events(session, run.id, "run.resumed")
    assert event.payload_json["retried"] == [str(change.id)]
