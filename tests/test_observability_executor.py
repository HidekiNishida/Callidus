"""
Arquivo: tests/test_observability_executor.py
Nome: test_observability_executor.py
Propósito: verificar que o executor real emite os fatos da execução na ordem e ligados à tarefa correspondente.
Responsabilidade: camada de testes — comportamento emissor do executor durante uma execução de ponta a ponta.
Componentes: ordem e tipagem dos eventos, vínculo com tarefa e pai, diff de arquivo alterado, saída de teste em memória, coerência entre persistido e entregue.
Dependências: agent.orchestrator.runner, agent.observability, agent.persistence (database, models), agent.services, pytest.
Observações: banco e workspace temporários; o provedor de modelo é o mock configurado na run.

o executor real emite os fatos da execução, na ordem, ligados à tarefa
"""
import asyncio
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.observability import get_bus
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, TaskModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


async def _run_calc_fix(tmp_path: Path):
    """Executa uma run de correção de calc.py e devolve a sessão, as tarefas, o log e os eventos persistidos e entregues."""
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="e2e", root_path=str(workspace)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Objetivo E2E", objective="e2e corrigir calc.py e validar")
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=80)
    session.commit()
    await asyncio.sleep(0.05)
    delivered = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    bus.unsubscribe(sub)
    rows = list(
        session.scalars(select(EventLogModel).where(EventLogModel.run_id == run.id).order_by(EventLogModel.seq))
    )
    return session, root, run, log, rows, delivered


@pytest.mark.asyncio
async def test_executor_emits_ordered_typed_facts_for_a_real_run(tmp_path: Path):
    """O executor emite fatos ordenados e tipados da execução, com seq único, diff real do arquivo e nenhum evento duplicado."""
    session, root, run, log, rows, delivered = await _run_calc_fix(tmp_path)
    assert log[-1]["action"] == "run_completed"
    types = [r.event_type for r in rows]

    seqs = [r.seq for r in rows]
    assert None not in seqs and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert types[0] == "run.started"
    assert "run.completed" in types and types.index("run.completed") > types.index("plan.updated")
    for expected in ("plan.started", "plan.updated", "task.created", "task.started", "task.completed",
                     "tool.started", "tool.completed", "test.started", "verification.started",
                     "verification.passed", "run.progress"):
        assert expected in types, expected
    assert "task.status_changed" not in types

    # Tarefa e pai vêm do estado real.
    tasks = {t.id: t for t in session.scalars(select(TaskModel))}
    for r in rows:
        if r.task_id is not None and r.task_id in tasks:
            assert r.parent_task_id == tasks[r.task_id].parent_id

    # Arquivo alterado com diff real do disco, ligado à chamada da ferramenta.
    changed = [r for r in rows if r.event_type in ("file.changed", "file.created") and r.payload_json["path"] == "calc.py"]
    assert changed and "+    return a + b" in changed[-1].payload_json["diff"]
    tool_calls = {r.payload_json["call_id"] for r in rows if r.event_type == "tool.started"}
    assert changed[-1].payload_json["call_id"] in tool_calls

    # Testes: início, saída progressiva (só em memória) e fim com contagem.
    test_done = [r for r in rows if r.event_type in ("test.completed", "test.failed")]
    assert test_done and test_done[-1].event_type == "test.completed"
    assert test_done[-1].payload_json["counts"].get("passed", 0) >= 1
    assert "test.output" not in types
    outputs = [e for e in delivered if e["type"] == "test.output"]
    assert outputs and "passed" in "".join(e["data"]["text"] for e in outputs)

    # Entregues em ordem de commit, sem duplicar, com o mesmo seq gravado.
    persisted = [e for e in delivered if e.get("persisted")]
    assert [e["seq"] for e in persisted] == sorted(e["seq"] for e in persisted)
    assert len({e["id"] for e in persisted}) == len(persisted)
    by_id = {str(r.id): r.seq for r in rows}
    assert all(by_id[e["id"]] == e["seq"] for e in persisted)

    # Nenhuma tarefa concluída sem o fato correspondente.
    completed = {r.task_id for r in rows if r.event_type == "task.completed"}
    for t in tasks.values():
        if t.status == TaskStatus.COMPLETED.value:
            assert t.id in completed
    session.close()
