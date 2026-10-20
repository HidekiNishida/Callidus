"""
Arquivo: tests/test_proportional_verification.py
Nome: test_proportional_verification.py
Propósito: verificar que a escrita gera evidência e que uma etapa sem ação não conclui à toa.
Responsabilidade: camada de testes — comportamento da verificação proporcional ao que a etapa fez.
Componentes: verificação implícita de conteúdo após escrita, execução da etapa que não tinha ação declarada.
Dependências: agent.orchestrator.runner.RunOrchestrator, agent.persistence (database, models), agent.services (project, run, task), pytest.
Observações: banco e workspace temporários; o provedor de modelo é substituído por um falso que escreve o arquivo.

escrita gera evidência; etapa sem ação não conclui à toa
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
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


class _Writer:
    """Provedor falso que devolve a operação de arquivo a ser gravada."""
    name = "mock"
    last_usage = None

    def __init__(self) -> None:
        """Zera o contador de chamadas ao modelo."""
        self.calls = 0

    async def chat(self, request):
        """Provedor falso: devolve o conteúdo a ser gravado e conta as chamadas."""
        self.calls += 1

        class _R:
            """Resposta falsa com a operação de arquivo em JSON."""
            content = '{"path": "notas.txt", "content": "lista de compras"}'

        return _R()


def _leaf(session, tmp_path: Path, metadata: dict, monkeypatch):
    """Prepara uma tarefa folha em execução com o provedor falso já conectado."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    leaf = tasks.create_task(
        project.id,
        TaskCreate(title="Anotar", objective="Crie notas.txt", parent_id=root.id, metadata=metadata),
    )
    leaf.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    provider = _Writer()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, leaf, provider


@pytest.mark.asyncio
async def test_write_without_declared_check_gets_an_implicit_content_check(session, tmp_path, monkeypatch):
    """Uma escrita sem verificação declarada recebe uma checagem implícita de conteúdo, com evidência aprovada."""
    run, leaf, _ = _leaf(session, tmp_path, {"model_operation": True}, monkeypatch)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "verified_ok"
    evidence = session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == leaf.id)).one()
    assert evidence.verifier == "file_contains"
    assert evidence.passed is True
    assert evidence.attempt_id is not None


@pytest.mark.asyncio
async def test_step_without_action_runs_instead_of_completing_silently(session, tmp_path, monkeypatch):
    """Uma etapa sem ação declarada executa o trabalho em vez de pular direto para a verificação."""
    run, leaf, provider = _leaf(session, tmp_path, {"atomic": True}, monkeypatch)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] != "skipped_to_verify"
    assert provider.calls == 1
    assert (tmp_path / "notas.txt").read_text(encoding="utf-8") == "lista de compras"
    assert TaskService(session).get_task(leaf.id).metadata_json["model_operation"] is True
