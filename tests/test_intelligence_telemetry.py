#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_telemetry.py
Nome: test_intelligence_telemetry.py
Propósito: verificar o serviço de telemetria centralizada (eventos tipados, correlação, emissão fora de contexto).
Responsabilidade: camada de testes — comportamento unitário do TelemetryService.
Componentes: TelemetryService, emissão de eventos de orquestrador, provedor, contexto, recursos e verificação.
Dependências: agent.intelligence.telemetry, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from agent.intelligence.telemetry import TelemetryService
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def test_telemetry_service_creation():
    """O TelemetryService é instanciado com uma sessão e tem _current_event_id inicial None."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)
    assert svc._session is session
    assert svc._current_event_id is None
    session.close()


def test_telemetry_step_started_completed():
    """step_started e step_completed emitem eventos com os campos corretos de correlação."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    # Fora de contexto de observação, emit não grava nada
    result = svc.step_started(step_index=1, run_id=run_id)
    assert result is None

    # Dentro do contexto de observação, grava EventLogModel
    from agent.observability.emitter import observe

    with observe(session, run_id=run_id, task_id=task_id):
        res1 = svc.step_started(step_index=1)
        res2 = svc.step_completed(step_index=1, action="decomposed", duration_ms=120)

    assert res1 is not None
    assert res2 is not None
    assert svc._current_event_id == res2.id

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.run_id == run_id)
    ).all())
    assert len(rows) == 2
    event_types = {r.event_type for r in rows}
    assert "orchestrator.step.started" in event_types
    assert "orchestrator.step.completed" in event_types
    session.close()


def test_telemetry_state_transitioned():
    """state_transitioned emite evento com from, to e motivo da transição de tarefa."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    from agent.observability.emitter import observe
    with observe(session, run_id=run_id, task_id=task_id):
        svc.state_transitioned(
            task_id=task_id,
            from_status="PENDING",
            to_status="PLANNING",
            reason="iniciou planejamento",
        )

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.task_id == task_id)
    ).all())
    assert len(rows) == 1
    assert rows[0].event_type == "task.state.transitioned"
    payload = rows[0].payload_json
    assert payload["from"] == "PENDING"
    assert payload["to"] == "PLANNING"
    assert payload["reason"] == "iniciou planejamento"
    session.close()


def test_telemetry_provider_inference():
    """provider_inference_started e provider_inference_completed emitem eventos com métricas de tokens."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    from agent.observability.emitter import observe
    with observe(session, run_id=run_id, task_id=task_id):
        svc.provider_inference_started(
            provider="ollama",
            model="llama3.2",
            purpose="plan",
        )
        svc.provider_inference_completed(
            provider="ollama",
            model="llama3.2",
            duration_ms=450,
            prompt_tokens=120,
            completion_tokens=80,
            measurement_quality="exact",
        )

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.run_id == run_id)
    ).all())
    assert len(rows) == 2
    started = [r for r in rows if r.event_type == "provider.inference.started"][0]
    completed = [r for r in rows if r.event_type == "provider.inference.completed"][0]
    assert started.payload_json["provider"] == "ollama"
    assert started.payload_json["model"] == "llama3.2"
    assert completed.payload_json["prompt_tokens"] == 120
    assert completed.payload_json["completion_tokens"] == 80
    assert completed.payload_json["duration_ms"] == 450
    assert completed.payload_json["measurement_quality"] == "exact"
    session.close()


def test_telemetry_context_compacted():
    """context_compacted emite evento com antes/depois de tokens e tokens removidos."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()

    from agent.observability.emitter import observe
    with observe(session, run_id=run_id):
        svc.context_compacted(
            before_tokens=5000,
            after_tokens=3000,
            purpose="pressão de orçamento",
        )

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.run_id == run_id)
    ).all())
    assert len(rows) == 1
    payload = rows[0].payload_json
    assert payload["before_tokens"] == 5000
    assert payload["after_tokens"] == 3000
    assert payload["tokens_removed"] == 2000
    session.close()


def test_telemetry_resources_sampled():
    """resources_sampled emite evento com consumo de CPU, RAM e VRAM."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()
    svc.resources_sampled(
        cpu_percent=45.5,
        ram_mb=1024.0,
        vram_mb=512.0,
        run_id=run_id,
    )

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.run_id == run_id)
    ).all())
    assert len(rows) == 1
    payload = rows[0].payload_json
    assert payload["cpu_percent"] == 45.5
    assert payload["ram_mb"] == 1024.0
    assert payload["vram_mb"] == 512.0
    session.close()


def test_telemetry_verification_attempt():
    """verification_attempt_started e verification_attempt_completed emitem eventos com resultado."""
    SessionLocal = setup_function()
    session = SessionLocal()
    svc = TelemetryService(session)

    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    from agent.observability.emitter import observe
    with observe(session, run_id=run_id, task_id=task_id):
        svc.verification_attempt_started(verifier="pytest")
        svc.verification_attempt_completed(
            verifier="pytest",
            passed=True,
            duration_ms=300,
        )

    rows = list(session.scalars(
        __import__("sqlalchemy").select(EventLogModel).where(EventLogModel.run_id == run_id)
    ).all())
    assert len(rows) == 2
    started = [r for r in rows if r.event_type == "verification.attempt.started"][0]
    completed = [r for r in rows if r.event_type == "verification.attempt.completed"][0]
    assert started.payload_json["verifier"] == "pytest"
    assert completed.payload_json["passed"] is True
    assert completed.payload_json["duration_ms"] == 300
    session.close()


def test_telemetry_telemetry_event_dataclass():
    """TelemetryEvent converte corretamente para dicionário de emissão com campos de correlação."""
    from agent.intelligence.telemetry import TelemetryEvent

    ev = TelemetryEvent(
        event_type="orchestrator.step.started",
        run_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        parent_event_id=uuid.uuid4(),
        component="orchestrator",
        operation="step",
        status="started",
        duration_ms=100,
        measurement_quality="exact",
    )
    data = ev.to_emit_data()
    assert data["component"] == "orchestrator"
    assert data["operation"] == "step"
    assert data["status"] == "started"
    assert data["duration_ms"] == 100
    assert data["measurement_quality"] == "exact"
    assert "attempt_id" in data
    assert "parent_event_id" in data
    assert data["schema_version"] == 2
