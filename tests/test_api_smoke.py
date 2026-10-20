"""
Arquivo: tests/test_api_smoke.py
Nome: test_api_smoke.py
Propósito: Verificar, de forma ampla, que as rotas da API respondem sem erro interno.
Responsabilidade: camada de testes — fumaça das rotas de leitura, ciclo de projeto e conversa, execuções, provedores, payloads inválidos e filesystem.
Componentes: rotas somente-leitura, ciclo de projeto e conversa, rotas de execução, configuração de provedor, payloads inválidos, criação de pasta, retomada de run, remoto do projeto e identificadores inexistentes.
Dependências: agent.api.deps, agent.config.Settings e TestClient.
Observações: banco temporário em tmp_path e worker de fundo desativado; a criação de pasta usa um diretório temporário na home, removido ao fim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Cliente de teste da API com banco temporário e worker de fundo desligado."""
    monkeypatch.delenv("PROVIDERS_CONFIG_PATH", raising=False)
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        """Devolve as configurações do teste, com banco temporário e worker de fundo desligado."""
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def test_read_only_routes_answer(client: TestClient):
    """Nenhuma rota somente-leitura responde com erro de servidor."""
    for path in (
        "/health",
        "/providers",
        "/providers/config",
        "/tools",
        "/mcp/servers",
        "/config/ui-defaults",
        "/projects",
        "/conversations",
        "/fs/browse",
    ):
        response = client.get(path)
        assert response.status_code < 500, f"{path} → {response.status_code}"


def test_project_and_conversation_lifecycle(client: TestClient, tmp_path: Path):
    """Criar, renomear projeto e conversa, criar tarefa e consultá-la responde dentro do esperado."""
    project = client.post("/projects", json={"name": "projeto", "root_path": str(tmp_path)})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]

    renamed = client.patch(f"/projects/{project_id}", json={"name": "projeto novo"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "projeto novo"

    conversation = client.post(f"/projects/{project_id}/conversations", json={"title": "conversa"})
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    task = client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "tarefa",
            "objective": "faça alguma coisa",
            "conversation_id": conversation_id,
            "metadata": {"attachments": [{"kind": "text", "name": "nota.txt", "content": "oi"}]},
        },
    )
    assert task.status_code == 200, task.text
    task_id = task.json()["id"]

    for path in (
        f"/projects/{project_id}/tasks",
        f"/conversations/{conversation_id}/tasks",
        f"/tasks/{task_id}",
        f"/tasks/{task_id}/attempts",
        f"/tasks/{task_id}/evidences",
        f"/tasks/{task_id}/contract",
        f"/tasks/{task_id}/context-snapshots",
        f"/projects/{project_id}/runs",
        f"/projects/{project_id}/overview",
        f"/projects/{project_id}/live",
        f"/projects/{project_id}/metrics",
        f"/projects/{project_id}/git-diff",
        f"/projects/{project_id}/knowledge/search?q=qualquer",
        f"/projects/{project_id}/knowledge/neighbors?ref=qualquer",
    ):
        response = client.get(path)
        assert response.status_code < 500, f"{path} → {response.status_code} {response.text[:200]}"

    renamed_conversation = client.patch(f"/conversations/{conversation_id}", json={"title": "renomeada"})
    assert renamed_conversation.status_code == 200

    removed = client.delete(f"/conversations/{conversation_id}")
    assert removed.status_code == 200, removed.text

    removed_project = client.delete(f"/projects/{project_id}")
    assert removed_project.status_code == 200, removed_project.text
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_run_routes_answer(client: TestClient, tmp_path: Path):
    """As rotas de execução (passo, pausa, retomada, autônomo e métricas) respondem sem erro interno."""
    project = client.post("/projects", json={"name": "projeto", "root_path": str(tmp_path)}).json()
    conversation = client.post(f"/projects/{project['id']}/conversations", json={"title": "c"}).json()
    task = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "t", "objective": "o", "conversation_id": conversation["id"]},
    ).json()
    run = client.post(
        f"/projects/{project['id']}/runs",
        json={"root_task_id": task["id"], "config": {"provider": "mock"}},
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]

    for path in (
        f"/runs/{run_id}/step",
        f"/runs/{run_id}/pause",
        f"/runs/{run_id}/resume",
        f"/runs/{run_id}/autonomous/enable",
        f"/runs/{run_id}/autonomous/disable",
        f"/runs/{run_id}/metrics",
    ):
        response = client.post(path)
        assert response.status_code < 500, f"{path} → {response.status_code} {response.text[:200]}"

    cancel = client.post(f"/runs/{run_id}/cancel")
    assert cancel.status_code < 500


def test_provider_configuration_routes_answer(client: TestClient, monkeypatch):
    """A configuração de provedor é salva e consultada, e um servidor inexistente devolve erro limpo."""
    monkeypatch.setenv("CHAVE_DE_TESTE", "chave-de-teste-123456")
    saved = client.put(
        "/providers/config",
        json={
            "default_provider": "meu",
            "providers": {
                "meu": {
                    "type": "openai_compatible",
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "m",
                    "api_key_env": "CHAVE_DE_TESTE",
                }
            },
        },
    )
    assert saved.status_code == 200, saved.text

    config = client.get("/providers/config")
    assert config.status_code == 200
    assert "meu" in config.json()["providers"]

    # Servidor inexistente: erro de conexão limpo (503), nunca 500 com traceback.
    models = client.get("/providers/meu/models")
    assert models.status_code == 503, models.text
    assert models.json()["detail"]

    tested = client.post("/providers/meu/test")
    assert tested.status_code == 200
    assert tested.json()["ok"] is False
    assert tested.json()["detail"]

    removed = client.delete("/providers/config/meu")
    assert removed.status_code == 200, removed.text


def test_invalid_payloads_return_4xx_not_500(client: TestClient):
    """Payloads inválidos são recusados com 4xx, nunca com erro de servidor."""
    cases = [
        ("post", "/projects", {"name": ""}),
        ("post", "/projects", {"name": "x", "root_path": 123}),
        ("put", "/providers/config", {"providers": {"x": {"type": "inexistente"}}}),
        ("put", "/providers/config", {"providers": {"x": {"type": "ollama", "base_url": "ftp://x"}}}),
        ("post", "/conversations", {"title": 5}),
    ]
    for method, path, payload in cases:
        response = getattr(client, method)(path, json=payload)
        assert 400 <= response.status_code < 500, f"{method} {path} → {response.status_code}"


def test_criar_pasta_dentro_do_alcance(client: TestClient, tmp_path: Path):
    """A interface cria pastas pelo seletor (POST /fs/mkdir) — dentro da pasta do usuário."""
    import shutil

    base = Path.home() / ".callidus-teste-pastas"
    base.mkdir(parents=True, exist_ok=True)
    try:
        response = client.post("/fs/mkdir", json={"path": str(base), "name": "pasta-nova"})
        assert response.status_code == 200, response.text
        assert (base / "pasta-nova").is_dir()
        assert response.json()["created"].endswith("pasta-nova")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_criar_pasta_com_nome_invalido(client: TestClient, tmp_path: Path):
    """Nome de pasta vazio, com barras ou ponto duplo é recusado com 400."""
    for name in ("", "  ", "a/b", ".."):
        response = client.post("/fs/mkdir", json={"path": str(tmp_path), "name": name})
        assert response.status_code == 400, f"{name!r} → {response.status_code}"


def test_criar_pasta_fora_do_alcance(client: TestClient):
    """Criar pasta fora do alcance permitido é recusado com 400."""
    response = client.post("/fs/mkdir", json={"path": "/etc", "name": "x"})
    assert response.status_code == 400


def test_run_pausado_pode_ser_retomado(client: TestClient, tmp_path: Path):
    """O caminho de retomada (usado pelo botão “Retomar” do chat) responde."""
    project = client.post("/projects", json={"name": "p", "root_path": str(tmp_path)}).json()
    conversation = client.post(f"/projects/{project['id']}/conversations", json={"title": "c"}).json()
    task = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "t", "objective": "o", "conversation_id": conversation["id"]},
    ).json()
    run = client.post(
        f"/projects/{project['id']}/runs",
        json={"root_task_id": task["id"], "config": {"provider": "mock"}},
    ).json()
    paused = client.post(f"/runs/{run['id']}/pause")
    assert paused.status_code < 500
    resumed = client.post(f"/runs/{run['id']}/resume")
    assert resumed.status_code < 500, resumed.text


def test_remote_do_projeto_e_configuravel(client: TestClient, tmp_path: Path):
    """O remoto do projeto é salvo, consultado e removido pela API."""
    project = client.post("/projects", json={"name": "p", "root_path": str(tmp_path)}).json()
    saved = client.put(
        f"/projects/{project['id']}/remote",
        json={"host": "servidor.exemplo", "port": 2222, "user": "deploy", "root": "/srv/app"},
    )
    assert saved.status_code == 200, saved.text
    assert client.get(f"/projects/{project['id']}/remote").json()["remote"]["host"] == "servidor.exemplo"
    assert client.delete(f"/projects/{project['id']}/remote").status_code == 200
    assert client.get(f"/projects/{project['id']}/remote").json()["remote"] is None


def test_remote_sem_host_e_recusado(client: TestClient, tmp_path: Path):
    """Configurar o remoto sem host é recusado com 400."""
    project = client.post("/projects", json={"name": "p", "root_path": str(tmp_path)}).json()
    response = client.put(f"/projects/{project['id']}/remote", json={"host": ""})
    assert response.status_code == 400


def test_unknown_ids_return_404(client: TestClient):
    """Identificadores inexistentes devolvem 404 nas rotas de projeto, tarefa e conversa."""
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/projects/{missing}").status_code == 404
    assert client.delete(f"/projects/{missing}").status_code == 404
    assert client.get(f"/tasks/{missing}").status_code == 404
    assert client.delete(f"/conversations/{missing}").status_code == 404
    assert client.get(f"/providers/inexistente/models").status_code in (404, 502, 503)
