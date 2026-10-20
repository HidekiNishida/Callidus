"""
Arquivo: tests/test_contract_impact.py
Nome: test_contract_impact.py
Propósito: Verificar o impacto da mudança de contrato sobre as tarefas dependentes.
Responsabilidade: camada de testes — identificação das tarefas afetadas quando o contrato do produtor muda.
Componentes: contrato do produtor que encontra a tarefa dependente.
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


def test_contract_change_finds_dependent_tasks(session, tmp_path: Path):
    """A mudança de contrato do produtor lista a tarefa que depende dele."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    ts = TaskService(session)
    producer = ts.create_task(
        project.id, TaskCreate(title="Auth", objective="Definir serviço auth")
    )
    consumer = ts.create_task(
        project.id,
        TaskCreate(title="Login UI", objective="Integrar com auth.py na interface"),
    )
    cs = ContractService(session)
    out = cs.upsert_with_impact(
        producer.id,
        outputs={"type": "AuthResult", "files": ["auth.py"]},
    )
    assert str(consumer.id) in out["impacted_task_ids"]
