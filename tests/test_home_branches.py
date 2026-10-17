# tests/test_home_branches.py
import asyncio
from pathlib import Path

from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import MemoryKind
from agent.domain.schemas import ConversationCreate, MemoryCreate, ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import MemoryRecordModel
from agent.services.branches import memory_visible
from agent.services.conversation_service import ConversationService
from agent.services.inbox import effective_root, user_home
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.builtins import register_all
from agent.tools.registry import ToolContext, ToolRegistry


def _session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path))
    return build_session_factory(engine)()


def test_project_without_folder_uses_the_user_home(tmp_path: Path):
    session = _session(tmp_path)
    project = ProjectService(session).create_project(ProjectCreate(name="Casa", root_path=""))
    assert project.path_origin == "home"
    assert project.root_path == user_home()
    assert any(item.id == project.id for item in ProjectService(session).list_projects())
    session.close()


def test_loose_chat_and_override_use_home_until_a_folder_is_chosen(tmp_path: Path):
    session = _session(tmp_path)
    conversation = ConversationService(session).create_loose(ConversationCreate(title="Solta"))
    project = ProjectService(session).get_project(conversation.project_id)
    assert effective_root(project, conversation) == user_home()
    assert not any(item.id == project.id for item in ProjectService(session).list_projects())
    updated = ConversationService(session).set_root(conversation.id, str(tmp_path))
    assert effective_root(project, updated) == str(tmp_path.resolve())
    session.close()


def test_rename_keeps_a_custom_title(tmp_path: Path):
    session = _session(tmp_path)
    conversation = ConversationService(session).create_loose(ConversationCreate(title="Nome original"))
    renamed = ConversationService(session).rename(conversation.id, "Nome novo")
    assert renamed.title == "Nome novo"
    session.close()


def test_editing_a_message_forks_and_memory_follows_the_branch(tmp_path: Path):
    session = _session(tmp_path)
    service = ConversationService(session)
    conversation = service.create_loose(ConversationCreate(title="Chat"))
    tasks = TaskService(session)
    first = tasks.create_task(
        conversation.project_id,
        TaskCreate(title="antes", objective="primeira mensagem", conversation_id=conversation.id),
    )
    edited = tasks.create_task(
        conversation.project_id,
        TaskCreate(title="meio", objective="mensagem original", conversation_id=conversation.id),
    )
    ProjectService(session).add_memory(
        conversation.project_id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Antes",
            content="FATO-ANTES vale nos dois ramos.",
            conversation_id=conversation.id,
        ),
    )
    session.commit()
    forked = service.fork_message(conversation.id, edited.id, "mensagem editada")
    parent_id = edited.branch_id
    ProjectService(session).add_memory(
        conversation.project_id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Depois",
            content="FATO-DEPOIS fica só no ramo antigo.",
            conversation_id=conversation.id,
            branch_id=parent_id,
        ),
    )
    session.commit()
    old_tasks = service.tasks_for_branch(conversation.id, parent_id)
    new_tasks = service.tasks_for_branch(conversation.id, forked.branch_id)
    old_ids = {task.id for task in old_tasks if task.parent_id is None}
    new_ids = {task.id for task in new_tasks if task.parent_id is None}
    assert first.id in old_ids and edited.id in old_ids and forked.id not in old_ids
    assert first.id in new_ids and edited.id not in new_ids and forked.id in new_ids
    assert forked.objective == "mensagem editada"
    memories = {
        item.title: item
        for item in session.scalars(
            select(MemoryRecordModel).where(MemoryRecordModel.conversation_id == conversation.id)
        ).all()
    }
    catalog = {item.id: item for item in service.branches_of(conversation.id)}
    assert memory_visible(
        memory_branch_id=memories["Antes"].branch_id,
        memory_created_at=memories["Antes"].created_at,
        conversation_id=conversation.id,
        task_branch_id=forked.branch_id,
        branches=catalog,
    )
    assert not memory_visible(
        memory_branch_id=memories["Depois"].branch_id,
        memory_created_at=memories["Depois"].created_at,
        conversation_id=conversation.id,
        task_branch_id=forked.branch_id,
        branches=catalog,
    )
    session.close()


def test_system_info_reports_the_home_directory(tmp_path: Path):
    registry = ToolRegistry()
    register_all(registry)
    result = asyncio.run(
        registry.execute("sysinfo", ToolContext(project_root=str(tmp_path), run_id="r", task_id="t"), {})
    )
    assert result["success"] is True
    assert result["home"] == user_home()
    assert result["workspace"] == str(tmp_path)
