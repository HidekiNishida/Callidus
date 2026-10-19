#!/usr/bin/env python3
# tests/test_observability_unit1.py
# Unit 1 tests for observabilidade-tempo-real: contrato, barramento, emissor, migração

import uuid
from datetime import datetime, timezone
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.persistence.models import Base, EventLogModel, TaskModel
from agent.persistence.database import init_db, build_session_factory
from agent.observability.contracts import (
    EVENT_SPECS,
    SCHEMA_VERSION,
    UnknownEventType,
    InvalidEventPayload,
    validate_payload,
    spec_for,
    envelope_from_row,
)
from agent.observability.emitter import observe, emit, _CURRENT
from agent.observability.bus import get_bus
from agent.observability.sanitize import sanitize


def setup_function():
    # Create a fresh in-memory database for each test
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def test_event_specs_and_validation():
    """Contract: specs exist and validation works."""
    SessionLocal = setup_function()
    # Known event type
    spec = spec_for("agent.started")
    assert spec.type == "agent.started"
    assert spec.category == "agent"
    assert spec.persist is True
    assert spec.required == ("output_id", "provider", "model", "streaming")

    # Validate payload
    data = {
        "output_id": "out1",
        "provider": "test",
        "model": "test-model",
        "streaming": True,
    }
    validated = validate_payload("agent.started", data)
    assert validated == data

    # Missing required
    with pytest.raises(InvalidEventPayload):
        validate_payload("agent.started", {"output_id": "out1"})

    # Unknown event type
    with pytest.raises(UnknownEventType):
        spec_for("unknown.event")


def test_envelope_from_row():
    """Envelope conversion from row."""
    SessionLocal = setup_function()
    with SessionLocal() as session:
        # Create an instance without specifying id (let default work)
        row = EventLogModel(
            project_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            event_type="test.event",
            payload_json={"foo": "bar"},
            agent="test-agent",
            created_at=datetime.now(timezone.utc),
            seq=5,
            parent_task_id=uuid.uuid4(),
            schema_version=SCHEMA_VERSION,
        )
        session.add(row)
        session.commit()
        env = envelope_from_row(row)
        assert env["id"] == str(row.id)
        assert env["run_id"] == str(row.run_id)
        assert env["task_id"] == str(row.task_id)
        assert env["parent_task_id"] == str(row.parent_task_id)
        assert env["agent"] == row.agent
        assert env["type"] == row.event_type
        assert env["seq"] == row.seq
        # ts is a string in ISO format with Z suffix
        expected_ts = row.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        assert env["ts"] == expected_ts
        assert env["data"] == row.payload_json
        assert env["persisted"] is True
        assert env["schema_version"] == SCHEMA_VERSION


def test_emit_without_context():
    """Emit outside of observe context returns None."""
    SessionLocal = setup_function()
    with SessionLocal() as session:
        result = emit("agent.started", {"output_id": "x", "provider": "p", "model": "m", "streaming": True})
        assert result is None


def test_emit_persists_after_commit():
    """Emit inside observe context persists row only after commit."""
    SessionLocal = setup_function()
    bus = get_bus()
    # Reset bus state for test
    bus.reset()

    with SessionLocal() as session:
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        project_id = uuid.uuid4()
        with observe(session, run_id=run_id, task_id=task_id, project_id=project_id, agent="test-agent"):
            # Emit a persisted event
            row = emit("agent.started", {"output_id": "out1", "provider": "prov", "model": "mod", "streaming": False}, commit=False)
            assert row is not None
            # Not committed yet, should not be published
            assert bus.subscriber_count(str(run_id)) == 0
            # Check that row is in session but not committed
            assert row in session.new
            # Emit a fragment (should be published immediately)
            fragment = emit("agent.output.delta", {"output_id": "out1", "text": "hello", "offset": 0}, commit=False)
            assert fragment is not None
            assert fragment["persisted"] is False

        # Commit the transaction
        session.commit()

    # After commit, we should be able to query the row with a new session from the same engine
    with SessionLocal() as session:
        rows = session.query(EventLogModel).filter(EventLogModel.event_type == "agent.started").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.agent == "test-agent"
        assert row.payload_json == {"output_id": "out1", "provider": "prov", "model": "mod", "streaming": False}
        # Note: the seq is 2 because the fragment (non-persisted) also consumed a seq number
        assert row.seq == 2  # first seq for this run is 1, but fragment took 1, so this is 2
        assert row.project_id == project_id
        assert row.run_id == run_id
        assert row.task_id == task_id
        # Check that parent_task_id is None because task has no parent in this test
        assert row.parent_task_id is None
        assert row.schema_version == SCHEMA_VERSION


def test_sequence_allocation():
    """Sequence numbers increase per run and are based on max seq in db."""
    SessionLocal = setup_function()
    bus = get_bus()
    bus.reset()

    with SessionLocal() as session:
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        with observe(session, run_id=run_id, task_id=task_id):
            # Emit two events without commit
            emit("agent.started", {"output_id": "o1", "provider": "p", "model": "m", "streaming": True}, commit=False)
            emit("agent.started", {"output_id": "o2", "provider": "p", "model": "m", "streaming": True}, commit=False)
            # Flush to get seq numbers assigned
            session.flush()
            # Check seq numbers
            rows = session.query(EventLogModel).filter(EventLogModel.run_id == run_id).order_by(EventLogModel.seq).all()
            assert len(rows) == 2
            assert rows[0].seq == 1
            assert rows[1].seq == 2
            # Now commit
            session.commit()

    # Simulate existing rows in db: manually set seq to 10 for this run
    with SessionLocal() as session:
        # Add a row with seq=10
        existing = EventLogModel(
            run_id=run_id,
            task_id=task_id,
            event_type="test.existing",
            payload_json={},
            agent="test",
            created_at=datetime.now(timezone.utc),
            seq=10,
        )
        session.add(existing)
        session.commit()

        # Reset the bus state for this run_id so that it re-queries the database for the max seq
        bus = get_bus()
        with bus._lock:
            if str(run_id) in bus._runs:
                del bus._runs[str(run_id)]

    with SessionLocal() as session:
        run_id2 = uuid.uuid4()
        task_id2 = uuid.uuid4()
        with observe(session, run_id=run_id2, task_id=task_id2):
            emit("agent.started", {"output_id": "o3", "provider": "p", "model": "m", "streaming": True}, commit=False)
            session.flush()
            rows = session.query(EventLogModel).filter(EventLogModel.run_id == run_id2).all()
            assert len(rows) == 1
            assert rows[0].seq == 1
            session.commit()

    # Same run after existing row should continue at 11
    with SessionLocal() as session:
        with observe(session, run_id=run_id, task_id=task_id):
            emit("agent.started", {"output_id": "o4", "provider": "p", "model": "m", "streaming": True}, commit=False)
            session.flush()
            rows = session.query(EventLogModel).filter(EventLogModel.run_id == run_id).order_by(EventLogModel.seq).all()
            seqs = [r.seq for r in rows]
            assert seqs == [1, 2, 10, 11]
            session.commit()


def test_parent_task_id_and_agent_set():
    """When emitting, parent_task_id and agent are set from context if not provided."""
    SessionLocal = setup_function()
    with SessionLocal() as session:
        parent_task_id = uuid.uuid4()
        child_task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        project_id = uuid.uuid4()
        # Persist parent task
        parent_task = TaskModel(
            id=parent_task_id,
            project_id=project_id,
            title="parent",
            objective="parent obj",
        )
        # Persist child task with parent_id set
        child_task = TaskModel(
            id=child_task_id,
            project_id=project_id,
            title="child",
            objective="child obj",
            parent_id=parent_task_id,
        )
        session.add(parent_task)
        session.add(child_task)
        session.commit()

        with observe(session, run_id=run_id, task_id=child_task_id, project_id=project_id, agent="context-agent"):
            # Emit without providing task_id or agent (should use context)
            row = emit("agent.started", {"output_id": "o1", "provider": "p", "model": "m", "streaming": True}, commit=False)
            assert row.task_id == child_task_id
            assert row.agent == "context-agent"
            # parent_task_id is not set yet because we haven't flushed
        # Commit the transaction
        session.commit()
        # Now refresh the row from the database
        from sqlalchemy import select
        stmt = select(EventLogModel).where(EventLogModel.id == row.id)
        result = session.execute(stmt).scalar_one()
        assert result.parent_task_id == parent_task_id

        # Now for the second part: create explicit task and its parent
        explicit_task_id = uuid.uuid4()
        explicit_parent_id = uuid.uuid4()
        explicit_task = TaskModel(
            id=explicit_task_id,
            project_id=project_id,
            title="explicit",
            objective="explicit obj",
            parent_id=explicit_parent_id,
        )
        session.add(explicit_task)
        session.commit()

        # Now emit with explicit task_id and agent, but we need an observe context to have a session and run_id.
        # We'll use a new observe block with a dummy task_id and agent (they will be overridden).
        with observe(session, run_id=run_id, task_id=uuid.uuid4(), agent="dummy", project_id=project_id):
            row2 = emit("agent.started", {"output_id": "o2", "provider": "p", "model": "m", "streaming": True},
                       task_id=explicit_task_id, agent="explicit-agent", commit=False)
            assert row2 is not None
            assert row2.task_id == explicit_task_id
            assert row2.agent == "explicit-agent"
            # Flush to set parent_task_id and other defaults
            session.flush()
            # parent_task_id should be the parent of the explicit task
            assert row2.parent_task_id == explicit_parent_id
        session.rollback()


def test_sanitize_text_limit():
    """Text payloads are sanitized to event_text_limit."""
    from agent.config import get_settings
    settings = get_settings()
    limit = settings.event_text_limit
    long_text = "x" * (limit + 10)
    SessionLocal = setup_function()
    with SessionLocal() as session:
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        with observe(session, run_id=run_id, task_id=task_id):
            # Emit a persisted event with a long text in a custom field (e.g., we can add a field to payload)
            # Use agent.started and add a "text" field (extra fields are allowed)
            row = emit("agent.started", {"output_id": "out1", "provider": "p", "model": "m", "streaming": False, "text": long_text}, commit=False)
            # Flush to trigger sanitization
            session.flush()
            # The row's payload_json should have the text field trimmed to limit
            assert len(row.payload_json["text"]) == limit
            session.commit()


def test_migration_columns_exist():
    """Ensure the migration added the expected columns to event_logs."""
    SessionLocal = setup_function()
    with SessionLocal() as session:
        # Try to insert a row with all columns
        row = EventLogModel(
            run_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            event_type="test.migration",
            payload_json={},
            agent="test",
            created_at=datetime.now(timezone.utc),
            seq=1,
            parent_task_id=uuid.uuid4(),
            schema_version=99,
        )
        session.add(row)
        session.commit()
        # If no error, columns exist.
        assert row.id is not None