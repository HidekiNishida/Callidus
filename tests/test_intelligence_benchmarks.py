#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_benchmarks.py
Nome: test_intelligence_benchmarks.py
Propósito: verificar o engine de benchmarking (cenários, execuções, resultados, comparação, pontuação).
Responsabilidade: camada de testes — comportamento unitário do BenchmarkEngine.
Componentes: BenchmarkEngine, BenchmarkScenario, BenchmarkExecution, BenchmarkResult, BenchmarkScore.
Dependências: agent.intelligence.benchmarks, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from agent.intelligence.benchmarks import (
    BenchmarkEngine,
    BenchmarkScenario,
    BenchmarkExecution,
    BenchmarkResult,
    BenchmarkScore,
    SCENARIO_CATEGORIES,
    SCORE_DIMENSIONS,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    BenchmarkExecutionModel,
    BenchmarkResultModel,
    BenchmarkScenarioModel,
)


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def test_scenario_categories_and_dimensions():
    """SCENARIO_CATEGORIES e SCORE_DIMENSIONS definem as categorias e dimensões de pontuação."""
    assert "planejamento" in SCENARIO_CATEGORIES
    assert "decomposição" in SCENARIO_CATEGORIES
    assert "execução" in SCORE_DIMENSIONS
    assert "eficiência" in SCORE_DIMENSIONS
    assert "conclusão" in SCORE_DIMENSIONS


def test_benchmark_scenario_dataclass():
    """BenchmarkScenario armazena todos os campos de um cenário versionado."""
    sc = BenchmarkScenario(
        id="bench-01",
        version=2,
        name="Cenário de teste",
        description="Descrição",
        category="planejamento",
        difficulty="intermediário",
        prompt="Faça algo",
        tools_allowed=["read_file", "write_file"],
        token_budget=8000,
        time_limit_sec=300,
        acceptance_criteria=["critério 1", "critério 2"],
        validation_tests=["teste 1"],
        expected_result={"sucesso": True},
        is_active=True,
    )
    assert sc.id == "bench-01"
    assert sc.version == 2
    assert sc.name == "Cenário de teste"
    assert sc.difficulty == "intermediário"
    assert sc.tools_allowed == ["read_file", "write_file"]
    assert sc.token_budget == 8000
    assert sc.is_active is True


def test_benchmark_score_dataclass():
    """BenchmarkScore armazena pontuação por dimensão com critérios e evidências."""
    score = BenchmarkScore(
        dimension="execução",
        score=85.5,
        criteria="Taxa de sucesso de chamadas ao modelo.",
        evidence={"error_rate": 0.1, "calls": 10},
        subjective=False,
    )
    d = score.to_dict()
    assert d["dimension"] == "execução"
    assert d["score"] == 85.5
    assert d["criteria"] == "Taxa de sucesso de chamadas ao modelo."
    assert d["evidence"] == {"error_rate": 0.1, "calls": 10}
    assert d["subjective"] is False


def test_benchmark_result_dataclass():
    """BenchmarkResult armazena resultado completo com pontuações."""
    result = BenchmarkResult(
        id="result-01",
        execution_id="exec-01",
        scenario_id="scen-01",
        task_completed=True,
        requirements_satisfied=3,
        requirements_total=3,
        total_tokens=1500,
        inference_count=10,
        total_time_seconds=45.5,
        latency_p50_ms=120.0,
        latency_p95_ms=300.0,
        tool_calls=25,
        recovery_count=2,
        scores=[BenchmarkScore(dimension="eficiência", score=90.0, criteria="c", evidence={})],
        metrics={"tokens": {"total": 1500}},
        evidence={"scenario": "teste"},
    )
    d = result.to_dict()
    assert d["task_completed"] is True
    assert d["total_tokens"] == 1500
    assert d["scores"][0]["dimension"] == "eficiência"
    assert d["metrics"]["tokens"]["total"] == 1500


def test_benchmark_engine_create_and_list_scenarios():
    """O engine cria e lista cenários de benchmark."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    scenario = BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Planejamento",
        description="Avalia planejamento",
        category="planejamento",
        difficulty="fácil",
        prompt="Planeje uma tarefa",
    )
    created = engine.create_scenario(scenario)
    assert created.id == "bench-01"
    assert created.version == 1

    scenarios = engine.list_scenarios()
    assert len(scenarios) == 1
    assert scenarios[0].id == "bench-01"
    assert scenarios[0].is_active is True
    session.close()


def test_benchmark_engine_get_scenario():
    """get_scenario devolve o cenário pelo id e versão."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="V1",
        description="v1",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))
    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=2,
        name="V2",
        description="v2",
        category="planejamento",
        difficulty="difícil",
        prompt="p2",
    ))

    v1 = engine.get_scenario("bench-01", version=1)
    assert v1.version == 1
    assert v1.name == "V1"

    v2 = engine.get_scenario("bench-01", version=2)
    assert v2.version == 2
    assert v2.name == "V2"

    latest = engine.get_scenario("bench-01")
    assert latest.version == 2
    session.close()


def test_benchmark_engine_create_and_complete_execution():
    """O engine cria execuções e as marca como concluídas."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Teste",
        description="d",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))

    run_id = uuid.uuid4()
    exec_ = engine.create_execution(
        scenario_id="bench-01",
        provider="ollama",
        model_id="llama3.2",
        run_id=run_id,
    )
    assert exec_.status == "pending"
    assert exec_.provider == "ollama"
    assert exec_.run_id == run_id

    completed = engine.complete_execution(exec_.id, status="completed", duration_sec=45.5)
    assert completed.status == "completed"
    assert completed.duration_sec == 45.5
    session.close()


def test_benchmark_engine_save_and_get_result():
    """O engine salva e devolve resultados de benchmark."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Teste",
        description="d",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))
    exec_ = engine.create_execution(scenario_id="bench-01", provider="ollama", model_id="llama3.2")
    execution_id = exec_.id

    result = BenchmarkResult(
        id="result-01",
        execution_id=execution_id,
        scenario_id="bench-01",
        task_completed=True,
        requirements_satisfied=2,
        requirements_total=2,
        total_tokens=1000,
        inference_count=5,
        total_time_seconds=30.0,
        latency_p50_ms=100.0,
        latency_p95_ms=200.0,
        tool_calls=10,
        recovery_count=1,
        scores=[
            BenchmarkScore(dimension="execução", score=90.0, criteria="c", evidence={}),
            BenchmarkScore(dimension="eficiência", score=80.0, criteria="c", evidence={}),
        ],
        metrics={"tokens": {"total": 1000}},
        evidence={"scenario": "teste"},
    )
    engine.save_result(execution_id, result)

    fetched = engine.get_result(execution_id)
    assert fetched is not None
    assert fetched.task_completed is True
    assert fetched.total_tokens == 1000
    assert len(fetched.scores) == 2
    assert fetched.scores[0].dimension == "execução"
    assert fetched.scores[0].score == 90.0
    session.close()


def test_benchmark_engine_compare():
    """compare compara execuções de um mesmo cenário."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Teste",
        description="d",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))
    e1 = engine.create_execution(scenario_id="bench-01", provider="ollama", model_id="m1")
    e2 = engine.create_execution(scenario_id="bench-01", provider="mock", model_id="m2")

    comparison = engine.compare(scenario_id="bench-01", execution_ids=[e1.id, e2.id])
    assert comparison["count"] == 2
    assert len(comparison["executions"]) == 2
    providers = {e["provider"] for e in comparison["executions"]}
    assert providers == {"ollama", "mock"}
    session.close()


def test_benchmark_engine_export_results():
    """export_results devolve resultados serializáveis."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Teste",
        description="d",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))
    exec_ = engine.create_execution(scenario_id="bench-01", provider="ollama", model_id="m1")

    results = engine.export_results()
    assert len(results) == 1
    assert results[0]["execution_id"] == exec_.id
    session.close()


def test_benchmark_engine_run_scenario_async():
    """run_scenario executa um cenário de forma assíncrona e salva o resultado."""
    SessionLocal = setup_function()
    session = SessionLocal()
    engine = BenchmarkEngine(session)

    engine.create_scenario(BenchmarkScenario(
        id="bench-01",
        version=1,
        name="Teste",
        description="d",
        category="planejamento",
        difficulty="fácil",
        prompt="p",
    ))

    run_id = uuid.uuid4()
    result = asyncio.run(engine.run_scenario(
        scenario_id="bench-01",
        provider="ollama",
        model_id="llama3.2",
        run_id=run_id,
    ))
    assert result.scenario_id == "bench-01"
    assert result.total_time_seconds >= 0
    assert len(result.scores) == len(SCORE_DIMENSIONS)
    assert result.metrics is not None
    assert result.evidence is not None
    session.close()
