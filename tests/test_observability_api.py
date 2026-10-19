# tests/test_observability_api.py — histórico paginado, foto do estado, SSE com reconexão e recuperação
import asyncio
import json
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agent.api import deps
from agent.api.observe_routes import sse_stream
from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.observability import emit, get_bus, observe
from agent.observability.bus import EventBus
from agent.observability.snapshot import run_snapshot
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, ExecutionRunModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    app.dependency_overrides[deps.read_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def _completed_run(tmp_path: Path):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    session = deps.get_session_factory()()
    project = ProjectService(session).create_project(ProjectCreate(name="e2e", root_path=str(workspace)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Objetivo", objective="e2e corrigir calc.py e validar"))
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True})
    )
    session.commit()
    log = asyncio.run(RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).run_until_idle(run.id, max_steps=80))
    session.commit()
    assert log[-1]["action"] == "run_completed"
    return session, run


def _parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        item: dict = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            item[key] = value
        if "data" in item:
            item["data"] = json.loads(item["data"])
            out.append(item)
    return out


def test_history_pages_filters_snapshot_and_stream_of_a_finished_run(client, tmp_path):
    session, run = _completed_run(tmp_path)
    # Fragmentos (não persistidos) consomem números da mesma sequência: o persistido é crescente, com lacunas.
    db_seqs = list(session.scalars(select(EventLogModel.seq).where(EventLogModel.run_id == run.id).order_by(EventLogModel.seq)))
    total = len(db_seqs)

    seen, after = [], 0
    while True:
        page = client.get(f"/runs/{run.id}/events", params={"after": after, "limit": 25}).json()
        seen += page["events"]
        after = page["next_after"]
        if not page["has_more"]:
            break
    assert [e["seq"] for e in seen] == db_seqs
    assert page["last_seq"] == db_seqs[-1]

    only_tasks = client.get(f"/runs/{run.id}/events", params={"types": "task", "limit": 1000}).json()["events"]
    assert only_tasks and all(e["type"].startswith("task.") for e in only_tasks)
    tail = client.get(f"/runs/{run.id}/events", params={"tail": 5}).json()
    assert [e["seq"] for e in tail["events"]] == db_seqs[-5:] and tail["has_more"]
    task_id = only_tasks[-1]["task_id"]
    per_task = client.get(f"/runs/{run.id}/events", params={"task_id": task_id, "limit": 1000}).json()["events"]
    assert per_task and all(e["task_id"] == task_id for e in per_task)

    snap = client.get(f"/runs/{run.id}/observe").json()
    assert snap["header"]["mode"] == "replay" and snap["run"]["status"] == "completed"
    assert snap["last_seq"] == db_seqs[-1] and snap["interrupted"] == []
    by_id = {t["id"]: t for t in snap["tasks"]}
    assert by_id[str(run.root_task_id)]["parent_id"] is None
    assert all(t["parent_id"] in by_id for t in snap["tasks"] if t["parent_id"])
    assert any(t["evidence"] and t["evidence"]["passed"] for t in snap["tasks"])

    # Reexibição: a run acabou, o stream reenvia o histórico e termina com `end`.
    with client.stream("GET", f"/runs/{run.id}/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        items = _parse_sse(resp.read().decode())
    assert items[-1]["event"] == "end"
    ids = [int(i["id"]) for i in items if "id" in i]
    assert ids == db_seqs and total == len(ids)
    # Relidos do SQLite (que perde o fuso), os carimbos ainda saem como UTC explícito.
    def _utc(text: str) -> bool:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).utcoffset() == timedelta(0)

    assert all(_utc(i["data"]["ts"]) for i in items if "id" in i)
    assert _utc(snap["run"]["created_at"]) and all(_utc(t["started_at"]) for t in snap["tasks"] if t["started_at"])

    # Reconexão com Last-Event-ID: só o que veio depois, sem repetir.
    with client.stream("GET", f"/runs/{run.id}/stream", headers={"Last-Event-ID": str(db_seqs[-4])}) as resp:
        again = _parse_sse(resp.read().decode())
    assert [int(i["id"]) for i in again if "id" in i] == db_seqs[-3:]

    # Reconexão automática reaproveita a URL com `after` antigo: vale o cursor mais adiantado.
    stale = f"/runs/{run.id}/stream?after={db_seqs[0]}"
    with client.stream("GET", stale, headers={"Last-Event-ID": str(db_seqs[-2])}) as resp:
        resumed = _parse_sse(resp.read().decode())
    assert [int(i["id"]) for i in resumed if "id" in i] == db_seqs[-1:]

    assert client.get(f"/runs/{uuid.uuid4()}/observe").status_code == 404
    assert client.get(f"/runs/{uuid.uuid4()}/stream").status_code == 404
    session.close()


def _active_run(tmp_path: Path, name: str = "p"):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name=name, root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="o"))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id))
    session.commit()
    return factory, session, project, root, run


class _Req:
    async def is_disconnected(self) -> bool:
        return False


async def _collect(gen, into: list):
    """Como o StreamingResponse: lê até o gerador terminar (ele termina sozinho depois de `end`)."""
    try:
        async for chunk in gen:
            into.extend(_parse_sse(chunk))
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_live_stream_orders_dedupes_separates_runs_and_ends(tmp_path):
    factory, session, project, root, run = _active_run(tmp_path)
    other_root = TaskService(session).create_task(project.id, TaskCreate(title="Outra", objective="o"))
    session.commit()
    other = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=other_root.id))
    session.commit()
    bus = get_bus()
    got: list = []
    reader = asyncio.create_task(_collect(sse_stream(run.id, _Req(), 0, factory=factory, bus=bus, heartbeat=0.05), got))
    await asyncio.sleep(0.1)

    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        emit("agent.started", {"output_id": "o1", "provider": "ollama", "model": "m", "streaming": True}, commit=True)
        emit("agent.output.delta", {"output_id": "o1", "text": "par", "offset": 0})
        emit("agent.output.delta", {"output_id": "o1", "text": "cial", "offset": 3})
        emit("agent.output.completed", {"output_id": "o1", "content": "parcial"}, commit=True)
    with observe(session, run_id=other.id, project_id=project.id):
        emit("run.progress", {"state": {"verified": 9}}, commit=True)
    dup = next(e for e in bus.recent(str(run.id)) if e["type"] == "agent.started")
    bus.publish(dup)
    await asyncio.sleep(0.1)
    with observe(session, run_id=run.id, project_id=project.id):
        session.get(ExecutionRunModel, run.id).status = RunStatus.COMPLETED.value
        emit("run.completed", {}, commit=True)
    await asyncio.wait_for(reader, 2)

    types = [i["data"].get("type") for i in got if i.get("event") is None]
    assert types[0] == "run.started"
    assert types.count("agent.started") == 1
    assert "run.progress" not in types
    assert types[-1] == "run.completed" and got[-1]["event"] == "end"
    assert any(i.get("event") == "live" for i in got)
    deltas = [i for i in got if i["data"].get("type") == "agent.output.delta"]
    assert [d["data"]["data"]["text"] for d in deltas] == ["par", "cial"] and all("id" not in d for d in deltas)
    seqs = [i["data"]["seq"] for i in got if i.get("event") is None]
    assert seqs == sorted(seqs)
    assert bus.subscriber_count(str(run.id)) == 0


@pytest.mark.asyncio
async def test_stream_rotates_after_max_age_so_server_shutdown_never_waits_forever(tmp_path):
    factory, session, project, root, run = _active_run(tmp_path)
    bus = get_bus()
    got: list = []
    gen = sse_stream(run.id, _Req(), 0, factory=factory, bus=bus, heartbeat=0.05, max_age=0.2)
    await asyncio.wait_for(_collect(gen, got), 2)
    assert got[-1]["event"] == "rotate"
    assert got[-1]["data"]["last_seq"] == max(int(i["id"]) for i in got if "id" in i)
    assert bus.subscriber_count(str(run.id)) == 0
    session.close()


@pytest.mark.asyncio
async def test_slow_consumer_resyncs_from_the_database_without_losing_persisted_events(tmp_path):
    factory, session, project, root, run = _active_run(tmp_path)
    bus = EventBus(queue_size=2)
    got: list = []
    gen = sse_stream(run.id, _Req(), 0, factory=factory, bus=bus, heartbeat=0.05)
    first = await gen.__anext__()  # retry
    got.extend(_parse_sse(first))
    # Lê o histórico e o `live`, depois para de consumir enquanto a run produz.
    for _ in range(2):
        got.extend(_parse_sse(await gen.__anext__()))
    import agent.observability.emitter as emitter

    real = emitter.get_bus
    emitter.get_bus = lambda: bus
    try:
        with observe(session, run_id=run.id, project_id=project.id):
            for i in range(8):
                emit("run.progress", {"state": {"i": i}}, commit=True)
            session.get(ExecutionRunModel, run.id).status = RunStatus.COMPLETED.value
            emit("run.completed", {}, commit=True)
    finally:
        emitter.get_bus = real
    await asyncio.sleep(0.05)
    await asyncio.wait_for(_collect(gen, got), 2)
    assert any(i.get("event") == "resync" for i in got)
    persisted = [i["data"]["seq"] for i in got if "id" in i]
    assert persisted == sorted(set(persisted))
    db_seqs = list(session.scalars(select(EventLogModel.seq).where(EventLogModel.run_id == run.id).order_by(EventLogModel.seq)))
    assert persisted == db_seqs
    assert got[-1]["event"] == "end"


def test_interrupted_operations_are_shown_and_never_marked_completed(tmp_path):
    factory, session, project, root, run = _active_run(tmp_path)
    child = TaskService(session).create_task(project.id, TaskCreate(title="Gerar", objective="o", parent_id=root.id))
    session.commit()
    with observe(session, run_id=run.id, project_id=project.id, task_id=child.id):
        tasks = TaskService(session)
        for st in (TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.RUNNING):
            tasks.update_status(child.id, TaskStatusUpdate(status=st))
        emit("agent.started", {"output_id": "o9", "provider": "ollama", "model": "m", "streaming": True}, commit=True)
        emit("agent.output.delta", {"output_id": "o9", "text": "meio", "offset": 0})
        emit("tool.started", {"call_id": "c1", "tool": "run_pytest"}, commit=True)
    live_bus = get_bus()
    assert run_snapshot(session, run.id, bus=live_bus)["live"]["outputs"][0]["text"] == "meio"

    restarted = EventBus()  # processo reiniciado: nada em memória
    snap = run_snapshot(session, run.id, bus=restarted)
    assert snap["header"]["mode"] == "interrupted"
    assert {(op["kind"], op["id"]) for op in snap["interrupted"]} == {("output", "o9"), ("tool", "c1")}
    row = next(t for t in snap["tasks"] if t["id"] == str(child.id))
    assert row["interrupted"] is True and row["status"] == TaskStatus.RUNNING.value

    # Retomada: um passo em andamento torna a run ao vivo de novo; fechada a operação, ela sai da lista.
    restarted.step_started(str(run.id))
    assert run_snapshot(session, run.id, bus=restarted)["header"]["mode"] == "live"
    restarted.step_finished(str(run.id))
    with observe(session, run_id=run.id, project_id=project.id, task_id=child.id):
        emit("agent.output.failed", {"output_id": "o9", "error": "processo reiniciado"}, commit=True)
    left = run_snapshot(session, run.id, bus=restarted)["interrupted"]
    assert [(op["kind"], op["id"]) for op in left] == [("tool", "c1")]
