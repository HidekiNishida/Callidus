"""
Arquivo: tests/test_automation_api.py
Nome: test_automation_api.py
Propósito: Verificar as rotas de automação: criar, consultar, ativar, suspender, executar, testar, cancelar e remover.
Responsabilidade: camada de testes — contrato HTTP das rotas de automação e o que a interface precisa ver.
Componentes: ciclo de criação e remoção, ativação com próximo disparo, validação sem gravação, estados, edição, execução manual, teste de prontidão, cancelamento, status e diagnóstico do supervisor.
Dependências: agent.api.main, agent.config.get_settings e agent.persistence.database.
Observações: banco SQLite temporário por teste (CALLIDUS_TEST_DATABASE_URL) e supervisor de automação desligado.

Testes das rotas de automação: criar, consultar, ativar, suspender, executar,
testar, cancelar e remover — e o que a interface precisa ver.
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from agent.config import get_settings
from agent.persistence.database import build_session_factory, create_db_engine, init_db
from agent.persistence.models import ProjectModel


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Cliente de teste da API sobre um banco temporário, com um projeto já criado."""
    monkeypatch.setenv("CALLIDUS_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.setenv("CALLIDUS_ENABLE_AUTOMATION_SUPERVISOR", "0")
    from agent.api import deps

    deps._engine = None
    deps._session_factory = None
    settings = get_settings()
    engine = init_db(create_db_engine(settings), settings)
    factory = build_session_factory(engine)
    session = factory()
    project = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(project)
    session.commit()
    project_id = str(project.id)
    session.close()

    from agent.api.main import app

    with TestClient(app) as test_client:
        test_client.project_id = project_id
        yield test_client
    deps._engine = None
    deps._session_factory = None


def _definition(project_id: str) -> dict:
    """Monta a definição de uma automação cron com ação de script e permissões."""
    return {
        "name": "tarefa da madrugada",
        "project_id": project_id,
        "trigger": {"kind": "cron", "cron": "0 3 * * *", "timezone": "UTC"},
        "action": {"kind": "script", "command": ["/bin/sh", "-c", "echo ok"]},
        "permissions": {"allow_scripts": True, "allowed_commands": ["/bin/sh"]},
        "policy": {"max_attempts": 2},
        "state": "disabled",
    }


def test_criar_consultar_e_remover(client):
    """A automação criada é listada, consultada e removida; depois da remoção, some da consulta."""
    payload = _definition(client.project_id)
    response = client.post("/automations", json={"definition": payload})
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "disabled"
    assert data["trigger"]["cron"] == "0 3 * * *"
    automation_id = data["id"]

    listed = client.get("/automations").json()
    assert any(item["id"] == automation_id for item in listed)

    detail = client.get(f"/automations/{automation_id}").json()
    assert detail["name"] == "tarefa da madrugada"
    assert detail["firings"] == []

    assert client.delete(f"/automations/{automation_id}").status_code == 200
    assert client.get(f"/automations/{automation_id}").status_code == 404


def test_criar_com_ativacao_calcula_proximo_disparo(client):
    """Criar já ativa calcula o próximo horário de disparo."""
    payload = _definition(client.project_id)
    response = client.post("/automations", json={"definition": payload, "activate": True})
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "enabled"
    assert data["next_run_at"] is not None


def test_validacao_sem_gravacao(client):
    """A validação aponta o erro do gatilho sem gravar a automação."""
    payload = _definition(client.project_id)
    payload["trigger"] = {"kind": "cron"}  # sem expressão
    response = client.post("/automations/validate", json={"definition": payload})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["errors"]
    assert client.get("/automations").json() == []


def test_ativar_suspender_e_desativar(client):
    """Ativar, suspender e desativar percorrem os estados enabled, suspended e disabled."""
    automation_id = client.post(
        "/automations", json={"definition": _definition(client.project_id)}
    ).json()["id"]
    assert client.post(f"/automations/{automation_id}/enable").json()["state"] == "enabled"
    assert client.post(f"/automations/{automation_id}/suspend").json()["state"] == "suspended"
    assert client.post(f"/automations/{automation_id}/disable").json()["state"] == "disabled"


def test_editar_automacao(client):
    """A edição troca o nome e a política de horário perdido da automação."""
    automation_id = client.post(
        "/automations", json={"definition": _definition(client.project_id)}
    ).json()["id"]
    response = client.patch(
        f"/automations/{automation_id}",
        json={"changes": {"name": "novo nome", "missed_policy": "catch_up"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "novo nome"
    assert body["missed_policy"] == "catch_up"


def test_executar_uma_vez_registra_disparo(client):
    """A execução manual cria um disparo pendente com chave de idempotência e o registra no histórico."""
    automation_id = client.post(
        "/automations", json={"definition": _definition(client.project_id)}
    ).json()["id"]
    response = client.post(f"/automations/{automation_id}/run")
    assert response.status_code == 200
    firing = response.json()["firing"]
    assert firing["state"] == "pending"
    assert firing["idempotency_key"]
    history = client.get(f"/automations/{automation_id}/firings").json()
    assert len(history) == 1


def test_teste_verifica_prontidao_sem_executar(client):
    """O teste de prontidão informa a prontidão sem executar a automação."""
    automation_id = client.post(
        "/automations", json={"definition": _definition(client.project_id)}
    ).json()["id"]
    response = client.post(f"/automations/{automation_id}/test", json={"execute": False})
    assert response.status_code == 200
    body = response.json()
    assert body["executed"] is False
    assert "readiness" in body


def test_cancelar_disparos(client):
    """O cancelamento encerra o disparo pendente e informa quantos foram cancelados."""
    automation_id = client.post(
        "/automations", json={"definition": _definition(client.project_id)}
    ).json()["id"]
    client.post(f"/automations/{automation_id}/run")
    response = client.post(f"/automations/{automation_id}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelled"] == 1


def test_status_do_supervisor(client):
    """O status do supervisor informa as automações e o serviço da plataforma."""
    response = client.get("/automations/supervisor/status")
    assert response.status_code == 200
    body = response.json()
    assert body["automations"]["total"] == 0
    assert "service" in body
    assert body["service"]["platform"] in {"macos", "linux", "windows"}


def test_diagnostico_do_supervisor(client):
    """O diagnóstico do supervisor detalha cada automação e os disparos pendentes."""
    client.post("/automations", json={"definition": _definition(client.project_id)})
    body = client.get("/automations/supervisor/diagnose").json()
    assert len(body["automations"]) == 1
    assert body["automations"][0]["missed_policy"] == "run_once"
    assert "pending_firings" in body
