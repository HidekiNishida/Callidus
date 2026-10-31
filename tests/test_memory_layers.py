"""
Arquivo: tests/test_memory_layers.py
Nome: test_memory_layers.py
Propósito: verificar a recuperação de memória por camada (MemoryLayers).
Responsabilidade: camada de testes — camada imediata (nível 1 da tarefa), memória da tarefa,
memória do projeto (escopo de projeto, sem conversa) e arquivo histórico; seleção seletiva sem
carregar todas as camadas em todas as inferências.
Dependências: agent.memory.layers (MemoryLayers), agent.services.project_service, agent.persistence
(database, models), agent.domain.enums, agent.domain.schemas, pytest.
Observações: banco SQLite temporário por teste; o agent.db real nunca é tocado.
"""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.enums import MemoryKind
from agent.domain.schemas import ConversationCreate, MemoryCreate, ProjectCreate
from agent.memory.layers import MemoryLayer, MemoryLayers
from agent.persistence.database import build_session_factory, init_db
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


def _add_memory(session, project_id, kind, title, content, *, conversation_id=None, task_id=None):
    return ProjectService(session).add_memory(
        project_id,
        MemoryCreate(
            kind=kind,
            title=title,
            content=content,
            task_id=task_id,
            conversation_id=conversation_id,
            source_refs=[f"task:{task_id}" if task_id else "manual"],
        ),
    )


def _make_conversation(session, project_id):
    cs = ConversationService(session)
    return cs.create_conversation(project_id, ConversationCreate(title="conv", locale="pt"))


def test_layer_object_has_purpose_and_cost():
    """Cada camada expõe nome, propósito e custo de recuperação."""
    immediate = MemoryLayer(MemoryLayer.IMMEDIATE)
    assert immediate.name == "immediate"
    assert "operação atual" in immediate.purpose
    assert immediate.cost == "baixo"

    archive = MemoryLayer(MemoryLayer.ARCHIVE)
    assert archive.name == "archive"
    assert archive.cost == "alto"


def test_layer_unknown_raises_keyerror():
    """Camada desconhecida levanta KeyError."""
    layers = MemoryLayers.__new__(MemoryLayers)
    with pytest.raises(KeyError):
        layers.layer("inexistente")


def test_immediate_layer_returns_operational_only(session):
    """A camada imediata devolve apenas memória operacional (nível 1) da tarefa."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ProjectService.__new__(ProjectService)
    # criar tarefa diretamente para ter task_id
    from agent.domain.enums import TaskKind
    from agent.domain.schemas import TaskCreate
    from agent.services.task_service import TaskService

    ts = TaskService(session)
    t = ts.create_task(
        project.id,
        TaskCreate(title="t", objective="o", kind=TaskKind.OPERATION.value),
    )
    session.commit()

    _add_memory(session, project.id, MemoryKind.OPERATIONAL.value, "Estado", "estado da tarefa", task_id=t.id)
    _add_memory(session, project.id, MemoryKind.TASK_DETAIL.value, "Detalhe", "detalhe longo", task_id=t.id)
    _add_memory(session, project.id, MemoryKind.ARTIFACT.value, "Artefato", "ref:snap:1", task_id=t.id)
    session.commit()

    layers = MemoryLayers(session)
    imediate = layers.immediate(t.id)
    assert len(imediate) == 1
    assert imediate[0].kind == MemoryKind.OPERATIONAL.value
    assert imediate[0].title == "Estado"


def test_task_layer_includes_detail_and_artifact(session):
    """A camada de tarefa agrega operacional, detalhe e artefato da tarefa."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    from agent.domain.enums import TaskKind
    from agent.domain.schemas import TaskCreate
    from agent.services.task_service import TaskService

    ts = TaskService(session)
    t = ts.create_task(
        project.id,
        TaskCreate(title="t", objective="o", kind=TaskKind.OPERATION.value),
    )
    session.commit()

    _add_memory(session, project.id, MemoryKind.OPERATIONAL.value, "Estado", "estado", task_id=t.id)
    _add_memory(session, project.id, MemoryKind.TASK_DETAIL.value, "Detalhe", "detalhe da tarefa", task_id=t.id)
    _add_memory(session, project.id, MemoryKind.ARTIFACT.value, "Artefato", "ref:snap:1", task_id=t.id)
    # memória de outra tarefa não entra
    t2 = ts.create_task(project.id, TaskCreate(title="t2", objective="o2", kind=TaskKind.OPERATION.value))
    _add_memory(session, project.id, MemoryKind.TASK_DETAIL.value, "Outro", "outra tarefa", task_id=t2.id)
    session.commit()

    layers = MemoryLayers(session)
    task_mem = layers.task(project_id=project.id, task_id=t.id)
    titles = {m.title for m in task_mem}
    assert titles == {"Estado", "Detalhe", "Artefato"}
    assert "Outro" not in titles


def test_project_layer_only_project_scope(session):
    """A camada de projeto devolve apenas memórias com conversation_id nulo (escopo de projeto)."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    session.commit()

    _add_memory(
        session, project.id, MemoryKind.CANONICAL.value, "Canon", "decisão de arquitetura", conversation_id=None
    )
    conv = _make_conversation(session, project.id)
    _add_memory(session, project.id, MemoryKind.CONTEXTUAL.value, "Contexto", "conversa x", conversation_id=conv.id)
    session.commit()

    layers = MemoryLayers(session)
    proj = layers.project(project_id=project.id)
    titles = {m.title for m in proj}
    assert "Canon" in titles
    assert "Contexto" not in titles


def test_archive_layer_only_execution_kind(session):
    """O arquivo histórico devolve apenas registros de execução (ou o kind pedido)."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    session.commit()

    _add_memory(session, project.id, MemoryKind.EXECUTION.value, "Exec", "registro de execução")
    _add_memory(session, project.id, MemoryKind.CANONICAL.value, "Canon", "não é arquivo")
    session.commit()

    layers = MemoryLayers(session)
    arch = layers.archive(project_id=project.id)
    titles = {m.title for m in arch}
    assert "Exec" in titles
    assert "Canon" not in titles


def test_summary_for_prompt_truncates_to_budget(session):
    """O resumo para o prompt respeita o orçamento de caracteres da camada."""
    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    from agent.domain.enums import TaskKind
    from agent.domain.schemas import TaskCreate
    from agent.services.task_service import TaskService

    ts = TaskService(session)
    t = ts.create_task(
        project.id,
        TaskCreate(title="t", objective="o", kind=TaskKind.OPERATION.value),
    )
    session.commit()

    layers = MemoryLayers(session)
    resumo = layers.summary_for_prompt(t, layer_budget=20)
    assert len(resumo) <= 20
