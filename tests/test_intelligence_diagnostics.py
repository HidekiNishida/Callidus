#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_diagnostics.py
Nome: test_intelligence_diagnostics.py
Propósito: verificar o motor de diagnóstico determinístico (detecção de problemas, severidade, recomendações).
Responsabilidade: camada de testes — comportamento unitário do DiagnosticEngine.
Componentes: DiagnosticEngine, Diagnostic, categorias, severidades, tipos.
Dependências: agent.intelligence.diagnostics, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from agent.intelligence.diagnostics import (
    DiagnosticEngine,
    Diagnostic,
    DIAGNOSTIC_CATEGORIES,
    DIAGNOSTIC_SEVERITIES,
    DIAGNOSTIC_KINDS,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    DiagnosticModel, EventLogModel, ExecutionRunModel, InferenceRecordModel,
    ProjectModel, TaskModel,
)
from agent.domain.enums import TaskStatus, RunStatus, TaskKind


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def _create_run(session):
    """Cria projeto, run e tarefa para testes de diagnóstico."""
    project = ProjectModel(name="test", root_path="/tmp")
    session.add(project)
    session.flush()

    root = TaskModel(
        id=uuid.uuid4(),
        project_id=project.id,
        title="root",
        objective="objetivo",
        kind=TaskKind.OBJECTIVE.value,
        status=TaskStatus.COMPLETED.value,
    )
    session.add(root)
    session.flush()

    run = ExecutionRunModel(
        id=uuid.uuid4(),
        project_id=project.id,
        root_task_id=root.id,
        status=RunStatus.COMPLETED.value,
        config_json={"provider": "ollama", "model_id": "llama3.2"},
    )
    session.add(run)
    session.flush()
    return run


def test_diagnostic_categories_severities_kinds():
    """DIAGNOSTIC_CATEGORIES, DIAGNOSTIC_SEVERITIES e DIAGNOSTIC_KINDS definem os valores válidos."""
    assert "gargalo_inferencia" in DIAGNOSTIC_CATEGORIES
    assert "excesso_retries" in DIAGNOSTIC_CATEGORIES
    assert "excesso_compactacao" in DIAGNOSTIC_CATEGORIES
    assert "baixa" in DIAGNOSTIC_SEVERITIES
    assert "critica" in DIAGNOSTIC_SEVERITIES
    assert "problema_comprovado" in DIAGNOSTIC_KINDS
    assert "anomalia_estatistica" in DIAGNOSTIC_KINDS
    assert "hipotese" in DIAGNOSTIC_KINDS
    assert "recomendacao" in DIAGNOSTIC_KINDS


def test_diagnostic_dataclass():
    """Diagnostic armazena todos os campos de um diagnóstico."""
    d = Diagnostic(
        id="diag-01",
        run_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        category="gargalo_inferencia",
        severity="alta",
        state="open",
        evidence={"calls": 10, "error_rate": 0.5},
        metric_affected="inference_latency",
        observed_period={"start": "2026-01-01", "end": "2026-01-02"},
        probable_cause="Muitas chamadas com erro",
        confidence_level="alto",
        recommendation="Reduzir orçamento de contexto",
        recommendation_state="pendente",
        kind="problema_comprovado",
    )
    dd = d.to_dict()
    assert dd["id"] == "diag-01"
    assert dd["category"] == "gargalo_inferencia"
    assert dd["severity"] == "alta"
    assert dd["state"] == "open"
    assert dd["metric_affected"] == "inference_latency"
    assert dd["probable_cause"] == "Muitas chamadas com erro"
    assert dd["kind"] == "problema_comprovado"


def test_diagnostic_engine_create_and_list():
    """O engine cria e lista diagnósticos."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = DiagnosticEngine(session)

    d = Diagnostic(
        id="diag-01",
        category="gargalo_inferencia",
        severity="alta",
        state="open",
        evidence={"calls": 10},
        probable_cause="causa",
        recommendation="ação",
        kind="problema_comprovado",
    )
    created = engine.create_diagnostic(d)
    assert created.id == "diag-01"

    all_diags = engine.list_diagnostics()
    assert len(all_diags) == 1
    assert all_diags[0].category == "gargalo_inferencia"
    session.close()


def test_diagnostic_engine_list_with_filters():
    """list_diagnostics filtra por run, categoria, severidade e estado."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = DiagnosticEngine(session)
    run = _create_run(session)

    d1 = Diagnostic(
        id="diag-01",
        run_id=run.id,
        category="gargalo_inferencia",
        severity="alta",
        state="open",
        evidence={},
        kind="problema_comprovado",
    )
    d2 = Diagnostic(
        id="diag-02",
        run_id=run.id,
        category="excesso_retries",
        severity="baixa",
        state="resolved",
        evidence={},
        kind="anomalia_estatistica",
    )
    d3 = Diagnostic(
        id="diag-03",
        category="excesso_compactacao",
        severity="media",
        state="open",
        evidence={},
        kind="hipotese",
    )
    engine.create_diagnostic(d1)
    engine.create_diagnostic(d2)
    engine.create_diagnostic(d3)

    by_run = engine.list_diagnostics(run_id=run.id)
    assert len(by_run) == 2

    by_category = engine.list_diagnostics(category="excesso_retries")
    assert len(by_category) == 1

    by_severity = engine.list_diagnostics(severity="alta")
    assert len(by_severity) == 1

    by_state = engine.list_diagnostics(state="open")
    assert len(by_state) == 2
    session.close()


def test_diagnostic_engine_get_and_analyze_run():
    """get_diagnostic devolve um diagnóstico; analyze_run gera diagnósticos a partir de evidências."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = DiagnosticEngine(session)
    run = _create_run(session)

    # Adiciona muitos registros de inferência com erro para triggering de diagnóstico de gargalo
    for i in range(15):
        status = "failed" if i % 3 == 0 else "completed"
        rec = InferenceRecordModel(
            idempotency_key=f"{run.id}:call{i}",
            run_id=run.id,
            task_id=run.root_task_id,
            project_id=run.project_id,
            agent="orchestrator",
            purpose="plan",
            provider="ollama",
            model_id="llama3.2",
            status=status,
            duration_ms=100 + i * 10,
            measurement="exact",
            prompt_tokens=10,
            completion_tokens=5,
        )
        session.add(rec)
    session.flush()

    diagnostics = engine.analyze_run(run.id)
    assert len(diagnostics) >= 1
    # Pelo menos um diagnóstico de gargalo de inferência deve ser gerado
    categories = {d.category for d in diagnostics}
    assert "gargalo_inferencia" in categories
    session.close()


def test_diagnostic_engine_summary():
    """get_summary agrega diagnósticos por categoria, severidade, estado e tipo."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = DiagnosticEngine(session)

    d1 = Diagnostic(
        id="diag-01",
        category="gargalo_inferencia",
        severity="critica",
        state="open",
        evidence={},
        kind="problema_comprovado",
    )
    d2 = Diagnostic(
        id="diag-02",
        category="excesso_retries",
        severity="media",
        state="resolved",
        evidence={},
        kind="anomalia_estatistica",
    )
    engine.create_diagnostic(d1)
    engine.create_diagnostic(d2)

    summary = engine.get_summary()
    assert summary["total"] == 2
    assert summary["critical"] == 1
    assert summary["open"] == 1
    assert summary["by_category"]["gargalo_inferencia"] == 1
    assert summary["by_severity"]["critica"] == 1
    assert summary["by_kind"]["problema_comprovado"] == 1
    session.close()


def test_diagnostic_engine_create_persists():
    """create_diagnostic persiste DiagnosticModel no banco."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = DiagnosticEngine(session)

    d = Diagnostic(
        id="diag-persist",
        category="ferramenta_lenta",
        severity="media",
        state="open",
        evidence={"calls": 5},
        probable_cause="ferramenta lenta",
        recommendation="otimizar",
        kind="problema_comprovado",
    )
    engine.create_diagnostic(d)

    row = session.scalar(select(DiagnosticModel).where(DiagnosticModel.diagnostic_id == "diag-persist"))
    assert row is not None
    assert row.category == "ferramenta_lenta"
    assert row.severity == "media"
    assert row.state == "open"
    assert row.probable_cause == "ferramenta lenta"
    session.close()
