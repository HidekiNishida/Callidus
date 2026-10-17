# tests/test_evolution_api.py — endpoints de grafo, métricas e autonomia
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


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


def test_knowledge_reindex_and_metrics(client: TestClient, tmp_path: Path):
    (tmp_path / "a.py").write_text("def foo(): pass\n", encoding="utf-8")
    r = client.post("/projects", json={"name": "P", "root_path": str(tmp_path)})
    pid = r.json()["id"]
    idx = client.post(f"/projects/{pid}/knowledge/reindex")
    assert idx.status_code == 200
    assert idx.json()["nodes"] >= 1
    m = client.get(f"/projects/{pid}/metrics")
    assert m.status_code == 200
    assert "tasks" in m.json()


def test_autonomous_toggle(client: TestClient, tmp_path: Path):
    r = client.post("/projects", json={"name": "P", "root_path": str(tmp_path)})
    pid = r.json()["id"]
    t = client.post(f"/projects/{pid}/tasks", json={"title": "T", "objective": "o"})
    run = client.post(
        f"/projects/{pid}/runs",
        json={"root_task_id": t.json()["id"], "config": {"provider": "mock"}},
    )
    rid = run.json()["id"]
    en = client.post(f"/runs/{rid}/autonomous/enable")
    assert en.status_code == 200
    assert en.json()["autonomous"] is True
    dis = client.post(f"/runs/{rid}/autonomous/disable")
    assert dis.json()["autonomous"] is False
