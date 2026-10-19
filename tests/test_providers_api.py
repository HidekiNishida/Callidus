# tests/test_providers_api.py — descoberta de provedores pela API
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings

CONFIG = """
default_provider: ollama_remote

providers:
  ollama_remote:
    type: ollama
    base_url: http://10.0.0.9:11434
    model: qwen3:8b
    api_key_env: CHAVE_DE_TESTE
"""


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHAVE_DE_TESTE", "chave-de-teste-123456")
    config = tmp_path / "providers.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        enable_background_worker=False,
        provider_config_path=config,
    )

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


def test_providers_are_listed_without_secrets(client: TestClient):
    r = client.get("/providers")
    assert r.status_code == 200
    payload = r.json()
    names = [item["name"] for item in payload["providers"]]
    assert "ollama_remote" in names
    assert "ollama" in names and "llamacpp" in names and "mock" in names
    assert payload["default_provider"] == "ollama_remote"
    entry = next(item for item in payload["providers"] if item["name"] == "ollama_remote")
    assert entry["api_key_source"] == "env"
    assert "api_key" not in entry


def test_unknown_provider_is_404(client: TestClient):
    r = client.get("/providers/nao-existe/models")
    assert r.status_code == 404


def test_models_endpoint_reports_the_server_state(client: TestClient, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "agent.providers.ollama.httpx.AsyncClient",
        lambda *a, **k: real(*a, **{**k, "transport": transport}),
    )
    r = client.get("/providers/ollama_remote/models")
    assert r.status_code == 200
    assert r.json() == {"provider": "ollama_remote", "models": ["qwen3:8b"]}


def test_health_endpoint_reports_connectivity(client: TestClient, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "agent.providers.ollama.httpx.AsyncClient",
        lambda *a, **k: real(*a, **{**k, "transport": transport}),
    )
    r = client.get("/providers/ollama_remote/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert payload["models"] == ["qwen3:8b"]
