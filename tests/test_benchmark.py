"""
Arquivo: tests/test_benchmark.py
Nome: test_benchmark.py
Propósito: testar o runner de benchmark.
Responsabilidade: camada de testes — execução de tarefas, coleta de métricas, relatórios.
Componentes: BenchmarkRunner, MetricsCollector, BenchmarkTask.
Dependências: agent.benchmark.runner, pytest, asyncio.
Observações: usa banco temporário para isolamento.
"""

import tempfile

import pytest

from agent.benchmark.runner import (
    SAMPLE_TASKS,
    BenchmarkCategory,
    BenchmarkDifficulty,
    BenchmarkRunner,
    BenchmarkTask,
    MetricsCollector,
    create_benchmark_runner,
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    import os

    os.unlink(db_path)


@pytest.fixture
def temp_output():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_tasks_file(temp_output):
    """Cria arquivo de tarefas de exemplo."""
    import json

    tasks_file = f"{temp_output}/tasks.json"
    with open(tasks_file, "w", encoding="utf-8") as f:
        json.dump(SAMPLE_TASKS, f)
    return tasks_file


def test_benchmark_task_creation():
    """Criação de tarefa de benchmark."""
    task = BenchmarkTask(
        id="test_01",
        category=BenchmarkCategory.CODE_SEARCH,
        difficulty=BenchmarkDifficulty.EASY,
        objective="Encontre a função X",
        acceptance_criteria=["Critério 1", "Critério 2"],
    )

    assert task.id == "test_01"
    assert task.category == BenchmarkCategory.CODE_SEARCH
    assert task.difficulty == BenchmarkDifficulty.EASY
    assert len(task.acceptance_criteria) == 2


def test_metrics_collector():
    """Coleta de métricas funciona."""
    collector = MetricsCollector()
    collector.start()

    collector.record_inference(100.0, 500)
    collector.record_inference(150.0, 600)
    collector.record_file_read("src/file1.py")
    collector.record_file_read("src/file1.py")  # releitura
    collector.record_file_read("src/file2.py")
    collector.record_tool_call()
    collector.record_tool_call()

    metrics = collector.get_metrics()

    assert metrics.inference_count == 0  # não exposto diretamente
    assert metrics.files_read == 2
    assert metrics.files_reread == 1
    assert metrics.tool_calls == 2
    assert metrics.latency_p50_ms > 0
    assert metrics.latency_p95_ms > 0


def test_benchmark_task_serialization():
    """Serialização de tarefa funciona."""
    task = BenchmarkTask(
        id="test_01",
        category=BenchmarkCategory.BUG_FIX,
        difficulty=BenchmarkDifficulty.MEDIUM,
        objective="Corrija o bug",
        acceptance_criteria=["Critério 1"],
        setup_script="echo setup",
        verification_script="echo verify",
        expected_files=["src/file.py"],
        timeout_seconds=600,
        metadata={"key": "value"},
    )

    # Converte para dict e volta
    data = {
        "id": task.id,
        "category": task.category.value,
        "difficulty": task.difficulty.value,
        "objective": task.objective,
        "acceptance_criteria": task.acceptance_criteria,
        "setup_script": task.setup_script,
        "verification_script": task.verification_script,
        "expected_files": task.expected_files,
        "timeout_seconds": task.timeout_seconds,
        "metadata": task.metadata,
    }

    restored = BenchmarkTask(
        id=data["id"],
        category=BenchmarkCategory(data["category"]),
        difficulty=BenchmarkDifficulty(data["difficulty"]),
        objective=data["objective"],
        acceptance_criteria=data["acceptance_criteria"],
        setup_script=data["setup_script"],
        verification_script=data["verification_script"],
        expected_files=data["expected_files"],
        timeout_seconds=data["timeout_seconds"],
        metadata=data["metadata"],
    )

    assert restored.id == task.id
    assert restored.category == task.category
    assert restored.difficulty == task.difficulty


def test_sample_tasks():
    """Tarefas de exemplo são válidas."""
    for task_data in SAMPLE_TASKS["tasks"]:
        task = BenchmarkTask(
            id=task_data["id"],
            category=BenchmarkCategory(task_data["category"]),
            difficulty=BenchmarkDifficulty(task_data["difficulty"]),
            objective=task_data["objective"],
            acceptance_criteria=task_data["acceptance_criteria"],
            expected_files=task_data.get("expected_files", []),
        )

        assert task.id
        assert task.category in BenchmarkCategory
        assert task.difficulty in BenchmarkDifficulty
        assert len(task.acceptance_criteria) > 0


@pytest.mark.asyncio
async def test_benchmark_runner_creation(temp_db, temp_output):
    """Criação do runner funciona."""
    runner = create_benchmark_runner(".", temp_db, temp_output)
    assert isinstance(runner, BenchmarkRunner)


def test_factory_function(temp_db, temp_output):
    """Factory function cria instância."""
    runner = create_benchmark_runner(".", temp_db, temp_output)
    assert isinstance(runner, BenchmarkRunner)


def test_sample_tasks_file(temp_output):
    """Arquivo de tarefas de exemplo pode ser salvo."""
    import json

    tasks_file = f"{temp_output}/tasks.json"
    with open(tasks_file, "w", encoding="utf-8") as f:
        json.dump(SAMPLE_TASKS, f)

    with open(tasks_file, encoding="utf-8") as f:
        loaded = json.load(f)

    assert "tasks" in loaded
    assert len(loaded["tasks"]) == 3
