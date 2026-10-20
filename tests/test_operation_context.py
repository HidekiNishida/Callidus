"""
Arquivo: tests/test_operation_context.py
Nome: test_operation_context.py
Propósito: verificar que o contexto de operação é montado e persistido para uma tarefa.
Responsabilidade: camada de testes — comportamento do construtor de contexto de operação (orçamento e instantâneo).
Componentes: montagem do contexto de uma tarefa, cálculo do orçamento de tokens e persistência do instantâneo.
Dependências: agent.context.operation_builder.OperationContextBuilder, agent.services (project, task), agent.persistence.database, pytest.
Observações: banco SQLite temporário por teste (tmp_path) e nenhum serviço externo é usado.
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_context_snapshot_persisted(session, tmp_path: Path):
    """O contexto da tarefa é montado com orçamento positivo de tokens e o instantâneo é persistido com seus componentes."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="ctx", root_path=str(tmp_path))
    )
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective="ajustar função calc_add")
    )
    builder = OperationContextBuilder(session)
    budget, snap = builder.build_for_task(
        project_id=project.id,
        root_path=project.root_path,
        task=task,
        profile=ModelProfile(model_id="mock", context_limit=4096),
    )
    assert budget.estimated_tokens > 0
    assert snap.id is not None
    assert snap.components_json
