"""
Arquivo: tests/test_ucg_execution.py
Nome: test_ucg_execution.py
Propósito: Verificar o Execution Graph — DAG de operações e dependências, detecção de
ciclos bloqueantes, tarefas prontas para execução, checkpoints de retomada e reutilização
de resultados.
Responsabilidade: camada de testes — integração do Execution Graph com as tabelas
existentes (`tasks`, `task_dependencies`, `execution_runs`).
Componentes: ExecutionNode, ExecutionEdge, CycleError, ExecutionGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.execution,
agent.persistence.database, agent.services.project_service, agent.services.task_service.
Observações: banco e arquivos temporários em tmp_path; não grava dados de negócio.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.knowledge.ucg.execution import (
    CycleError,
    ExecutionEdge,
    ExecutionGraphService,
    ExecutionNode,
)
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import TaskDependencyModel, TaskModel
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


@pytest.fixture
def project(session, tmp_path: Path):
    """Cria um projeto."""
    return ProjectService(session).create_project(
        ProjectCreate(name="execution", root_path=str(tmp_path / "root"))
    )


def _create_task(session, project, title, objective, status="PENDING", parent_id=None):
    """Cria uma tarefa e devolve o modelo."""
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title=title,
            objective=objective,
            kind="operation",
            parent_id=parent_id,
        ),
    )
    if status:
        task.status = status
        session.flush()
    return task


def _add_dependency(session, task_id, depends_on_task_id):
    """Adiciona uma dependência entre duas tarefas."""
    dep = TaskDependencyModel(
        task_id=task_id,
        depends_on_task_id=depends_on_task_id,
    )
    session.add(dep)
    session.flush()


def test_build_execution_graph_simple(session, project):
    """Grafo simples: tarefa A depende de B; B está pronta, A não."""
    proj = project
    b = _create_task(session, proj, "B", "tarefa B", status="COMPLETED")
    a = _create_task(session, proj, "A", "tarefa A depende de B")
    _add_dependency(session, a.id, b.id)

    service = ExecutionGraphService(session, proj)
    nodes, edges = service.build_execution_graph()

    assert len(nodes) == 2
    assert len(edges) == 1
    node_a = next(n for n in nodes if n.task_id == str(a.id))
    node_b = next(n for n in nodes if n.task_id == str(b.id))
    assert node_b.completed is True
    assert node_a.ready is True  # dependência B concluída
    assert node_a.depends_on == [str(b.id)]


def test_ready_tasks(session, project):
    """ready_tasks devolve apenas tarefas com dependências concluídas."""
    proj = project
    b = _create_task(session, proj, "B", "tarefa B", status="COMPLETED")
    c = _create_task(session, proj, "C", "tarefa C sem dependências", status="PENDING")
    a = _create_task(session, proj, "A", "tarefa A depende de B e C")
    _add_dependency(session, a.id, b.id)
    _add_dependency(session, a.id, c.id)

    service = ExecutionGraphService(session, proj)
    ready = service.ready_tasks()
    ready_ids = {n.task_id for n in ready}
    assert str(c.id) in ready_ids
    assert str(a.id) not in ready_ids  # depende de C que não está concluída


def test_next_task(session, project):
    """next_task devolve a próxima tarefa pronta de menor profundidade."""
    proj = project
    b = _create_task(session, proj, "B", "tarefa B", status="COMPLETED")
    a = _create_task(session, proj, "A", "tarefa A depende de B", parent_id=b.id)
    _add_dependency(session, a.id, b.id)

    service = ExecutionGraphService(session, proj)
    nxt = service.next_task()
    assert nxt is not None
    assert nxt.task_id == str(a.id)


def test_has_cycle_false(session, project):
    """has_cycle retorna False quando não há ciclo."""
    proj = project
    b = _create_task(session, proj, "B", "tarefa B", status="COMPLETED")
    a = _create_task(session, proj, "A", "tarefa A depende de B")
    _add_dependency(session, a.id, b.id)

    service = ExecutionGraphService(session, proj)
    assert service.has_cycle() is False


def test_has_cycle_true(session, project):
    """has_cycle retorna True e build_execution_graph levanta CycleError quando há ciclo."""
    proj = project
    a = _create_task(session, proj, "A", "tarefa A")
    b = _create_task(session, proj, "B", "tarefa B")
    _add_dependency(session, a.id, b.id)  # A depende de B
    _add_dependency(session, b.id, a.id)  # B depende de A (ciclo)

    service = ExecutionGraphService(session, proj)
    assert service.has_cycle() is True
    with pytest.raises(CycleError):
        service.build_execution_graph()


def test_checkpoint_and_resume(session, project):
    """checkpoint grava estado e resume_checkpoint recupera o último."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")

    service = ExecutionGraphService(session, proj)
    cp = service.checkpoint(
        run_id="run-1",
        task_id=str(task.id),
        state={"step": 1, "note": "primeiro checkpoint"},
    )
    assert cp["run_id"] == "run-1"
    assert cp["state"]["step"] == 1

    recovered = service.resume_checkpoint(task_id=str(task.id), run_id="run-1")
    assert recovered == {"step": 1, "note": "primeiro checkpoint"}


def test_resume_checkpoint_without_run_id(session, project):
    """resume_checkpoint sem run_id devolve o último checkpoint."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T")

    service = ExecutionGraphService(session, proj)
    service.checkpoint(run_id="run-1", task_id=str(task.id), state={"step": 1})
    service.checkpoint(run_id="run-2", task_id=str(task.id), state={"step": 2})

    recovered = service.resume_checkpoint(task_id=str(task.id))
    assert recovered == {"step": 2}


def test_reusable_result_true(session, project):
    """reusable_result retorna True quando há resultado concluído com fingerprint igual."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T", status="COMPLETED")
    task.consolidated_result_json = {"fingerprint": "abc123", "verified": True}
    session.flush()

    service = ExecutionGraphService(session, proj)
    assert service.reusable_result(task_id=str(task.id), artifact_fingerprint="abc123") is True


def test_reusable_result_false(session, project):
    """reusable_result retorna False quando fingerprint não confere ou tarefa não concluída."""
    proj = project
    task = _create_task(session, proj, "T", "tarefa T", status="PENDING")

    service = ExecutionGraphService(session, proj)
    assert service.reusable_result(task_id=str(task.id), artifact_fingerprint="abc123") is False


def test_execution_node_to_graph_node_ref():
    """ExecutionNode converte para GraphNodeRef do domínio task."""
    node = ExecutionNode(
        task_id="task-1",
        title="Tarefa A",
        objective="Objetivo A",
        status="PENDING",
        kind="operation",
        depth=1,
        ready=True,
        completed=False,
        fingerprint="fp-123",
    )
    ref = node.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.TASK
    assert ref.domain == GraphDomain.TASK
    assert ref.source_system == "task"
    assert ref.source_id == "task-1"
    assert ref.metadata["ready"] is True
    assert ref.metadata["fingerprint"] == "fp-123"


def test_execution_edge_to_graph_edge_ref():
    """ExecutionEdge.to_graph_edge_ref cria aresta DEPENDS_ON."""
    source = GraphNodeRef(
        id=1, domain=GraphDomain.TASK, kind=GraphNodeKind.TASK,
        source_system="task", source_id="task-a",
    )
    target = GraphNodeRef(
        id=2, domain=GraphDomain.TASK, kind=GraphNodeKind.TASK,
        source_system="task", source_id="task-b",
    )
    edge = ExecutionEdge(task_id="task-a", depends_on_task_id="task-b", relation="DEPENDS_ON")
    ger = edge.to_graph_edge_ref(source, target)
    assert ger.relation == GraphRelationKind.DEPENDS_ON
    assert ger.source.source_id == "task-a"
    assert ger.target.source_id == "task-b"
