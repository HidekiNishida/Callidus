"""
Arquivo: tests/test_api.py
Nome: test_api.py
Propósito: Verificar o contrato básico da API HTTP do Callidus.
Responsabilidade: camada de testes — rotas de saúde, configuração da interface, visão geral de projeto e fluxo de projeto e tarefa.
Componentes: health, ui-defaults, overview do projeto e criação de projeto, tarefa e mudança de status.
Dependências: agent.api.deps, agent.config.Settings e TestClient.
Observações: banco temporário em tmp_path e worker de fundo desativado.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    """Cliente de teste da API com banco temporário e worker de fundo desligado."""
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


def test_health(client: TestClient):
    """A rota de health responde com status ok."""
    assert client.get("/health").json()["status"] == "ok"


def test_ui_defaults(client: TestClient):
    """A configuração padrão da interface informa o provedor inicial."""
    r = client.get("/config/ui-defaults")
    assert r.status_code == 200
    assert r.json()["provider"] == "ollama"


def test_project_overview(client: TestClient, tmp_path: Path):
    """A visão geral do projeto conta as tarefas criadas."""
    r = client.post(
        "/projects",
        json={"name": "Ov", "root_path": str(tmp_path)},
    )
    pid = r.json()["id"]
    client.post(
        f"/projects/{pid}/tasks",
        json={"title": "T", "objective": "o"},
    )
    ov = client.get(f"/projects/{pid}/overview")
    assert ov.status_code == 200
    assert ov.json()["task_total"] == 1


def test_project_task_flow(client: TestClient, tmp_path: Path):
    """Criar projeto, criar tarefa e mudar o status responde 200 e gera eventos no histórico."""
    r = client.post(
        "/projects",
        json={"name": "Test", "root_path": str(tmp_path), "description": "d"},
    )
    assert r.status_code == 200
    project_id = r.json()["id"]

    r2 = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Obj", "objective": "Implementar Y"},
    )
    assert r2.status_code == 200
    task_id = r2.json()["id"]

    r3 = client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "PLANNING"},
    )
    assert r3.status_code == 200

    r4 = client.get(f"/projects/{project_id}/events")
    assert r4.status_code == 200
    assert len(r4.json()) >= 2
