"""
Arquivo: tests/test_granular_approval.py
Nome: test_granular_approval.py
Propósito: verificar a aprovação granular de operações arriscadas — pedido na hora da execução, pausa, decisão persistida e retomada.
Responsabilidade: camada de testes — comportamento do ApprovalService, do portão no registro de ferramentas, do executor, do orquestrador e das rotas.
Componentes: testes de chave da operação, uso único, negação, fluxo completo pelo orquestrador e pela API.
Dependências: agent.services.approval_service, agent.orchestrator.runner, agent.tools.registry, agent.api.main, fastapi.testclient, pytest.
Observações: banco e workspace temporários; provedor mock; nenhuma rede.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel, ToolApprovalModel
from agent.services.approval_service import ApprovalService, operation_key
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolContext, build_default_registry


def _setup(tmp_path: Path, *, approve_flag: bool = False):
    """Projeto com um arquivo e uma raiz que pede para apagá-lo (operação que exige aprovação)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "lixo.txt").write_text("temporário\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Apagar arquivo temporário",
            objective="Apagar lixo.txt",
            metadata={"tool": "delete_file", "tool_args": {"path": "lixo.txt"}},
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": approve_flag}),
    )
    session.commit()
    return settings, factory, session, workspace, root, run


def test_operation_key_ignores_argument_order():
    """A identidade da operação não depende da ordem dos argumentos, mas muda com o valor."""
    assert operation_key("delete_file", {"a": 1, "b": 2}) == operation_key("delete_file", {"b": 2, "a": 1})
    assert operation_key("delete_file", {"path": "x"}) != operation_key("delete_file", {"path": "y"})
    assert operation_key("delete_file", {"path": "x"}) != operation_key("move_file", {"path": "x"})


@pytest.mark.asyncio
async def test_registry_refuses_without_decision_and_opens_one_request(tmp_path: Path):
    """Sem decisão a ferramenta não roda; repetir a chamada não abre um segundo pedido."""
    settings, factory, session, workspace, root, run = _setup(tmp_path)
    service = ApprovalService(session)
    gate = lambda tool, args, risk, reason: service.check(  # noqa: E731
        tool=tool, args=args, task_id=root.id, run_id=run.id, project_id=root.project_id, risk=risk, reason=reason
    )
    registry = build_default_registry()
    ctx = ToolContext(project_root=str(workspace), approval_gate=gate)
    first = await registry.execute("delete_file", ctx, {"path": "lixo.txt"})
    second = await registry.execute("delete_file", ctx, {"path": "lixo.txt"})
    assert first["error"] == "approval_required" and first["approval_status"] == "pending"
    assert second["approval_id"] == first["approval_id"]
    assert (workspace / "lixo.txt").exists()
    rows = session.scalars(select(ToolApprovalModel)).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_approval_is_single_use_and_bound_to_arguments(tmp_path: Path):
    """A aprovação libera só a mesma operação, uma vez; outro argumento continua exigindo decisão."""
    settings, factory, session, workspace, root, run = _setup(tmp_path)
    (workspace / "outro.txt").write_text("importante\n", encoding="utf-8")
    service = ApprovalService(session)
    gate = lambda tool, args, risk, reason: service.check(  # noqa: E731
        tool=tool, args=args, task_id=root.id, run_id=run.id, project_id=root.project_id, risk=risk, reason=reason
    )
    registry = build_default_registry()
    ctx = ToolContext(project_root=str(workspace), approval_gate=gate)
    pending = await registry.execute("delete_file", ctx, {"path": "lixo.txt"})
    row = session.get(ToolApprovalModel, uuid.UUID(pending["approval_id"]))
    row.status = "approved"
    session.flush()

    other = await registry.execute("delete_file", ctx, {"path": "outro.txt"})
    assert other["error"] == "approval_required"
    assert (workspace / "outro.txt").exists()

    done = await registry.execute("delete_file", ctx, {"path": "lixo.txt"})
    assert done.get("success") is True
    assert not (workspace / "lixo.txt").exists()
    assert row.status == "consumed" and row.consumed_at is not None

    (workspace / "lixo.txt").write_text("de novo\n", encoding="utf-8")
    again = await registry.execute("delete_file", ctx, {"path": "lixo.txt"})
    assert again["error"] == "approval_required"
    assert (workspace / "lixo.txt").exists()


@pytest.mark.asyncio
async def test_orchestrator_pauses_then_resumes_after_approval(tmp_path: Path):
    """Cenário 7: a política é avaliada na execução, o run pausa, a decisão é persistida e a
    execução retoma do mesmo ponto só depois de aprovada."""
    settings, factory, session, workspace, root, run = _setup(tmp_path)
    orch = RunOrchestrator(session, settings)
    log = await orch.run_until_idle(run.id, max_steps=20)
    session.commit()

    assert log[-1]["action"] == "awaiting_approval"
    assert (workspace / "lixo.txt").exists(), "a operação não pode rodar sem aprovação"
    task = session.get(TaskModel, root.id)
    assert task.status == TaskStatus.BLOCKED.value
    approval_id = task.metadata_json["awaiting_approval"]
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.PAUSED.value
    attempts_before = len([x for x in log if x.get("action") == "tool_executed"])
    assert attempts_before == 0, "a recusa por falta de aprovação não é repetida às cegas"

    # Mais passos com o run pausado não executam nada.
    assert (await orch.step(run.id))["action"] == "run_paused"
    assert (workspace / "lixo.txt").exists()

    ApprovalService(session).decide(uuid.UUID(approval_id), approve=True, note="ok")
    session.commit()
    assert session.get(ExecutionRunModel, run.id).status == RunStatus.ACTIVE.value

    log2 = await RunOrchestrator(factory(), settings).run_until_idle(run.id, max_steps=4)
    assert not (workspace / "lixo.txt").exists()
    # A etapa retoma do ponto em que parou e conclui; sem verificador para "apagar", a
    # conclusão fica registrada como não verificada (e a aceitação global continua exigindo prova).
    finished = [x for x in log2 if x.get("task_id") == str(root.id) and x.get("action") == "completed_without_verification"]
    assert finished, log2
    check = factory()
    row = check.get(ToolApprovalModel, uuid.UUID(approval_id))
    assert row.status == "consumed" and row.decision_note == "ok"
    kinds = {e.event_type for e in check.scalars(select(EventLogModel).where(EventLogModel.run_id == run.id))}
    assert {"approval.requested", "approval.decided", "run.paused", "run.resumed"} <= kinds


@pytest.mark.asyncio
async def test_denied_operation_never_runs(tmp_path: Path):
    """Negada, a operação não roda; a etapa fica bloqueada com o motivo e o run sai da espera."""
    settings, factory, session, workspace, root, run = _setup(tmp_path)
    orch = RunOrchestrator(session, settings)
    await orch.run_until_idle(run.id, max_steps=20)
    approval_id = session.get(TaskModel, root.id).metadata_json["awaiting_approval"]
    ApprovalService(session).decide(uuid.UUID(approval_id), approve=False, note="não")
    session.commit()
    with pytest.raises(ValueError):
        ApprovalService(session).decide(uuid.UUID(approval_id), approve=True)

    await RunOrchestrator(factory(), settings).run_until_idle(run.id, max_steps=20)
    assert (workspace / "lixo.txt").exists()
    check = factory()
    task = check.get(TaskModel, root.id)
    assert task.status != TaskStatus.COMPLETED.value
    assert task.metadata_json.get("approval_denied", {}).get("tool") == "delete_file"
    assert "awaiting_approval" not in task.metadata_json


@pytest.mark.asyncio
async def test_run_flag_still_grants_broad_approval(tmp_path: Path):
    """A aprovação ampla explícita do run continua valendo (compatibilidade)."""
    settings, factory, session, workspace, root, run = _setup(tmp_path, approve_flag=True)
    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=20)
    assert not (workspace / "lixo.txt").exists()
    assert not any(x.get("action") == "awaiting_approval" for x in log)
    assert session.scalars(select(ToolApprovalModel)).all() == []


def test_approval_routes(tmp_path: Path, monkeypatch):
    """As rotas listam os pedidos do run e aplicam a decisão (404 e 409 nos erros)."""
    import asyncio

    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.main import app

    settings, factory, session, workspace, root, run = _setup(tmp_path)
    asyncio.run(RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=20))
    session.commit()

    def _db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[deps.db_session] = _db
    try:
        client = TestClient(app)
        listed = client.get(f"/runs/{run.id}/approvals").json()
        assert len(listed) == 1 and listed[0]["status"] == "pending" and listed[0]["tool"] == "delete_file"
        assert client.post(f"/approvals/{uuid.uuid4()}/approve").status_code == 404
        decided = client.post(f"/approvals/{listed[0]['id']}/approve", json={"note": "pode"})
        assert decided.status_code == 200
        assert decided.json()["status"] == "approved" and decided.json()["run_status"] == RunStatus.ACTIVE.value
        assert client.post(f"/approvals/{listed[0]['id']}/deny").status_code == 409
        assert client.get(f"/runs/{uuid.uuid4()}/approvals").status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resume_after_crash_does_not_repeat_unsafe_operation_blindly(tmp_path: Path):
    """Cenário 3 (efeito externo): o processo caiu durante uma operação não repetível — o
    marcador `inflight_operation` ficou gravado. A retomada não repete a operação às cegas:
    pede confirmação; confirmada, roda uma vez e o marcador some."""

    settings, factory, session, workspace, root, run = _setup(tmp_path, approve_flag=True)
    orch = RunOrchestrator(session, settings)
    # Avança até a etapa estar pronta para rodar (sem executá-la).
    for _ in range(6):
        if session.get(TaskModel, root.id).status == TaskStatus.READY.value:
            break
        await orch.step(run.id)
    task = session.get(TaskModel, root.id)
    assert task.status == TaskStatus.READY.value
    from agent.services.approval_service import operation_key

    # Simula a queda: o marcador foi gravado antes do efeito e a etapa ficou em RUNNING.
    task.metadata_json = {
        **task.metadata_json,
        "inflight_operation": {"tool": "delete_file", "key": operation_key("delete_file", {"path": "lixo.txt"})},
    }
    TaskService(session).update_status(task.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
    session.commit()
    session.close()

    restarted = factory()
    out = await RunOrchestrator(restarted, settings).step(run.id)
    restarted.commit()
    assert out["action"] == "awaiting_approval", out
    assert (workspace / "lixo.txt").exists(), "a operação não foi repetida sem confirmação"
    row = restarted.get(ToolApprovalModel, uuid.UUID(out["approval_id"]))
    assert "interrompida" in row.reason

    ApprovalService(restarted).decide(row.id, approve=True)
    restarted.commit()
    await RunOrchestrator(factory(), settings).run_until_idle(run.id, max_steps=4)
    check = factory()
    assert not (workspace / "lixo.txt").exists()
    assert "inflight_operation" not in (check.get(TaskModel, root.id).metadata_json or {})
    assert check.get(ToolApprovalModel, row.id).status == "consumed"
