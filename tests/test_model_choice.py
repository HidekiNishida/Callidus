# tests/test_model_choice.py — o modelo escolhido é o que a inferência chama
from pathlib import Path

import httpx
import pytest

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.ollama import chat_body, inference_failure_text
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.util.json_parse import parse_json_object


def test_chat_uses_the_selected_model_without_hidden_reasoning():
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="escreva a página")],
        profile=ModelProfile(
            model_id="gpt-oss:20b",
            generation={"think": False, "num_predict": 4096},
        ),
    )
    body = chat_body(request)
    assert body["model"] == "gpt-oss:20b"
    assert body["think"] is False
    assert body["options"]["num_predict"] == 4096


def test_plain_model_does_not_send_think_flag():
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="llama3.2", generation={"think": False}),
    )
    assert "think" not in chat_body(request)


def test_timeout_without_message_is_named():
    assert inference_failure_text(httpx.ReadTimeout("")) == "tempo esgotado"


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    factory = build_session_factory(engine)
    opened = factory()
    yield opened
    opened.close()


def test_run_remembers_the_selected_model(session, tmp_path: Path):
    project = ProjectService(session).create_project(ProjectCreate(name="site", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Melhore o site", objective="Melhore o site"),
    )
    RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root.id,
            config={"provider": "ollama", "model_id": "gpt-oss:20b"},
        ),
    )
    session.commit()
    assert TaskService(session).get_task(root.id).metadata_json["model_id"] == "gpt-oss:20b"


def test_json_after_thinking_block_is_kept():
    data, err = parse_json_object('<think>longo</think>\n{"path":"index.html","content":"<p>ok</p>"}')
    assert err is None
    assert data["path"] == "index.html"
