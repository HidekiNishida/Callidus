#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_analytics.py
Nome: test_intelligence_analytics.py
Propósito: verificar o serviço de agregação de métricas (tokens, contexto, inferência, recursos, eficiência).
Responsabilidade: camada de testes — comportamento unitário do AnalyticsService.
Componentes: AnalyticsService, métricas de tokens, contexto, inferência, recursos, eficiência.
Dependências: agent.intelligence.analytics, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from agent.intelligence.analytics import AnalyticsService
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    ExecutionRunModel,
    InferenceRecordModel,
    ProjectModel,
    TaskModel,
)
from agent.domain.enums import TaskStatus, RunStatus, TaskKind


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def _create_run_task(session):
    """Cria projeto, run e tarefa para testes de analytics."""
    project = ProjectModel(
        name="test-project",
        root_path="/tmp/test",
    )
    session.add(project)
    session.flush()

    run = ExecutionRunModel(
        project_id=project.id,
        root_task_id=uuid.uuid4(),
        status=RunStatus.ACTIVE.value,
        config_json={"provider": "ollama", "model_id": "llama3.2"},
    )
    session.add(run)
    session.flush()

    task = TaskModel(
        id=run.root_task_id,
        project_id=project.id,
        title="test task",
        objective="do something",
        kind=TaskKind.OBJECTIVE.value,
        status=TaskStatus.COMPLETED.value,
        metadata_json={"usage": {"prompt": 100, "completion": 50, "total": 150, "calls": 3, "measurement": "exact"}},
    )
    session.add(task)
    session.flush()
    return project, run, task


def test_analytics_token_metrics():
    """token_metrics agrega entrada, saída e total com qualidade de medição."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    rec = InferenceRecordModel(
        idempotency_key=f"{run.id}:call1",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        agent="orchestrator",
        purpose="plan",
        provider="ollama",
        model_id="llama3.2",
        status="completed",
        duration_ms=200,
        measurement="exact",
        prompt_tokens=100,
        completion_tokens=50,
        estimated_prompt_tokens=110,
        estimated_completion_tokens=60,
    )
    session.add(rec)
    session.flush()

    metrics = analytics.token_metrics(run_id=run.id)
    assert metrics["prompt_tokens"] == 100
    assert metrics["prompt_measurement"] == "exact"
    assert metrics["completion_tokens"] == 50
    assert metrics["total_tokens"] == 150
    assert metrics["total_measurement"] == "exact"
    assert metrics["calls"] == 1
    session.close()


def test_analytics_context_metrics():
    """context_metrics agrega snapshots de contexto e eventos de compactação."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    snap = ContextSnapshotModel(
        project_id=project.id,
        task_id=task.id,
        run_id=run.id,
        estimated_tokens=4000,
    )
    session.add(snap)

    # Adiciona um registro de inferência com pressão de orçamento
    inf = InferenceRecordModel(
        idempotency_key=f"{run.id}:pressure",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        agent="orchestrator",
        purpose="plan",
        provider="ollama",
        model_id="llama3.2",
        status="completed",
        duration_ms=100,
        measurement="exact",
        prompt_tokens=10,
        completion_tokens=5,
        budget_pressure=True,
    )
    session.add(inf)

    event = EventLogModel(
        project_id=project.id,
        run_id=run.id,
        task_id=task.id,
        event_type="context.compacted",
        payload_json={"before_tokens": 5000, "after_tokens": 3000, "purpose": "pressão"},
    )
    session.add(event)
    session.flush()

    metrics = analytics.context_metrics(run_id=run.id)
    assert metrics["snapshots"] == 1
    assert metrics["estimated_tokens_total"] == 4000
    assert metrics["budget_pressure_count"] == 1
    assert metrics["compaction_events"] == 1
    session.close()


def test_analytics_inference_metrics():
    """inference_metrics calcula taxa de erro, timeout e duração por percentil."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    for i, status in enumerate(["completed", "completed", "failed", "timeout"]):
        rec = InferenceRecordModel(
            idempotency_key=f"{run.id}:call{i}",
            run_id=run.id,
            task_id=task.id,
            project_id=project.id,
            agent="orchestrator",
            purpose="plan",
            provider="ollama",
            model_id="llama3.2",
            status=status,
            duration_ms=100 + i * 50,
            measurement="exact",
            prompt_tokens=10,
            completion_tokens=5,
        )
        session.add(rec)
    session.flush()

    metrics = analytics.inference_metrics(run_id=run.id)
    assert metrics["calls"] == 4
    assert metrics["completed"] == 2
    assert metrics["failed"] == 1
    assert metrics["timed_out"] == 1
    assert metrics["error_rate"] == 0.25
    assert metrics["timeout_rate"] == 0.25
    session.close()


def test_analytics_resource_metrics():
    """resource_metrics agrega amostras de CPU, RAM e VRAM."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    for i, (cpu, ram, vram) in enumerate([(30.0, 500.0, 200.0), (60.0, 800.0, 400.0)]):
        event = EventLogModel(
            project_id=project.id,
            run_id=run.id,
            task_id=task.id,
            event_type="resources.sampled",
            payload_json={"cpu_percent": cpu, "ram_mb": ram, "vram_mb": vram},
        )
        session.add(event)
    session.flush()

    metrics = analytics.resource_metrics(run_id=run.id)
    assert metrics["samples"] == 2
    assert metrics["cpu_percent"]["avg"] == 45.0
    assert metrics["cpu_percent"]["max"] == 60.0
    assert metrics["ram_mb"]["max"] == 800.0
    assert metrics["vram_mb"]["max"] == 400.0
    session.close()


def test_analytics_efficiency_metrics():
    """efficiency_metrics calcula taxa de conclusão, tokens por tarefa e progresso."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    # Adiciona uma segunda tarefa falhada (filha da raiz)
    task2 = TaskModel(
        id=uuid.uuid4(),
        project_id=project.id,
        parent_id=task.id,
        title="failed task",
        objective="fail",
        kind=TaskKind.OBJECTIVE.value,
        status=TaskStatus.FAILED.value,
        metadata_json={"usage": {"prompt": 50, "completion": 25, "total": 75, "calls": 2, "measurement": "exact"}},
    )
    session.add(task2)
    session.flush()

    metrics = analytics.efficiency_metrics(run_id=run.id)
    assert metrics["tasks_total"] == 2
    assert metrics["tasks_completed"] == 1
    assert metrics["tasks_failed"] == 1
    assert metrics["completion_rate"] == 0.5
    assert metrics["tokens_per_completed_task"] == 150.0
    session.close()


def test_analytics_overview():
    """overview agrega métricas de alto nível para o dashboard."""
    SessionLocal = setup_function()
    session = SessionLocal()
    analytics = AnalyticsService(session)
    project, run, task = _create_run_task(session)

    overview = analytics.overview(project_id=project.id)
    assert overview["runs_total"] == 1
    assert overview["runs_completed"] == 0  # run está ACTIVE
    assert overview["runs_active"] == 1
    assert "tokens" in overview
    assert "inference" in overview
    assert "resources" in overview
    assert "efficiency" in overview
    assert "recent_runs" in overview
    session.close()


def test_analytics_percentile():
    """_percentile calcula percentis corretamente."""
    from agent.intelligence.analytics import _percentile

    assert _percentile([], 50) is None
    assert _percentile([42], 50) == 42
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert _percentile(vals, 50) == 5.5  # mediana
    assert _percentile(vals, 90) == 9.1
