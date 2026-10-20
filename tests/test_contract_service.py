"""
Arquivo: tests/test_contract_service.py
Nome: test_contract_service.py
Propósito: Verificar a exigência de contrato definido antes de executar uma tarefa.
Responsabilidade: camada de testes — bloqueio de tarefa sem contrato e liberação após a definição.
Componentes: validação para execução sem contrato e com contrato definido.
Dependências: agent.services.contract_service, agent.services.task_service e agent.services.project_service.
Observações: banco temporário por teste.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_contract_required_blocks_without_definition(session, tmp_path: Path):
    """Tarefa que exige contrato é bloqueada sem definição e liberada após definir o contrato."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="c", root_path=str(tmp_path))
    )
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective="integrar", metadata={"requires_contract": True})
    )
    ok, errs = ContractService(session).validate_for_run(task.id)
    assert not ok
    assert errs
    ContractService(session).upsert(task.id, outputs={"type": "AuthResult"})
    ok2, _ = ContractService(session).validate_for_run(task.id)
    assert ok2
