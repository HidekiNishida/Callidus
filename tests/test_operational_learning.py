"""
Arquivo: tests/test_operational_learning.py
Nome: test_operational_learning.py
Propósito: testar o aprendizado operacional.
Responsabilidade: camada de testes — registro, recuperação, reutilização e estatísticas.
Componentes: ExperienceStore, StrategyRetriever, OperationalLearning.
Dependências: agent.learning.operational, pytest.
Observações: usa banco temporário para isolamento.
"""

import tempfile

import pytest

from agent.learning.operational import (
    ExperienceStore,
    OperationalLearning,
    StrategyQuery,
    StrategyRecord,
    StrategyRetriever,
    create_operational_learning,
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    import os

    os.unlink(db_path)


@pytest.fixture
def store(temp_db):
    return ExperienceStore(temp_db)


@pytest.fixture
def learning(temp_db):
    return create_operational_learning(temp_db)


def test_experience_store_save_and_query(store):
    """Salva e recupera registros."""
    record = StrategyRecord(
        id="test-1",
        task_type="bug",
        objective_summary="Fix login bug",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools"],
        strategy={"plan": ["inspect", "fix", "test"]},
        model_provider="ollama",
        model_id="llama3",
        tools_used=["read_file", "write_file"],
        tokens_estimated=2000,
        tokens_consumed=1800,
        duration_ms=5000,
        attempts=1,
        verification_result="validated",
        success=True,
        failure_cause=None,
        recovery_strategy=None,
        created_at="2026-01-01T00:00:00Z",
        project_version="1.0",
        confidence=0.9,
    )

    store.save(record)

    query = StrategyQuery(task_type="bug", min_confidence=0.5, limit=10)
    results = store.query(query)

    assert len(results) == 1
    assert results[0].id == "test-1"
    assert results[0].task_type == "bug"
    assert results[0].success is True


def test_experience_store_query_filters(store):
    """Filtros de consulta funcionam."""
    # Salva registros de diferentes tipos
    for i, task_type in enumerate(["bug", "feature", "refactor"]):
        record = StrategyRecord(
            id=f"test-{i}",
            task_type=task_type,
            objective_summary=f"Task {i}",
            complexity="moderate",
            risk="medium",
            required_capabilities=["tools"],
            strategy={},
            model_provider="ollama",
            model_id="llama3",
            tools_used=[],
            tokens_estimated=1000,
            tokens_consumed=1000,
            duration_ms=1000,
            attempts=1,
            verification_result="validated",
            success=True,
            failure_cause=None,
            recovery_strategy=None,
            created_at="2026-01-01T00:00:00Z",
            project_version="1.0",
            confidence=0.8,
        )
        store.save(record)

    # Filtra por task_type
    query = StrategyQuery(task_type="bug", min_confidence=0.5, limit=10)
    results = store.query(query)
    assert len(results) == 1
    assert results[0].task_type == "bug"

    # Filtra por confidence
    query = StrategyQuery(min_confidence=0.9, limit=10)
    results = store.query(query)
    assert len(results) == 0


def test_experience_store_statistics(store):
    """Estatísticas são calculadas corretamente."""
    for i in range(3):
        record = StrategyRecord(
            id=f"test-{i}",
            task_type="bug" if i < 2 else "feature",
            objective_summary=f"Task {i}",
            complexity="moderate",
            risk="medium",
            required_capabilities=["tools"],
            strategy={},
            model_provider="ollama",
            model_id="llama3",
            tools_used=[],
            tokens_estimated=1000,
            tokens_consumed=1000,
            duration_ms=1000,
            attempts=1,
            verification_result="validated",
            success=i < 2,  # 2 sucessos, 1 falha
            failure_cause=None,
            recovery_strategy=None,
            created_at="2026-01-01T00:00:00Z",
            project_version="1.0",
            confidence=0.8,
        )
        store.save(record)

    stats = store.get_statistics()
    assert stats["total_records"] == 3
    assert stats["successful_records"] == 2
    assert stats["success_rate"] == pytest.approx(2 / 3)
    assert "bug" in stats["by_task_type"]
    assert stats["by_task_type"]["bug"]["total"] == 2
    assert stats["by_task_type"]["bug"]["success"] == 2


def test_strategy_retriever(store):
    """Recuperador encontra estratégias relevantes."""
    retriever = StrategyRetriever(store)

    # Salva registro de bug fix
    record = StrategyRecord(
        id="test-1",
        task_type="bug",
        objective_summary="Fix authentication login error",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools", "tool_loop"],
        strategy={"steps": ["inspect auth", "fix token", "test login"]},
        model_provider="ollama",
        model_id="llama3",
        tools_used=["read_file", "write_file", "run_test"],
        tokens_estimated=3000,
        tokens_consumed=2800,
        duration_ms=10000,
        attempts=1,
        verification_result="completed",
        success=True,
        failure_cause=None,
        recovery_strategy=None,
        created_at="2026-01-01T00:00:00Z",
        project_version="1.0",
        confidence=0.9,
    )
    store.save(record)

    # Busca estratégia similar
    results = retriever.find_relevant(
        task_type="bug",
        objective="Fix authentication login failure",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools"],
    )

    assert len(results) == 1
    assert results[0].id == "test-1"


def test_operational_learning_record(learning):
    """Registro de execução funciona."""
    record = learning.record_execution(
        task_type="feature",
        objective="Add user profile page",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools", "tool_loop"],
        strategy={"plan": ["create component", "add route", "test"]},
        model_provider="ollama",
        model_id="llama3",
        tools_used=["read_file", "write_file", "run_test"],
        tokens_estimated=4000,
        tokens_consumed=3800,
        duration_ms=15000,
        attempts=1,
        verification_result="completed",
        success=True,
        project_version="1.0",
    )

    assert record.id is not None
    assert record.task_type == "feature"
    assert record.success is True
    assert record.confidence > 0.5


def test_operational_learning_confidence_calculation(learning):
    """Cálculo de confiança considera tentativas e verificação."""
    # Sucesso na primeira tentativa com verificação completa
    record1 = learning.record_execution(
        task_type="bug",
        objective="Fix bug",
        complexity="simple",
        risk="low",
        required_capabilities=[],
        strategy={},
        model_provider="ollama",
        model_id="llama3",
        tools_used=[],
        tokens_estimated=1000,
        tokens_consumed=1000,
        duration_ms=5000,
        attempts=1,
        verification_result="completed",
        success=True,
        project_version="1.0",
    )

    # Falha após múltiplas tentativas
    record2 = learning.record_execution(
        task_type="bug",
        objective="Fix bug",
        complexity="simple",
        risk="low",
        required_capabilities=[],
        strategy={},
        model_provider="ollama",
        model_id="llama3",
        tools_used=[],
        tokens_estimated=1000,
        tokens_consumed=1000,
        duration_ms=5000,
        attempts=3,
        verification_result="failed",
        success=False,
        project_version="1.0",
    )

    assert record1.confidence > record2.confidence
    assert record1.confidence > 0.7
    assert record2.confidence < 0.3


def test_operational_learning_recommendations(learning):
    """Recomendações baseadas em experiências passadas."""
    # Registra experiência bem-sucedida
    learning.record_execution(
        task_type="bug",
        objective="Fix authentication token validation",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools", "tool_loop"],
        strategy={"plan": ["inspect auth module", "fix token validation", "add tests"]},
        model_provider="ollama",
        model_id="llama3",
        tools_used=["read_file", "write_file", "run_test"],
        tokens_estimated=5000,
        tokens_consumed=4800,
        duration_ms=20000,
        attempts=1,
        verification_result="completed",
        success=True,
        project_version="1.0",
    )

    # Pede recomendações para tarefa similar
    recommendations = learning.get_recommendations(
        task_type="bug",
        objective="Fix authentication login error",
        complexity="moderate",
        risk="medium",
        required_capabilities=["tools"],
    )

    assert len(recommendations) > 0
    rec = recommendations[0]
    assert "strategy" in rec
    assert "model_provider" in rec
    assert "confidence" in rec
    assert rec["confidence"] > 0.4


def test_operational_learning_statistics(learning):
    """Estatísticas do aprendizado."""
    # Registra alguns resultados
    for i in range(5):
        learning.record_execution(
            task_type="bug" if i < 3 else "feature",
            objective=f"Task {i}",
            complexity="moderate",
            risk="medium",
            required_capabilities=["tools"],
            strategy={},
            model_provider="ollama",
            model_id="llama3",
            tools_used=[],
            tokens_estimated=1000,
            tokens_consumed=1000,
            duration_ms=5000,
            attempts=1,
            verification_result="validated",
            success=i < 4,  # 4 sucessos, 1 falha
            project_version="1.0",
        )

    stats = learning.get_statistics()
    assert stats["total_records"] == 5
    assert stats["successful_records"] == 4
    assert stats["success_rate"] == pytest.approx(0.8)
    assert "bug" in stats["by_task_type"]
    assert stats["by_task_type"]["bug"]["total"] == 3


def test_factory_function(temp_db):
    """Factory function cria instância."""
    learning = create_operational_learning(temp_db)
    assert isinstance(learning, OperationalLearning)
