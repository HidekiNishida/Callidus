# tests/test_attachments.py — texto longo, imagem e documento viram arquivo no projeto
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def test_pasted_text_and_image_are_stored(client, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project = client.post("/projects", json={"name": "Anexos", "root_path": str(root)}).json()
    pasted = "linha de requisito\n" * 80
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={
            "title": "Com anexo",
            "objective": "olhe o texto e a imagem",
            "metadata": {
                "attachments": [
                    {"kind": "text", "name": "texto-colado.txt", "mime": "text/plain", "content": pasted},
                    {
                        "kind": "image",
                        "name": "tela.png",
                        "mime": "image/png",
                        "content_base64": f"data:image/png;base64,{png}",
                    },
                    {"kind": "file", "name": "../../segredo.txt", "mime": "text/plain", "content": "doc"},
                ]
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Anexos do usuário:" in body["objective"]
    assert "linha de requisito" not in body["objective"]
    refs = body["metadata_json"]["attachments"]
    assert len(refs) == 3
    assert "content" not in refs[0]
    text_path = root / refs[0]["path"]
    image_path = root / refs[1]["path"]
    assert text_path.read_text(encoding="utf-8") == pasted
    assert image_path.read_bytes().startswith(b"\x89PNG")
    assert refs[2]["name"] == "segredo.txt"
    assert ".." not in refs[2]["path"]
    assert (root / refs[2]["path"]).read_text(encoding="utf-8") == "doc"


def test_attachment_over_limit_is_rejected(client, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project = client.post("/projects", json={"name": "Limite", "root_path": str(root)}).json()
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={
            "title": "Grande",
            "objective": "texto",
            "metadata": {
                "attachments": [
                    {"kind": "text", "name": "grande.txt", "content": "x" * 1_000_001},
                ]
            },
        },
    )
    assert response.status_code == 400
