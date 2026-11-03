#!/usr/bin/env python3

"""
Arquivo: tests/test_context_consumption.py
Nome: test_context_consumption.py
Propósito: verificar a classificação de tipo de inferência e o serviço de consumo de contexto.
Responsabilidade: camada de testes — comportamento unitário de classify_inference_type e ContextConsumptionService.
Componentes: classify_inference_type, ContextConsumptionService, enums de domínio.
Dependências: agent.orchestrator.inference_usage, agent.intelligence.context_consumption, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from agent.domain.enums import InferenceType, TaskStatus, RunStatus, TaskKind
from agent.intelligence.context_consumption import ContextConsumptionService
from agent.orchestrator.inference_usage import (
    classify_inference_type,
    TOKENIZER_STRATEGY,
    TOKENIZER_VERSION,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    ExecutionRunModel,
    InferenceRecordModel,
    ProjectModel,
    TaskModel,
)


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def _create_run_task(session):
    """Cria projeto, run e tarefa para testes de consumo de contexto."""
    project = ProjectModel(name="test-project", root_path="/tmp/test")
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


def _add_inference(session, run, task, *, purpose="plan", provider="ollama", model="llama3.2",
                   prompt=100, completion=50, status="completed", window=8192,
                   components=None, agent="orchestrator"):
    """Acrescenta um registro de inferência ao banco."""
    rec = InferenceRecordModel(
        idempotency_key=f"{run.id}:{purpose}-{uuid.uuid4().hex[:6]}",
        run_id=run.id,
        task_id=task.id,
        project_id=run.project_id,
        agent=agent,
        purpose=purpose,
        inference_type=classify_inference_type(purpose),
        provider=provider,
        model_id=model,
        status=status,
        duration_ms=200,
        measurement="exact",
        prompt_tokens=prompt,
        completion_tokens=completion,
        context_window_size=window,
        tokenizer_version=TOKENIZER_VERSION,
        tokenizer_strategy=TOKENIZER_STRATEGY,
        components_included_json=components,
    )
    session.add(rec)
    return rec


# ── Classificação ──────────────────────────────────────────────────────

@pytest.mark.parametrize("purpose,expected", [
    ("plan", InferenceType.PLANNING.value),
    ("planning", InferenceType.PLANNING.value),
    ("decompose", InferenceType.TASK_DECOMPOSITION.value),
    ("decomposition", InferenceType.TASK_DECOMPOSITION.value),
    ("operation", InferenceType.EXECUTION.value),
    ("execute", InferenceType.EXECUTION.value),
    ("model_operation", InferenceType.EXECUTION.value),
    ("tool_selection", InferenceType.TOOL_SELECTION.value),
    ("tool_result", InferenceType.TOOL_RESULT_ANALYSIS.value),
    ("tool_result_analysis", InferenceType.TOOL_RESULT_ANALYSIS.value),
    ("verify", InferenceType.VERIFICATION.value),
    ("verification", InferenceType.VERIFICATION.value),
    ("error_correction", InferenceType.ERROR_CORRECTION.value),
    ("repair", InferenceType.ERROR_CORRECTION.value),
    ("recover", InferenceType.RECOVERY.value),
    ("recovery", InferenceType.RECOVERY.value),
    ("research", InferenceType.RESEARCH.value),
    ("memory", InferenceType.MEMORY_RETRIEVAL.value),
    ("memory_retrieval", InferenceType.MEMORY_RETRIEVAL.value),
    ("summary", InferenceType.CONTEXT_SUMMARIZATION.value),
    ("summarization", InferenceType.CONTEXT_SUMMARIZATION.value),
    ("context_summarization", InferenceType.CONTEXT_SUMMARIZATION.value),
    ("compact", InferenceType.CONTEXT_SUMMARIZATION.value),
    ("final_answer", InferenceType.FINAL_RESPONSE.value),
    ("final", InferenceType.FINAL_RESPONSE.value),
    ("diagnostic", InferenceType.DIAGNOSTIC.value),
    ("calibrate", InferenceType.CALIBRATION.value),
    ("calibration", InferenceType.CALIBRATION.value),
    ("agent_query", InferenceType.MEMORY_RETRIEVAL.value),
    ("automation", InferenceType.EXECUTION.value),
    ("coisa_desconhecida", InferenceType.OTHER.value),
])
def test_classify_inference_type(purpose, expected):
    """classify_inference_type mapeia finalidades conhecidas e devolve 'other' para desconhecidas."""
    assert classify_inference_type(purpose) == expected


def test_classify_inference_type_none():
    """Sem finalidade, a classificação é None; string vazia também é ausente."""
    assert classify_inference_type(None) is None
    assert classify_inference_type("") is None


# ── Serviço de consumo de contexto ───────────────────────────────────

def test_service_overview():
    """overview agrega totais, média, janela, compactação e tokens economizados."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    _add_inference(session, run, task, purpose="plan", prompt=100, completion=50, window=8192)
    _add_inference(session, run, task, purpose="operation", prompt=200, completion=100, window=8192)
    session.flush()

    # Evento de compactação
    session.add(EventLogModel(
        project_id=project.id,
        run_id=run.id,
        task_id=task.id,
        event_type="context.compacted",
        payload_json={"before_tokens": 4000, "after_tokens": 2000, "purpose": "compact"},
    ))
    session.flush()

    view = service.overview(project_id=project.id, run_id=run.id)
    assert view["samples"] == 2
    assert view["inferences_total"] == 2
    assert view["input_tokens"]["value"] == 300
    assert view["output_tokens"]["value"] == 150
    assert view["total_tokens"]["value"] == 450
    assert view["compaction"]["events"] == 1
    assert view["compaction"]["tokens_removed_estimated"] == 2000
    assert view["tokens_saved_estimated"] == 2000
    assert view["avg_window_occupancy_pct"]["count"] == 2
    session.close()


def test_service_by_inference_type():
    """by_inference_type agrupa estatísticas por tipo de inferência."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    _add_inference(session, run, task, purpose="plan", prompt=100, completion=50)
    _add_inference(session, run, task, purpose="plan", prompt=200, completion=100)
    _add_inference(session, run, task, purpose="verify", prompt=50, completion=25)
    session.flush()

    result = service.by_inference_type(project_id=project.id, run_id=run.id)
    types = {g["type"] for g in result["groups"]}
    assert "planning" in types
    assert "verification" in types
    plan = [g for g in result["groups"] if g["type"] == "planning"][0]
    assert plan["count"] == 2
    assert plan["total_tokens"]["value"] == 450
    session.close()


def test_service_by_component():
    """by_component agrega componentes do contexto por categoria."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    components = [
        {"category": "system_instructions", "identification": "regras-globais", "tokens": 200, "required": True, "measurement": "estimate"},
        {"category": "objective", "identification": "objetivo", "tokens": 100, "required": True, "measurement": "estimate"},
        {"category": "tools", "identification": "ferramentas", "tokens": 300, "required": False, "measurement": "estimate", "optimization_potential": True},
    ]
    _add_inference(session, run, task, purpose="plan", components=components)
    _add_inference(session, run, task, purpose="operation", components=components)
    session.flush()

    result = service.by_component(project_id=project.id, run_id=run.id)
    cats = {g["category"]: g for g in result["groups"]}
    assert cats["system_instructions"]["tokens_total"] == 400
    assert cats["system_instructions"]["occurrences"] == 2
    assert cats["tools"]["optimization_potential"] == 2
    assert result["grand_total_tokens"] == 1200
    session.close()


def test_service_matrix():
    """matrix cruza tipo de inferência com componente do contexto."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    components_plan = [
        {"category": "system_instructions", "identification": "regras", "tokens": 200, "required": True},
    ]
    components_op = [
        {"category": "tools", "identification": "ferramentas", "tokens": 300, "required": False},
    ]
    _add_inference(session, run, task, purpose="plan", components=components_plan)
    _add_inference(session, run, task, purpose="operation", components=components_op)
    session.flush()

    result = service.matrix(project_id=project.id, run_id=run.id)
    types = result["types"]
    assert "planning" in types
    assert "execution" in types
    cats = result["categories"]
    assert "system_instructions" in cats
    assert "tools" in cats
    session.close()


def test_service_compare():
    """compare agrega por dimensão escolhida (modelo, agente, provedor…)."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    _add_inference(session, run, task, purpose="plan", provider="ollama", model="llama3.2", prompt=100, completion=50)
    _add_inference(session, run, task, purpose="operation", provider="ollama", model="llama3.2", prompt=200, completion=100)
    _add_inference(session, run, task, purpose="verify", provider="ollama", model="qwen3:8b", prompt=50, completion=25)
    session.flush()

    result = service.compare(project_id=project.id, run_id=run.id, group_by="model")
    models = {g["key"] for g in result["groups"]}
    assert "llama3.2" in models
    assert "qwen3:8b" in models
    llama = [g for g in result["groups"] if g["key"] == "llama3.2"][0]
    assert llama["count"] == 2
    assert llama["total_tokens"]["value"] == 450
    session.close()


def test_service_timeline():
    """timeline agrega consumo por período."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    now = datetime.now(UTC)
    _add_inference(session, run, task, purpose="plan", prompt=100, completion=50)
    session.flush()
    # Força a data da segunda inferência para o mesmo dia
    rec = session.scalar(
        select(InferenceRecordModel).order_by(InferenceRecordModel.created_at.desc()).limit(1)
    )
    rec.created_at = now
    session.flush()

    result = service.timeline(project_id=project.id, run_id=run.id, period="day")
    assert result["period"] == "day"
    assert len(result["series"]) >= 1
    assert result["series"][0]["inferences"] >= 1
    session.close()


def test_service_opportunities():
    """opportunities identifica padrões de consumo excessivo."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    # Muitas inferências com consumo elevado para gerar oportunidade
    for i in range(6):
        _add_inference(session, run, task, purpose="operation", prompt=1000 + i * 100, completion=500)
    session.flush()

    result = service.opportunities(project_id=project.id, run_id=run.id)
    assert "opportunities" in result
    assert "count" in result
    assert result["sample_inferences"] == 6
    session.close()


def test_service_get_inference_and_components():
    """get_inference e get_inference_components devolvem o detalhe de uma inferência."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    project, run, task = _create_run_task(session)

    components = [
        {"category": "system_instructions", "identification": "regras", "tokens": 200, "required": True, "measurement": "estimate"},
    ]
    rec = _add_inference(session, run, task, purpose="plan", components=components)
    session.flush()

    detail = service.get_inference(rec.id)
    assert detail is not None
    assert detail["purpose"] == "plan"
    assert detail["inference_type"] == "planning"
    assert detail["prompt_tokens"] == 100
    assert detail["context_window_size"] == 8192
    assert detail["tokenizer_version"] == TOKENIZER_VERSION
    assert detail["tokenizer_strategy"] == TOKENIZER_STRATEGY
    assert detail["components"] == components

    comps = service.get_inference_components(rec.id)
    assert comps is not None
    assert comps["total_components"] == 1
    assert comps["categories"][0]["category"] == "system_instructions"
    session.close()


def test_service_get_inference_not_found():
    """get_inference devolve None para id inexistente."""
    SessionLocal = setup_function()
    session = SessionLocal()
    service = ContextConsumptionService(session)
    assert service.get_inference(uuid.uuid4()) is None
    assert service.get_inference_components(uuid.uuid4()) is None
    session.close()


@pytest.mark.parametrize("purpose", ["operation", "plan", "final_answer", "agent_query"])
def test_every_inference_records_its_context_composition_with_tokens(purpose):
    """Regressão: `observed_chat` criava o snapshot mas não o passava ao registro, e os
    componentes saíam sem tokens — a barra de composição da inferência aparecia vazia."""
    import asyncio

    from agent.observability import observe
    from agent.providers.base import ChatCompletionRequest, ChatCompletionResponse, ChatMessage, ModelProfile
    from agent.providers.observed import observed_chat

    class _Fixed:
        name = "fake"
        supports_streaming = False

        async def chat(self, request):
            """Responde sempre o mesmo texto, sem rede."""
            return ChatCompletionResponse(content="ok")

    session = setup_function()()
    project, run, task = _create_run_task(session)
    session.commit()
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="system", content="regras " * 40), ChatMessage(role="user", content="faça x")],
        profile=ModelProfile(model_id="m"),
    )

    async def _call():
        with observe(session, run_id=run.id, project_id=project.id, task_id=task.id):
            await observed_chat(_Fixed(), request, purpose=purpose, stream=False)

    asyncio.run(_call())
    row = session.scalar(select(InferenceRecordModel))
    assert row.context_snapshot_id is not None
    components = row.components_included_json or []
    assert components and all((c.get("tokens") or 0) > 0 for c in components)
