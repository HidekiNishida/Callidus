# tests/test_observability_events.py — contrato, sequência, sanitização e publicação só após commit
import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.domain.enums import TaskStatus
from agent.observability import emit, get_bus, observe
from agent.observability.bus import RESYNC, EventBus
from agent.observability.contracts import InvalidEventPayload, UnknownEventType
from agent.observability.sanitize import REDACTED, is_sensitive_path, sanitize
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


def _setup(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="o"))
    session.commit()
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id))
    session.commit()
    return factory, session, project, root, run


def _events(session, run_id):
    return list(
        session.scalars(select(EventLogModel).where(EventLogModel.run_id == run_id).order_by(EventLogModel.seq))
    )


def test_emit_outside_a_run_records_nothing(tmp_path: Path):
    assert emit("task.created") is None


def test_unknown_type_and_missing_fields_are_rejected(tmp_path: Path):
    _, session, project, root, run = _setup(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id):
        with pytest.raises(UnknownEventType):
            emit("task.exploded")
        with pytest.raises(InvalidEventPayload):
            emit("tool.started", {"tool": "x"})


def test_seq_is_monotonic_per_run_and_covers_legacy_producers(tmp_path: Path):
    factory, session, project, root, run = _setup(tmp_path)
    child = TaskService(session).create_task(project.id, TaskCreate(title="Filha", objective="o", parent_id=root.id))
    session.commit()
    with observe(session, run_id=run.id, project_id=project.id, task_id=child.id, agent="executor"):
        TaskService(session).update_status(child.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
        emit("plan.started", {"title": "Filha"})
        session.commit()
    rows = _events(session, run.id)
    seqs = [r.seq for r in rows]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs) and seqs[0] == 1
    by_type = {r.event_type: r for r in rows}
    assert "run.started" in by_type
    plan = by_type["plan.started"]
    assert plan.task_id == child.id and plan.parent_task_id == root.id and plan.agent == "executor"
    assert plan.schema_version == 1
    # Evento antigo sem run_id herda a run do contexto.
    assert any(r.task_id == child.id and r.event_type.startswith("task.") for r in rows)

    # Outro processo (novo barramento) continua a partir do maior seq gravado.
    get_bus().reset()
    other = factory()
    with observe(other, run_id=run.id, project_id=project.id):
        emit("run.progress", {"state": "progressing"})
        other.commit()
    assert _events(other, run.id)[-1].seq == seqs[-1] + 1


def test_runs_have_independent_sequences(tmp_path: Path):
    _, session, project, root, run = _setup(tmp_path)
    other_root = TaskService(session).create_task(project.id, TaskCreate(title="Outra", objective="o"))
    session.commit()
    run2 = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=other_root.id))
    session.commit()
    for r in (run, run2):
        with observe(session, run_id=r.id, project_id=project.id):
            emit("run.progress", {"state": "x"})
    session.commit()
    assert [e.seq for e in _events(session, run.id)] == [1, 2]
    assert [e.seq for e in _events(session, run2.id)] == [1, 2]


@pytest.mark.asyncio
async def test_persisted_events_are_published_only_after_commit(tmp_path: Path):
    _, session, project, root, run = _setup(tmp_path)
    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    try:
        with observe(session, run_id=run.id, project_id=project.id):
            emit("plan.started", {})
            session.flush()
            await asyncio.sleep(0.01)
            assert sub.queue.empty()
            session.rollback()
            emit("plan.updated", {"tasks": []})
            session.commit()
        await asyncio.sleep(0.01)
        got = [sub.queue.get_nowait()["type"] for _ in range(sub.queue.qsize())]
        assert got == ["plan.updated"]
    finally:
        bus.unsubscribe(sub)
    assert bus.subscriber_count(str(run.id)) == 0


@pytest.mark.asyncio
async def test_ephemeral_deltas_are_not_persisted_but_share_the_sequence(tmp_path: Path):
    _, session, project, root, run = _setup(tmp_path)
    bus = get_bus()
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        emit("agent.started", {"output_id": "o1", "provider": "p", "model": "m", "streaming": True}, commit=True)
        d1 = emit("agent.output.delta", {"output_id": "o1", "text": "Olá ", "offset": 0})
        d2 = emit("agent.output.delta", {"output_id": "o1", "text": "mundo", "offset": 4})
        live = bus.live(str(run.id))
        assert live["outputs"][0]["text"] == "Olá mundo"
        emit("agent.output.completed", {"output_id": "o1", "content": "Olá mundo"}, commit=True)
    assert d1["seq"] < d2["seq"] and not d1["persisted"]
    types = [e.event_type for e in _events(session, run.id)]
    assert "agent.output.delta" not in types and "agent.output.completed" in types
    assert bus.live(str(run.id))["outputs"] == []
    recent = bus.recent(str(run.id), after_seq=d1["seq"])
    assert [e["type"] for e in recent] == ["agent.output.delta", "agent.output.completed"]


def test_secrets_are_redacted_and_long_text_truncated():
    data = sanitize(
        {
            "api_key": "abc123",
            "tokens": 12,
            "env": {"OPENAI_API_KEY": "sk-xxxxxxxxxxxxxxxxxxxxxxxx"},
            "stdout": "export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx\nAuthorization: Bearer abcdefghijkl123\n"
            "max_tokens=4096 password: hunter22 url=https://user:pw1234@host/x",
        },
        limit=1000,
    )
    data["big"] = sanitize("x" * 500, limit=100)
    assert data["api_key"] == REDACTED and data["tokens"] == 12 and data["env"] == "[omitido]"
    out = data["stdout"]
    assert "sk-abc" not in out and "abcdefghijkl123" not in out and "hunter22" not in out and "pw1234" not in out
    assert "max_tokens=4096" in out
    assert len(data["big"]) < 200 and "omitidos" in data["big"]
    assert is_sensitive_path("config/.env") and is_sensitive_path("certs/server.pem")
    assert not is_sensitive_path("src/app.py")


@pytest.mark.asyncio
async def test_slow_subscriber_gets_resync_instead_of_unbounded_queue():
    bus = EventBus(queue_size=3)
    run_id = str(uuid.uuid4())
    bus.allocate_seq(run_id, lambda: 0)
    sub = bus.subscribe(run_id)
    for i in range(10):
        bus.publish({"run_id": run_id, "type": "run.progress", "seq": i + 1, "data": {"state": "x"}})
    await asyncio.sleep(0.01)
    items = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    assert len(items) <= 3 and any(e["type"] == RESYNC for e in items) and sub.dropped > 0
    bus.unsubscribe(sub)
