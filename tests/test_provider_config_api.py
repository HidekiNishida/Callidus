# tests/test_provider_config_api.py — configuração de provedores pela interface
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PROVIDERS_CONFIG_PATH", raising=False)
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


PAYLOAD = {
    "default_provider": "meu_ollama",
    "providers": {
        "meu_ollama": {
            "type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "llama3.2",
        },
        "meu_gateway": {
            "type": "openai_compatible",
            "base_url": "https://gateway.exemplo/v1",
            "model": "modelo-x",
            "timeout": 45,
        },
    },
}


def test_config_is_created_in_the_data_folder(client: TestClient, tmp_path: Path):
    r = client.put("/providers/config", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["default_provider"] == "meu_ollama"
    assert set(body["providers"]) == {"meu_ollama", "meu_gateway"}
    assert body["providers"]["meu_gateway"]["timeout"] == 45

    saved = tmp_path / "data" / "providers.yaml"
    assert saved.is_file()
    assert "meu_ollama" in saved.read_text(encoding="utf-8")


def test_configured_provider_becomes_usable_by_the_agent(client: TestClient):
    client.put("/providers/config", json=PAYLOAD)
    catalog = client.get("/providers").json()
    names = [item["name"] for item in catalog["providers"]]
    assert "meu_ollama" in names
    assert catalog["default_provider"] == "meu_ollama"


def test_invalid_provider_is_refused(client: TestClient):
    r = client.put(
        "/providers/config",
        json={"providers": {"x": {"type": "tipo-que-nao-existe"}}},
    )
    assert r.status_code == 400
    assert "tipo-que-nao-existe" in r.json()["detail"]


def test_invalid_url_is_refused(client: TestClient):
    r = client.put(
        "/providers/config",
        json={"providers": {"x": {"type": "ollama", "base_url": "ftp://servidor"}}},
    )
    assert r.status_code == 400


def test_secret_is_stored_outside_the_config_and_never_returned(client: TestClient, tmp_path: Path):
    client.put("/providers/config", json=PAYLOAD)
    r = client.put("/providers/config/meu_gateway/secret", json={"secret": "chave-secreta-123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["providers"]["meu_gateway"]["secret"] == {"configured": True, "source": "file"}
    assert "chave-secreta-123456" not in json.dumps(body)

    secret_file = tmp_path / "data" / "secrets" / "meu_gateway.key"
    assert secret_file.is_file()
    assert secret_file.read_text(encoding="utf-8").strip() == "chave-secreta-123456"
    # Permissão restrita: só o dono lê.
    assert not (secret_file.stat().st_mode & 0o077)

    # O arquivo de configuração aponta para a credencial, sem conter o valor.
    saved = (tmp_path / "data" / "providers.yaml").read_text(encoding="utf-8")
    assert "chave-secreta-123456" not in saved
    assert "api_key_file" in saved


def test_secret_can_be_cleared(client: TestClient, tmp_path: Path):
    client.put("/providers/config", json=PAYLOAD)
    client.put("/providers/config/meu_gateway/secret", json={"secret": "chave-secreta-123456"})
    r = client.delete("/providers/config/meu_gateway/secret")
    assert r.status_code == 200
    assert r.json()["providers"]["meu_gateway"]["secret"]["configured"] is False
    assert not (tmp_path / "data" / "secrets" / "meu_gateway.key").exists()


def test_provider_can_be_removed(client: TestClient):
    client.put("/providers/config", json=PAYLOAD)
    r = client.delete("/providers/config/meu_gateway")
    assert r.status_code == 200
    assert "meu_gateway" not in r.json()["providers"]


def test_removing_unknown_provider_is_404(client: TestClient):
    assert client.delete("/providers/config/nao-existe").status_code == 404


def test_json_config_file_is_supported(tmp_path: Path, monkeypatch):
    config = tmp_path / "providers.json"
    config.write_text(
        json.dumps({"providers": {"j": {"type": "mock"}}}), encoding="utf-8"
    )
    monkeypatch.setenv("PROVIDERS_CONFIG_PATH", str(config))
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as client:
        body = client.get("/providers/config").json()
        assert body["path"] == str(config)
        assert "j" in body["providers"]
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None
