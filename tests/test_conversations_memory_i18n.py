# tests/test_conversations_memory_i18n.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent.api import deps
from agent.config import Settings
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.enums import MemoryKind
from agent.domain.schemas import ConversationCreate, MemoryCreate, ProjectCreate, TaskCreate
from agent.i18n.locale import detect_language, translate
from agent.memory.store import decompose_for_use, extract_memory_request, summarize_text
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import ConversationModel, TaskModel
from agent.providers.base import ModelProfile
from agent.services.conversation_service import ConversationService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolContext, build_default_registry


def test_detects_and_translates_task_titles():
    assert detect_language("Crie uma calculadora com interface") == "pt"
    assert detect_language("Create unit tests for calculator logic") == "en"
    assert detect_language("Crear una interfaz para el archivo") == "es"
    assert translate("Run unit tests", "pt") == "Executar testes unitários"
    assert translate("Integrate logic into main.py", "pt") == "Integrar lógica em main.py"
    assert translate("Add Tkinter GUI to main.py", "pt") == "Adicionar Tkinter GUI em main.py"
    assert translate("Pensando em como dividir «Run unit tests».", "pt") == (
        "Pensando em como dividir «Executar testes unitários»."
    )
    assert translate("Dividindo o trabalho", "en") == "Splitting the work"


def test_memory_keeps_full_text_and_splits_on_use():
    content = (
        "O banco fica em SQLite e não deve ir para o git.\n\n"
        "A calculadora precisa de quatro operações e testes unitários na pasta tests."
    )
    summary = summarize_text(content, limit=80)
    assert len(summary) < len(content)
    assert content.startswith("O banco")
    pieces = decompose_for_use(content, "escrever testes unitários da calculadora")
    assert pieces
    assert any("testes unitários" in piece for piece in pieces)
    assert "SQLite" not in pieces[0]
    scope, fact = extract_memory_request("Lembre que a pasta do projeto é Documents/Projetos")
    assert scope == "project"
    assert "Documents/Projetos" in fact


def test_conversation_memory_is_scoped(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path))
    session: Session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    conversations = ConversationService(session)
    first = conversations.create_conversation(project.id, ConversationCreate(title="Nova conversa"))
    second = conversations.create_conversation(project.id, ConversationCreate(title="Outra"))
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Run unit tests", objective="Crie os testes", conversation_id=first.id),
    )
    child = tasks.create_task(
        project.id,
        TaskCreate(title="Filha", objective="detalhe", parent_id=root.id, kind="operation"),
    )
    assert child.conversation_id == first.id
    ProjectService(session).add_memory(
        project.id,
        MemoryCreate(
            kind=MemoryKind.CONTEXTUAL,
            title="Decisão da conversa",
            content="Usar Tkinter nesta conversa. " + ("detalhe " * 80),
            conversation_id=first.id,
            task_id=root.id,
        ),
    )
    ProjectService(session).add_memory(
        project.id,
        MemoryCreate(
            kind=MemoryKind.CANONICAL,
            title="Regra do projeto",
            content="Nunca apagar a pasta data.",
        ),
    )
    session.commit()
    stored = ProjectService(session).list_memory(project.id)
    long_one = next(item for item in stored if item.title == "Decisão da conversa")
    assert long_one.summary
    assert len(long_one.summary) < len(long_one.content)
    profile = ModelProfile(model_id="mock", context_limit=4000, input_budget=2000, output_reserve=200)
    other = tasks.create_task(
        project.id,
        TaskCreate(title="Outra", objective="listar arquivos", conversation_id=second.id),
    )
    budget, _snap = OperationContextBuilder(session).build_for_task(
        project_id=project.id,
        root_path=str(tmp_path),
        task=other,
        profile=profile,
    )
    prompt = "\n".join(message.content for message in budget.messages)
    assert "Regra do projeto" in prompt
    assert "Decisão da conversa" not in prompt
    session.close()


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as api:
        yield api
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def test_api_conversations_folder_and_memory(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "projetos").mkdir(exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = client.get("/fs/browse")
    assert home.status_code == 200
    assert home.json()["entries"]
    blocked = client.get("/fs/browse", params={"path": "/etc"})
    assert blocked.status_code == 400

    created = client.post("/projects", json={"name": "Demo", "root_path": str(tmp_path)})
    project_id = created.json()["id"]
    conversation = client.post(f"/projects/{project_id}/conversations", json={})
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    task = client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Lembrar",
            "objective": "Lembre que o tema da interface é escuro",
            "conversation_id": conversation_id,
        },
    )
    assert task.status_code == 200
    assert task.json()["conversation_id"] == conversation_id
    listed = client.get(f"/projects/{project_id}/conversations")
    assert listed.json()[0]["title"] == "Lembrar"
    memories = client.get(f"/projects/{project_id}/memory")
    assert any(item["summary"] and item["content"] for item in memories.json())


@pytest.mark.asyncio
async def test_remember_tool_uses_saver():
    seen = {}

    def saver(args):
        seen.update(args)
        return {"success": True, "summary": "ok"}

    registry = build_default_registry()
    out = await registry.execute(
        "remember",
        ToolContext(project_root=".", memory_saver=saver),
        {"content": "usar pytest", "scope": "project"},
    )
    assert out["success"] is True
    assert seen["content"] == "usar pytest"


def test_deleting_a_conversation_removes_the_whole_task_tree(tmp_path: Path):
    """Conversa com árvore de tarefas (raiz → filha → neta) e run: apaga sem violar a chave
    estrangeira (a remoção precisa ir das folhas para a raiz)."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    conversation = ConversationService(session).create_conversation(project.id, ConversationCreate(title="c"))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="root", objective="o", conversation_id=conversation.id)
    )
    child = TaskService(session).create_task(
        project.id, TaskCreate(title="child", objective="o", conversation_id=conversation.id, parent_id=root.id)
    )
    TaskService(session).create_task(
        project.id, TaskCreate(title="grand", objective="o", conversation_id=conversation.id, parent_id=child.id)
    )
    session.commit()

    ConversationService(session).delete_conversation(conversation.id)
    session.commit()

    assert session.get(ConversationModel, conversation.id) is None
    assert session.query(TaskModel).filter(TaskModel.conversation_id == conversation.id).count() == 0
