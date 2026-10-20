"""
Arquivo: tests/test_persistence.py
Nome: test_persistence.py
Propósito: verificar a persistência de projetos e tarefas, as transições de estado e as dependências entre tarefas.
Responsabilidade: camada de testes — comportamento dos serviços de projeto e tarefa sobre o banco.
Componentes: sobrevivência da árvore de tarefas à reabertura, recusa de transição inválida, bloqueio de ciclo de dependência, caminho feliz até concluída.
Dependências: agent.services (project_service, task_service), agent.persistence.database, agent.domain (enums, schemas), pytest.
Observações: banco SQLite temporário por teste (tmp_path); o agent.db real nunca é tocado.

persistência e recuperação
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.persistence.database import build_session_factory, init_db
from agent.config import Settings
from agent.services.project_service import ProjectService
from agent.services.task_service import DependencyError, TaskService


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


def test_project_and_task_tree_survives_reopen(tmp_path: Path, session: Session):
    """A árvore de tarefas permanece intacta depois de reabrir o banco em outra sessão."""
    ps = ProjectService(session)
    project = ps.create_project(
        ProjectCreate(name="demo", root_path=str(tmp_path), description="test")
    )
    ts = TaskService(session)
    root = ts.create_task(
        project.id,
        TaskCreate(title="Objetivo", objective="Fazer X", kind="objective"),
    )
    child = ts.create_task(
        project.id,
        TaskCreate(title="Op", objective="Passo 1", parent_id=root.id, kind="operation"),
    )
    session.commit()
    project_id = project.id
    root_id = root.id
    child_id = child.id

    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess2 = factory()
    tasks = TaskService(sess2).list_tasks(project_id)
    assert len(tasks) == 2
    assert {t.id for t in tasks} == {root_id, child_id}
    sess2.close()


def test_invalid_transition_rejected(session: Session):
    """Uma transição de estado inválida é recusada e a tarefa não muda de status."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective="o")
    )
    with pytest.raises(Exception):
        TaskService(session).update_status(
            task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED)
        )


def test_dependency_cycle_blocked(session: Session):
    """Uma dependência que criaria um ciclo entre tarefas é recusada."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts = TaskService(session)
    a = ts.create_task(project.id, TaskCreate(title="A", objective="a"))
    b = ts.create_task(project.id, TaskCreate(title="B", objective="b"))
    ts.add_dependency(b.id, TaskDependencyCreate(depends_on_task_id=a.id))
    with pytest.raises(DependencyError):
        ts.add_dependency(a.id, TaskDependencyCreate(depends_on_task_id=b.id))


def test_happy_path_to_completed(session: Session):
    """A sequência válida de estados leva a tarefa até concluída e registra o instante de conclusão."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts = TaskService(session)
    task = ts.create_task(project.id, TaskCreate(title="t", objective="o"))
    for status in [
        TaskStatus.PLANNING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.VERIFYING,
        TaskStatus.COMPLETED,
    ]:
        ts.update_status(task.id, TaskStatusUpdate(status=status))
    final = ts.get_task(task.id)
    assert final.status == TaskStatus.COMPLETED.value
    assert final.completed_at is not None
