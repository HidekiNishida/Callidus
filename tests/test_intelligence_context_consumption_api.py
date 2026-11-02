#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_context_consumption_api.py
Nome: test_intelligence_context_consumption_api.py
Propósito: verificar o serviço e os contratos HTTP das rotas de consumo de contexto, bem como
           a correlação entre inferência, run, tarefa e snapshot.
Responsabilidade: camada de testes — integração de `ContextConsumptionService` com o banco real
                  e dos endpoints `GET /api/intelligence/context-consumption/*` e
                  `GET /api/intelligence/inferences/*` via TestClient.
Componentes: ContextConsumptionService, funções de rota, modelos de persistência, TestClient.
Dependências: sqlalchemy, uuid, datetime, fastapi.testclient, agent.api.*, agent.persistence.*,
              pytest.
Observações: banco SQLite temporário isolado por teste (CALLIDUS_TEST_DATABASE_URL); nenhuma rede
             nem serviço externo é usado.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from tempfile import mkdtemp

import pytest
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from agent.api import deps
from agent.api.intelligence_routes import (
    context_consumption_by_component,
    context_consumption_by_type,
    context_consumption_compare,
    context_consumption_matrix,
    context_consumption_opportunities,
    context_consumption_overview,
    context_consumption_timeline,
    get_inference,
    get_inference_components,
    router,
)
from agent.config import Settings
from agent.domain.enums import InferenceType, RunStatus, TaskKind, TaskStatus
from agent.orchestrator.inference_usage import TOKENIZER_STRATEGY, TOKENIZER_VERSION
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    ContextSnapshotModel,
    ExecutionRunModel,
    InferenceRecordModel,
    ProjectModel,
    TaskModel,
)


@pytest.fixture
def session(tmp_path, monkeypatch):
    """Banco SQLite temporário isolado e sessão aberta para o teste."""
    db_url = f"sqlite:///{mkdtemp()}/agent.db"
    monkeypatch.setenv("CALLIDUS_TEST_DATABASE_URL", db_url)
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


@pytest.fixture
def client(session):
    """TestClient da API ligado ao banco temporário do teste, com worker desligado."""
    settings = Settings(data_dir=mkdtemp(), enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None

    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def _seed(session):
    """Cria projeto, run, tarefa, snapshot e inferências correlacionadas."""
    project = ProjectModel(name="api-projeto", root_path="/tmp/api")
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
        title="tarefa raiz",
        objective="exercitar a API de consumo",
        kind=TaskKind.OBJECTIVE.value,
        status=TaskStatus.COMPLETED.value,
    )
    session.add(task)
    session.flush()

    snap = ContextSnapshotModel(
        project_id=project.id,
        task_id=task.id,
        run_id=run.id,
        estimated_tokens=700,
        components_json=[
            {"category": "system_instructions", "identification": "regras", "tokens": 200, "required": True, "measurement": "estimate"},
            {"category": "objetivo", "identification": "enunciado", "tokens": 100, "required": True, "measurement": "estimate"},
        ],
        strategy_notes_json=[],
        refs_json=[],
        categories_json=[
            {"category": "system_instructions", "components": [{"name": "regras", "tokens": 200}]},
        ],
    )
    session.add(snap)
    session.flush()

    now = datetime.now(UTC)
    inf_plan = InferenceRecordModel(
        idempotency_key=f"{run.id}:plan-1",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        agent="orchestrator",
        purpose="plan",
        inference_type=InferenceType.PLANNING.value,
        provider="ollama",
        model_id="llama3.2",
        status="completed",
        duration_ms=120,
        measurement="exact",
        prompt_tokens=100,
        completion_tokens=50,
        reasoning_tokens=10,
        cache_read_tokens=5,
        context_window_size=8192,
        tokenizer_version=TOKENIZER_VERSION,
        tokenizer_strategy=TOKENIZER_STRATEGY,
        components_included_json=[
            {"category": "system_instructions", "identification": "regras", "tokens": 200, "required": True, "measurement": "estimate", "origin": "snapshot"},
            {"category": "objetivo", "identification": "enunciado", "tokens": 100, "required": True, "measurement": "estimate", "origin": "snapshot"},
        ],
        created_at=now,
    )
    inf_op = InferenceRecordModel(
        idempotency_key=f"{run.id}:operation-1",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        agent="orchestrator",
        purpose="operation",
        inference_type=InferenceType.EXECUTION.value,
        provider="ollama",
        model_id="llama3.2",
        status="completed",
        duration_ms=250,
        measurement="exact",
        prompt_tokens=300,
        completion_tokens=150,
        context_window_size=8192,
        tokenizer_version=TOKENIZER_VERSION,
        tokenizer_strategy=TOKENIZER_STRATEGY,
        components_included_json=[
            {"category": "ferramentas", "identification": "write_file", "tokens": 300, "required": False, "measurement": "estimate", "origin": "snapshot", "optimization_potential": True},
        ],
        created_at=now,
    )
    inf_unav = InferenceRecordModel(
        idempotency_key=f"{run.id}:verify-1",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        agent="orchestrator",
        purpose="verify",
        inference_type=InferenceType.VERIFICATION.value,
        provider="ollama",
        model_id="qwen3:8b",
        status="failed",
        duration_ms=80,
        measurement="unavailable",
        prompt_tokens=None,
        completion_tokens=None,
        context_window_size=None,
        tokenizer_version=TOKENIZER_VERSION,
        tokenizer_strategy=TOKENIZER_STRATEGY,
        created_at=now,
    )
    session.add_all([inf_plan, inf_op, inf_unav])
    session.flush()
    session.commit()
    return project, run, task, snap, inf_plan, inf_op, inf_unav


# ── Serviço (banco real) ──────────────────────────────────────────────

def test_service_overview(session):
    _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    view = svc.overview()
    assert view["samples"] == 3
    assert view["inferences_total"] == 3
    assert view["input_tokens"]["value"] == 400
    assert view["output_tokens"]["value"] == 200
    assert view["total_tokens"]["value"] == 600
    assert view["avg_window_occupancy_pct"]["count"] == 2


def test_service_by_type(session):
    _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    result = svc.by_inference_type()
    types = {g["type"] for g in result["groups"]}
    assert "planning" in types
    assert "execution" in types


def test_service_by_component(session):
    _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    result = svc.by_component()
    cats = {g["category"]: g for g in result["groups"]}
    assert cats["system_instructions"]["tokens_total"] == 200
    assert cats["ferramentas"]["optimization_potential"] == 1
    assert result["grand_total_tokens"] == 600


def test_service_matrix(session):
    _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    result = svc.matrix()
    assert "planning" in result["types"]
    assert "execution" in result["types"]
    assert "system_instructions" in result["categories"]
    assert "ferramentas" in result["categories"]


def test_service_get_inference_and_components(session):
    _, run, task, snap, inf_plan, _, _ = _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    detail = svc.get_inference(inf_plan.id)
    assert detail is not None
    assert detail["run_id"] == str(run.id)
    assert detail["task_id"] == str(task.id)
    assert detail["purpose"] == "plan"
    assert detail["inference_type"] == "planning"
    assert detail["prompt_tokens"] == 100
    assert detail["completion_tokens"] == 50
    assert detail["measurement"] == "exact"
    assert detail["provider"] == "ollama"
    assert detail["model"] == "llama3.2"

    comps = svc.get_inference_components(inf_plan.id)
    assert comps is not None
    assert comps["inference_id"] == str(inf_plan.id)
    assert comps["total_components"] == 2
    cats = {c["category"]: c for c in comps["categories"]}
    assert cats["system_instructions"]["tokens"] == 200


def test_service_inference_without_provider_usage(session):
    _, _, _, _, _, _, inf_unav = _seed(session)
    from agent.intelligence.context_consumption import ContextConsumptionService
    svc = ContextConsumptionService(session)
    detail = svc.get_inference(inf_unav.id)
    assert detail is not None
    assert detail["measurement"] == "unavailable"
    assert detail["prompt_tokens"] is None
    assert detail["completion_tokens"] is None
    view = svc.overview()
    assert view["inferences_total"] == 3


# ── Rotas HTTP (TestClient) ───────────────────────────────────────────

def test_routes_registered():
    """As rotas de consumo de contexto e inferência estão registradas no router."""
    paths = {r.path for r in router.routes}
    assert "/api/intelligence/context-consumption/overview" in paths
    assert "/api/intelligence/context-consumption/by-type" in paths
    assert "/api/intelligence/context-consumption/by-component" in paths
    assert "/api/intelligence/context-consumption/matrix" in paths
    assert "/api/intelligence/context-consumption/compare" in paths
    assert "/api/intelligence/context-consumption/timeline" in paths
    assert "/api/intelligence/context-consumption/opportunities" in paths
    assert "/api/intelligence/inferences/{inference_id}" in paths
    assert "/api/intelligence/inferences/{inference_id}/components" in paths


def test_http_overview(client, session):
    _seed(session)
    resp = client.get("/api/intelligence/context-consumption/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["samples"] == 3
    assert data["inferences_total"] == 3
    assert data["input_tokens"]["value"] == 400


def test_http_by_component(client, session):
    _seed(session)
    resp = client.get("/api/intelligence/context-consumption/by-component")
    assert resp.status_code == 200
    data = resp.json()
    cats = {g["category"]: g for g in data["groups"]}
    assert cats["system_instructions"]["tokens_total"] == 200
    assert data["grand_total_tokens"] == 600


def test_http_get_inference(client, session):
    _, _, _, _, inf_plan, _, _ = _seed(session)
    resp = client.get(f"/api/intelligence/inferences/{inf_plan.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(inf_plan.id)
    assert data["purpose"] == "plan"
    assert data["model"] == "llama3.2"
    assert data["provider"] == "ollama"


def test_http_get_inference_components(client, session):
    _, _, _, _, inf_plan, _, _ = _seed(session)
    resp = client.get(f"/api/intelligence/inferences/{inf_plan.id}/components")
    assert resp.status_code == 200
    data = resp.json()
    assert data["inference_id"] == str(inf_plan.id)
    assert data["total_components"] == 2


def test_http_get_inference_not_found(client):
    resp = client.get(f"/api/intelligence/inferences/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_http_get_inference_components_not_found(client):
    resp = client.get(f"/api/intelligence/inferences/{uuid.uuid4()}/components")
    assert resp.status_code == 404
