"""
Arquivo: tests/test_truncated_output.py
Nome: test_truncated_output.py
Propósito: verificar que uma resposta vazia por corte de tokens não trava o run.
Responsabilidade: camada de testes — comportamento da classificação de saída truncada e do alargamento do orçamento de saída.
Componentes: classificação de corte no limite, saída vazia dentro do limite, ampliação do orçamento na tentativa seguinte e ampliação por estagnação sem pausar a run.
Dependências: agent.orchestrator.runner.RunOrchestrator, agent.domain.failures, agent.services (project, run, task), agent.persistence.database, pytest.
Observações: banco temporário por teste; o modelo é substituído por um falso que consome todo o orçamento de saída recebido.

resposta vazia por corte de tokens não trava o run
"""
from __future__ import annotations
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.failures import Failure, FailureCategory, FailureCause, classify_model_output
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
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


class _Truncating:
    """Modelo que gasta todo o orçamento de saída e devolve nada (típico de modelo que pensa)."""

    name = "mock"
    last_usage = None

    def __init__(self, budget: int = 1024, replies: list[str] | None = None) -> None:
        """Guarda o orçamento de saída e as respostas programadas do modelo falso."""
        self.budget = budget
        self.replies = replies or []
        self.requests: list[tuple[int | None, int]] = []

    async def chat(self, request):
        """Modelo falso: consome todo o orçamento de saída recebido e devolve a resposta programada."""
        num_predict = request.profile.generation.get("num_predict")
        reserve = request.profile.output_reserve
        self.requests.append((num_predict, reserve))
        reply = self.replies[len(self.requests) - 1] if len(self.replies) >= len(self.requests) else ""
        # O provedor consome exatamente o orçamento que recebeu.
        used = int(num_predict or reserve)

        class _R:
            """Resposta falsa que informa o consumo de todo o orçamento de saída."""
            content = reply
            completion_tokens_estimate = used
            prompt_tokens_estimate = 10
            tool_calls = None
            finish_reason = "length"
            model = "mock"

        return _R()


def _change(session, tmp_path: Path, provider, monkeypatch):
    """Prepara uma etapa de alteração de arquivo em execução, com o modelo falso já conectado."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Aplicar alterações",
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


def test_resposta_vazia_no_limite_e_classificada_como_corte():
    """Uma resposta vazia com o orçamento esgotado é classificada como corte de saída."""
    failure = classify_model_output("", "resposta vazia", None, budget=1024, used_tokens=1024)
    assert failure is not None
    assert failure.cause == FailureCause.TRUNCATED_OUTPUT
    assert failure.category == FailureCategory.CHANGE_STRATEGY
    assert "orçamento" in failure.detail


def test_resposta_vazia_sem_atingir_o_limite_continua_sendo_saida_invalida():
    """Uma resposta vazia que não atingiu o limite continua classificada como saída inválida."""
    failure = classify_model_output("", "resposta vazia", None, budget=1024, used_tokens=12)
    assert failure is not None
    assert failure.cause == FailureCause.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_tentativa_seguinte_amplia_o_orcamento_de_saida(session, tmp_path, monkeypatch):
    """A tentativa seguinte recebe um orçamento de saída maior que o da anterior."""
    provider = _Truncating(budget=1024)
    run, change = _change(session, tmp_path, provider, monkeypatch)
    orchestrator = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    first = await orchestrator.step(run.id)
    session.commit()

    assert first["failure"]["cause"] == FailureCause.TRUNCATED_OUTPUT.value
    assert change.status == TaskStatus.RETRY_PENDING.value

    # O ciclo passa por RETRY_PENDING → READY → RUNNING; na chamada seguinte o orçamento cresce.
    for _ in range(3):
        await orchestrator.step(run.id)
        session.commit()

    assert len(provider.requests) >= 2
    assert provider.requests[0][1] < provider.requests[1][1], "o orçamento deveria crescer"
    assert provider.requests[1][1] >= 2048


@pytest.mark.asyncio
async def test_estagnacao_por_corte_amplia_o_orcamento_sem_pausar(session, tmp_path, monkeypatch):
    """A estagnação por corte amplia o orçamento de saída e a run segue sem pausar."""
    provider = _Truncating(budget=1024)
    run, change = _change(session, tmp_path, provider, monkeypatch)
    orchestrator = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    # O limite de tentativas por estratégia (3) dispara a regra de estagnação: em vez de
    # pausar, o agente amplia o orçamento e segue sozinho.
    out = {}
    for _ in range(8):
        out = await orchestrator.step(run.id)
        session.commit()
        if out.get("action") == "budget_widened":
            break

    assert out["action"] == "budget_widened", out
    assert out["output_budget"] >= 2048
    assert run.status != "paused", "o run não pode pausar por corte de saída"
    assert change.metadata_json["output_budget"] >= 2048
