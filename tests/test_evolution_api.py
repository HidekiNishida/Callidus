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


def test_task_contract_upsert(client: TestClient, tmp_path: Path):
    r = client.post("/projects", json={"name": "P", "root_path": str(tmp_path)})
    pid = r.json()["id"]
    t = client.post(f"/projects/{pid}/tasks", json={"title": "T", "objective": "auth.py module"})
    tid = t.json()["id"]
    put = client.put(
        f"/tasks/{tid}/contract",
        json={"outputs": {"type": "Auth", "files": ["auth.py"]}},
    )
    assert put.status_code == 200
    got = client.get(f"/tasks/{tid}/contract")
    assert got.status_code == 200
    assert got.json()["outputs"]["files"] == ["auth.py"]


def test_live_board_after_step(client: TestClient, tmp_path: Path):
    r = client.post("/projects", json={"name": "P", "root_path": str(tmp_path)})
    pid = r.json()["id"]
    t = client.post(
        f"/projects/{pid}/tasks",
        json={"title": "Demo", "objective": "e2e corrigir calc.py"},
    )
    run = client.post(
        f"/projects/{pid}/runs",
        json={"root_task_id": t.json()["id"], "config": {"provider": "mock", "approve_risky_tools": True}},
    )
    step = client.post(f"/runs/{run.json()['id']}/step")
    assert step.status_code == 200
    live = client.get(f"/projects/{pid}/live")
    assert live.status_code == 200
    body = live.json()
    assert body["headline"]
    assert body["how"]
    assert body["action"] != "idle"
    assert isinstance(body["thoughts"], list)
    assert "thinking" in body


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
