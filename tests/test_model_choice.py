"""
Arquivo: tests/test_model_choice.py
Nome: test_model_choice.py
Propósito: Verificar a escolha e o uso do modelo selecionado.
Responsabilidade: camada de testes — corpo da requisição ao Ollama, modelo gravado na tarefa e leitura do JSON depois de um bloco de raciocínio.
Componentes: corpo da requisição com o modelo escolhido, sinalizador think, texto de timeout, modelo registrado na tarefa e JSON após bloco de pensamento.
Dependências: agent.providers.ollama, agent.services.run_service e agent.util.json_parse.
Observações: banco temporário por teste; a chamada ao modelo não é feita de verdade.
"""

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
    """O corpo da requisição usa o modelo escolhido, desliga o think e leva o limite de tokens."""
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
    """Um modelo sem raciocínio oculto não recebe o sinalizador think."""
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="llama3.2", generation={"think": False}),
    )
    assert "think" not in chat_body(request)


def test_timeout_without_message_is_named():
    """Um timeout sem mensagem vira um texto de falha legível."""
    assert inference_failure_text(httpx.ReadTimeout("")) == "tempo esgotado"


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    factory = build_session_factory(engine)
    opened = factory()
    yield opened
    opened.close()


def test_run_remembers_the_selected_model(session, tmp_path: Path):
    """O run grava o modelo escolhido nos metadados da tarefa."""
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
    """O JSON que vem depois de um bloco de raciocínio é lido sem perda."""
    data, err = parse_json_object('<think>longo</think>\n{"path":"index.html","content":"<p>ok</p>"}')
    assert err is None
    assert data["path"] == "index.html"
