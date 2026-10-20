# tests/test_agent_api.py — interface HTTP da hierarquia de agentes
"""Os endpoints de agente e consulta, exercitados como a interface web os usa."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.services.agent_service import AgentService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
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


@pytest.fixture
def tree(client: TestClient):
    project = client.post("/projects", json={"name": "agentes", "root_path": "/tmp/agentes"}).json()
    root = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Avô", "objective": "Resolver incidente"},
    ).json()
    child = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Pai", "objective": "Diagnosticar", "parent_id": root["id"]},
    ).json()
    return {"project": project, "root": root, "child": child}


def _agents(session):
    return AgentService(session)


def test_a_arvore_de_agentes_e_exposta(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        agents = _agents(session)
        root_agent = agents.ensure_agent(uuid.UUID(tree["root"]["id"]))
        child_agent = agents.ensure_agent(uuid.UUID(tree["child"]["id"]))
        session.commit()
        root_id, child_id = str(root_agent.id), str(child_agent.id)
    finally:
        session.close()

    listed = client.get(f"/projects/{tree['project']['id']}/agents").json()
    assert {a["id"] for a in listed} == {root_id, child_id}
    child = next(a for a in listed if a["id"] == child_id)
    assert child["parent_id"] == root_id
    assert child["depth"] == 1


def test_suspender_e_retomar_um_agente(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        service = _agents(session)
        agent = service.ensure_agent(uuid.UUID(tree["child"]["id"]))
        service.start_execution(agent.id)
        session.commit()
        agent_id = str(agent.id)
    finally:
        session.close()

    suspended = client.post(f"/agents/{agent_id}/suspend", params={"reason": "memória"})
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "SUSPENDED"

    resumed = client.post(f"/agents/{agent_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RUNNING"


def test_consulta_entre_agentes_pela_interface(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        agents = _agents(session)
        root_agent = agents.ensure_agent(uuid.UUID(tree["root"]["id"]))
        child_agent = agents.ensure_agent(uuid.UUID(tree["child"]["id"]))
        agents.record_finding(
            child_agent.id, "A causa da falha foi o import removido", evidence=["calc.py:1"]
        )
        session.commit()
        root_id, child_id = str(root_agent.id), str(child_agent.id)
    finally:
        session.close()

    asked = client.post(
        f"/agents/{child_id}/queries",
        json={"requester_agent_id": root_id, "question": "qual foi a causa da falha?"},
    )
    assert asked.status_code == 200
    body = asked.json()
    assert body["status"] == "ANSWERED"
    assert "import removido" in body["answer"]
    assert body["answer_json"]["from_persisted_state"] is True

    listed = client.get(f"/agents/{root_id}/queries").json()
    assert any(q["id"] == body["id"] for q in listed)


def test_consulta_circular_e_recusada_pela_interface(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        agents = _agents(session)
        root_agent = agents.ensure_agent(uuid.UUID(tree["root"]["id"]))
        child_agent = agents.ensure_agent(uuid.UUID(tree["child"]["id"]))
        session.commit()
        root_id, child_id = str(root_agent.id), str(child_agent.id)
    finally:
        session.close()

    asked = client.post(
        f"/agents/{root_id}/queries",
        json={"requester_agent_id": child_id, "question": "oi?"},
    )
    assert asked.status_code == 409


def test_descartar_um_agente(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        agent = _agents(session).ensure_agent(uuid.UUID(tree["child"]["id"]))
        session.commit()
        agent_id = str(agent.id)
    finally:
        session.close()

    discarded = client.post(f"/agents/{agent_id}/discard", json={"reason": "não é mais necessário"})
    assert discarded.status_code == 200
    body = discarded.json()
    assert body["preserved"]["task_id"] == tree["child"]["id"]


def test_as_metricas_de_recurso_sao_expostas(client: TestClient, tree):
    from agent.api.deps import get_session_factory

    session = get_session_factory()()
    try:
        agents = _agents(session)
        agent = agents.ensure_agent(uuid.UUID(tree["child"]["id"]))
        agents.record_finding(agent.id, "achado")
        session.commit()
    finally:
        session.close()

    metrics = client.get("/metrics/resources").json()
    assert metrics["executor_limit"] >= 1
    assert "max_active" in metrics["executor"]
    assert metrics["agents"]["total"] >= 1
    assert metrics["agents"]["max_depth"] >= 0
    assert "by_status" in metrics["executions"]
    assert "by_status" in metrics["queries"]
