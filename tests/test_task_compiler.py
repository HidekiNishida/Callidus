"""
Arquivo: tests/test_task_compiler.py
Nome: test_task_compiler.py
Propósito: verificar o compilador de tarefas (TaskCompiler).
Responsabilidade: camada de testes — compilação de intenção em TaskIR, detecção de componentes
afetados, operações pequenas, critérios de aceitação, orçamento e persistência.
Dependências: agent.memory.state (TaskStateService), agent.orchestrator.task_compiler (TaskCompiler),
agent.persistence (database, models), agent.services.project_service, agent.domain.schemas, pytest.
Observações: banco SQLite temporário por teste; o agent.db real nunca é tocado.
"""

from pathlib import Path

import pytest

from agent.domain.schemas import ProjectCreate
from agent.memory.state import TaskStateService
from agent.orchestrator.task_compiler import TaskCompiler
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ProjectModel
from agent.services.project_service import ProjectService


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = __import__("agent.config", fromlist=["Settings"]).Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


def _make_project(session, tmp_path: Path) -> ProjectModel:
    ps = ProjectService(session)
    return ps.create_project(ProjectCreate(name="demo", root_path=str(tmp_path), description="test"))


def test_compiler_produces_task_ir(session, tmp_path: Path):
    """O compilador devolve TaskIR com objetivo, operações, componentes afetados e orçamento."""
    project = _make_project(session, tmp_path)
    compiler = TaskCompiler(session, project)
    result = compiler.compile("Adicionar autenticação de dois fatores ao sistema de login")
    assert result is not None
    assert result.source == "compiler"
    assert result.ir.objective == "Adicionar autenticação de dois fatores ao sistema de login"
    assert result.ir.task_id is not None
    assert len(result.ir.operations) >= 3  # inspecionar, analisar impacto, implementar, verificar, finalizar
    op_ids = {op["id"] for op in result.ir.operations}
    assert "inspect" in op_ids
    assert "implement" in op_ids
    assert "verify" in op_ids
    assert "final_answer" in op_ids
    # Orçamento definido.
    assert result.ir.context_budget is not None
    assert result.ir.context_budget.max_input_tokens > 0
    assert result.ir.context_budget.max_output_tokens > 0
    # Restrições definidas.
    assert len(result.ir.constraints) >= 1


def test_compiler_persists_task(session, tmp_path: Path):
    """O IR compilado é persistido como tarefa no banco."""
    project = _make_project(session, tmp_path)
    compiler = TaskCompiler(session, project)
    result = compiler.compile("Criar endpoint de saúde")
    assert result.task_id is not None
    # A tarefa pode ser recuperada via TaskStateService.
    state = TaskStateService(session).get_task_state(result.task_id)
    assert state is not None
    assert state.objective == "Criar endpoint de saúde"
    assert state.project_id == project.id


def test_compiler_operations_have_dependencies_and_acceptance(session, tmp_path: Path):
    """Cada operação tem dependências explícitas e critérios de aceitação."""
    project = _make_project(session, tmp_path)
    compiler = TaskCompiler(session, project)
    result = compiler.compile("Refatorar módulo de pagamento")
    for op in result.ir.operations:
        assert op["id"]
        assert op["title"]
        assert op["objective"]
        assert op["kind"]
        assert "depends_on" in op
        assert "acceptance" in op
        assert "budget" in op
        assert op["budget"]["max_input_tokens"] > 0
        assert op["budget"]["max_output_tokens"] > 0


def test_compiler_acceptance_criteria_are_verifiable(session, tmp_path: Path):
    """Critérios de aceitação são derivados do objetivo e requisitos."""
    project = _make_project(session, tmp_path)
    compiler = TaskCompiler(session, project)
    requirements = [{"id": "R1", "description": "Gerar código de 6 dígitos"}]
    result = compiler.compile("Adicionar autenticação de dois fatores", requirements=requirements)
    assert any("6 dígitos" in c for c in result.ir.acceptance_criteria)
    assert len(result.ir.acceptance_criteria) >= 1


def test_compiler_complexity_score_bounded(session, tmp_path: Path):
    """A pontuação de complexidade fica entre 0 e 100."""
    project = _make_project(session, tmp_path)
    compiler = TaskCompiler(session, project)
    result = compiler.compile("Uma alteração pequena e simples")
    score = result.ir.complexity.get("score", 0)
    assert 0 <= score <= 100
