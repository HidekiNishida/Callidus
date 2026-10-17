# tests/test_api.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")

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


def test_health(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"


def test_ui_defaults(client: TestClient):
    r = client.get("/config/ui-defaults")
    assert r.status_code == 200
    assert r.json()["provider"] == "ollama"


def test_project_overview(client: TestClient, tmp_path: Path):
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
