"""
Arquivo: tests/test_task_state.py
Nome: test_task_state.py
Propósito: verificar o estado estruturado e consultável de tarefas (TaskStateService).
Responsabilidade: camada de testes — consulta de estado sem acionar o modelo, campos obrigatórios,
relações de dependência, operações filhas e evidências.
Dependências: agent.memory.state (TaskStateService, TaskState), agent.services (project_service,
task_service, contract_service), agent.persistence (database, models), agent.domain (enums, schemas),
pytest.
Observações: banco SQLite temporário por teste; o agent.db real nunca é tocado.
"""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import (
    ProjectCreate,
    TaskCreate,
    TaskDependencyCreate,
)
from agent.memory.state import TaskStateService
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    EvidenceModel,
    ExecutionRunModel,
    OperationAttemptModel,
)
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


def _make_root_task(session: Session, project_id) -> TaskService:
    ts = TaskService(session)
    root = ts.create_task(
        project_id,
        TaskCreate(
            title="Objetivo raiz",
            objective="Adicionar autenticação de dois fatores",
            kind=TaskKind.OBJECTIVE.value,
            acceptance_criteria="Login com código de uso único",
        ),
    )
    # cria um run para que OperationAttemptModel (run_id NOT NULL) possa ser gravado
    session.add(
        ExecutionRunModel(
            id=root.id,
            project_id=project_id,
            root_task_id=root.id,
            status="active",
        )
    )
    contract = ContractService(session)
    contract.upsert(
        root.id,
        acceptance={
            "criteria": [
                "Gerar código de 6 dígitos",
                "Validar código antes de entrar",
                "Testes de unidade passando",
            ]
        },
    )
    return ts, root


def test_task_state_returns_all_fields(session):
    """O estado estruturado devolve objetivo, requisitos, restrições, aceitação, dependências, operações, arquivos e orçamento."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts, root = _make_root_task(session, project.id)

    # cria duas operações filhas com dependência
    op1 = ts.create_task(
        project.id,
        TaskCreate(
            title="Inspecionar auth",
            objective="Ler o módulo de autenticação existente",
            parent_id=root.id,
            kind=TaskKind.OPERATION.value,
            metadata={"inspection": [{"path": "src/auth.py"}]},
        ),
    )
    op2 = ts.create_task(
        project.id,
        TaskCreate(
            title="Implementar 2FA",
            objective="Adicionar geração e validação de código",
            parent_id=root.id,
            kind=TaskKind.OPERATION.value,
            metadata={"model_operation": True, "attempts": 2},
        ),
    )
    ts.add_dependency(op2.id, TaskDependencyCreate(depends_on_task_id=op1.id))

    # grava uma evidência e uma tentativa
    session.add(
        EvidenceModel(
            task_id=op2.id,
            verifier="pytest",
            passed=True,
            summary="testes de 2FA passando",
        )
    )
    session.add(
        OperationAttemptModel(
            id=None,
            run_id=root.id,
            task_id=op2.id,
            kind="model",
            provider="ollama",
            request_json={"prompt_fp": "abc"},
            response_json={"content": "ok"},
            success=True,
        )
    )
    session.commit()

    state = TaskStateService(session).get_task_state(root.id)
    assert state is not None
    assert state.task_id == root.id
    assert state.project_id == project.id
    assert state.parent_id is None
    assert state.objective == "Adicionar autenticação de dois fatores"
    assert state.status == TaskStatus.PENDING.value
    assert state.kind == TaskKind.OBJECTIVE.value
    assert state.acceptance_criteria == ["Login com código de uso único"]
    assert state.budget["max_attempts"] == 8
    assert state.budget["depth"] == 0
    assert len(state.operations) == 2
    ops_by_title = {o.title: o for o in state.operations}
    assert ops_by_title["Inspecionar auth"].files == ["src/auth.py"]
    assert ops_by_title["Implementar 2FA"].depends_on == [op1.id]
    assert ops_by_title["Inspecionar auth"].depends_on == []
    assert state.verification_result is None


def test_task_state_nonexistent_returns_none(session):
    """Tarefa inexistente devolve None."""
    from uuid import uuid4

    assert TaskStateService(session).get_task_state(uuid4()) is None


def test_task_state_operational_summary(session):
    """O resumo operacional devolve o nível 1 da tarefa, pronto para o prompt."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    _ts, root = _make_root_task(session, project.id)
    session.commit()

    summary = TaskStateService(session).get_operational_summary(root.id)
    assert "Objetivo raiz" in summary or "Adicionar autenticação" in summary
    assert "Aceite:" in summary or "Estado:" in summary
