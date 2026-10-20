# tests/test_model_tool_operation.py — a operação do modelo usa ferramentas (regressão real)
"""Regressão da conversa real: com `gpt-oss:20b`, a etapa "Aplicar alterações" recebia o pedido
sem ferramentas e o modelo devolvia `content` vazio. O agente repetia o mesmo pedido três vezes
e parava em estagnação. Aqui o modelo pede a ferramenta, o agente a executa e a etapa conclui
com evidência."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, OperationAttemptModel
from agent.providers.base import ProviderCapabilities, ToolCall
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


class _ToolModel:
    """Modelo que primeiro pede uma leitura e depois escreve o arquivo."""

    name = "ollama"
    last_usage = None

    def __init__(self) -> None:
        self.calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, tool_loop=True)

    async def chat(self, request):
        self.calls += 1
        if self.calls == 1:
            return type(
                "R",
                (),
                {
                    "content": "",
                    "tool_calls": [
                        ToolCall(id="c1", name="read_file", arguments={"path": "notas.txt"})
                    ],
                    "reasoning": "preciso ler o arquivo",
                    "completion_tokens_estimate": 12,
                    "prompt_tokens_estimate": 30,
                },
            )()
        return type(
            "R",
            (),
            {
                "content": "",
                "tool_calls": [
                    ToolCall(
                        id="c2",
                        name="write_file",
                        arguments={"path": "notas.txt", "content": "lista de compras"},
                    )
                ],
                "reasoning": None,
                "completion_tokens_estimate": 20,
                "prompt_tokens_estimate": 40,
            },
        )()


def _leaf(session, tmp_path: Path, monkeypatch, provider):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    leaf = tasks.create_task(
        project.id,
        TaskCreate(
            title="Anotar",
            objective="Crie notas.txt",
            parent_id=root.id,
            metadata={"model_operation": True},
        ),
    )
    leaf.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, leaf


@pytest.mark.asyncio
async def test_model_that_uses_tools_applies_the_change_and_the_step_is_verified(
    session, tmp_path, monkeypatch
):
    provider = _ToolModel()
    run, leaf = _leaf(session, tmp_path, monkeypatch, provider)

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "verified_ok"
    assert (tmp_path / "notas.txt").read_text(encoding="utf-8") == "lista de compras"
    evidence = session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == leaf.id)).one()
    assert evidence.passed is True
    assert provider.calls == 2

    # A evidência guarda as duas pontas: a leitura pedida e a escrita aplicada.
    tools = [
        row.provider
        for row in session.scalars(
            select(OperationAttemptModel).where(OperationAttemptModel.task_id == leaf.id)
        ).all()
        if row.kind == "tool"
    ]
    assert tools == ["read_file", "write_file"]


@pytest.mark.asyncio
async def test_repeated_identical_tool_call_does_not_loop_forever(session, tmp_path, monkeypatch):
    """A mesma chamada com os mesmos argumentos falha de novo: a etapa para para o replanejamento."""

    class _AlwaysMissing:
        name = "mock"
        last_usage = None

        async def chat(self, request):  # pragma: no cover - não deve ser chamado
            raise AssertionError("o modelo não deve ser chamado nesta etapa")

    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Objetivo"))
    root.status = TaskStatus.COMPLETED.value
    leaf = tasks.create_task(
        project.id,
        TaskCreate(
            title="Ler README",
            objective="Leia o README",
            parent_id=root.id,
            metadata={"tool": "read_file", "tool_args": {"path": "README.md"}},
        ),
    )
    leaf.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: _AlwaysMissing())

    orchestrator = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))
    first = await orchestrator.step(run.id)
    session.commit()
    ready = await orchestrator.step(run.id)
    session.commit()
    second = await orchestrator.step(run.id)
    session.commit()

    assert first["action"] == "tool_executed"
    assert ready["action"] == "retry_ready"
    assert second["action"] == "tool_executed"
    assert TaskStatus(leaf.status) == TaskStatus.BLOCKED
    assert "mesma chamada" in (leaf.metadata_json or {}).get("blocked_reason", "")
