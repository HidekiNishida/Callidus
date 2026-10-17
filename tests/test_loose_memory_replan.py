# tests/test_loose_memory_replan.py
from pathlib import Path

from agent.config import Settings
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.enums import MemoryKind
from agent.domain.schemas import ConversationCreate, MemoryCreate, ProjectCreate, TaskCreate, TaskStatusUpdate
from agent.domain.enums import TaskStatus
from agent.memory.store import choose_memory_index, structure_memory
from agent.orchestrator.replan import replan_parent
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


def test_memory_index_chooses_without_the_full_text():
    outline = structure_memory(
        "O banco fica em SQLite.\n\nA interface da calculadora usa Tkinter e quatro operações."
    )
    assert outline["facts"]
    assert "topics" in outline
    chosen = choose_memory_index(
        [
            {
                "id": "a",
                "title": "Banco",
                "summary": "SQLite local",
                "facts": ["O banco fica em SQLite."],
                "topics": ["sqlite"],
                "scope": "conversation",
            },
            {
                "id": "b",
                "title": "Interface",
                "summary": "Tkinter",
                "facts": ["A interface usa Tkinter."],
                "topics": ["tkinter"],
                "scope": "conversation",
            },
        ],
        "montar a interface Tkinter",
    )
    assert [item["id"] for item in chosen] == ["b"]


def test_builder_reads_only_the_chosen_memory(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path))
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    conversation = ConversationService(session).create_conversation(project.id, ConversationCreate(title="Chat"))
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(title="UI", objective="montar a interface Tkinter", conversation_id=conversation.id),
    )
    ProjectService(session).add_memory(
        project.id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Banco",
            content="Segredo só do banco: ZEBU-91. O banco fica em SQLite.",
            conversation_id=conversation.id,
        ),
    )
    ProjectService(session).add_memory(
        project.id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Interface",
            content="A interface usa Tkinter com quatro botões.",
            conversation_id=conversation.id,
        ),
    )
    session.commit()
    budget, snap = OperationContextBuilder(session).build_for_task(
        project_id=project.id,
        root_path=str(tmp_path),
        task=task,
        profile=ModelProfile(model_id="mock", context_limit=4000, input_budget=2000, output_reserve=200),
    )
    prompt = "\n".join(message.content for message in budget.messages)
    assert "Tkinter" in prompt
    assert "ZEBU-91" not in prompt
    assert any(note.startswith("memória:") for note in snap.strategy_notes_json or [])
    session.close()


def test_loose_conversation_moves_its_memory_and_can_be_removed(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path))
    session = build_session_factory(engine)()
    projects = ProjectService(session)
    home = projects.create_project(ProjectCreate(name="Casa", root_path=str(tmp_path / "casa")))
    other = projects.create_project(ProjectCreate(name="Outro", root_path=str(tmp_path / "outro")))
    conversations = ConversationService(session)
    loose = conversations.create_loose(ConversationCreate(title="Solta"))
    assert loose.project_id != home.id
    assert all(item.id != loose.project_id for item in projects.list_projects())
    moved = conversations.move_conversation(loose.id, home.id)
    task = TaskService(session).create_task(
        home.id,
        TaskCreate(title="Fazer", objective="criar tela", conversation_id=moved.id),
    )
    projects.add_memory(
        home.id,
        MemoryCreate(kind=MemoryKind.CANONICAL, title="Regra da casa", content="Não apagar data."),
    )
    projects.add_memory(
        home.id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Desta conversa",
            content="Usar Tkinter aqui.",
            conversation_id=moved.id,
            task_id=task.id,
        ),
    )
    session.commit()
    conversations.move_conversation(moved.id, other.id)
    session.commit()
    home_titles = {item.title for item in projects.list_memory(home.id)}
    other_titles = {item.title for item in projects.list_memory(other.id)}
    assert "Regra da casa" in home_titles
    assert "Desta conversa" not in home_titles
    assert "Desta conversa" in other_titles
    assert TaskService(session).get_task(task.id).project_id == other.id
    conversations.move_conversation(moved.id, None)
    session.commit()
    assert conversations.list_loose()[0].id == moved.id
    assert "Desta conversa" not in {item.title for item in projects.list_memory(other.id)}
    conversations.delete_conversation(moved.id)
    session.commit()
    assert conversations.list_loose() == []
    assert "Regra da casa" in {item.title for item in projects.list_memory(home.id)}
    session.close()


def test_replan_keeps_done_work_and_replaces_the_tail(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path))
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    parent = tasks.create_task(project.id, TaskCreate(title="Fazer tela", objective="Criar a tela", kind="objective"))
    tasks.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
    done = tasks.create_task(
        project.id,
        TaskCreate(title="Criar arquivo", objective="escrever", parent_id=parent.id, kind="operation"),
    )
    stopped = tasks.create_task(
        project.id,
        TaskCreate(title="Rodar testes", objective="pytest", parent_id=parent.id, kind="operation"),
    )
    pending = tasks.create_task(
        project.id,
        TaskCreate(title="Entregar", objective="fechar", parent_id=parent.id, kind="operation"),
    )
    done.status = "COMPLETED"
    stopped.status = "BLOCKED"
    stopped.consolidated_result_json = {"result": {"error": "teste falhou"}}
    session.commit()
    first = replan_parent(session, parent)
    assert first["action"] == "replanned"
    assert pending.status == "CANCELLED"
    assert done.status == "COMPLETED"
    titles = [item.title for item in tasks.list_tasks(project.id)]
    assert "Ver o que ainda falta" in titles
    assert "Seguir com o plano corrigido" in titles
    assert replan_parent(session, parent) is None
    session.close()
