# tests/test_web_frontend.py — a interface Vue está montada e conversa com rotas que existem
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.api.main import app


def _all_paths(router) -> set[str]:
    """Rotas da API, incluindo as de routers incluídos (o FastAPI mantém aninhadas)."""
    paths: set[str] = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            paths |= _all_paths(original)
    return paths


WEB = Path(__file__).resolve().parents[1] / "web" / "static"
APP_DIR = WEB / "assets" / "app"


def _html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


def test_index_mounts_the_vue_application():
    html = _html()
    assert '<div id="app">' in html
    assert "/assets/vendor/vue.global.prod.js" in html
    assert "/assets/app/main.js" in html
    assert "/assets/app/style.css" in html
    # O shell não carrega mais o front antigo em JS puro.
    assert "assets/app.js" not in html
    assert "observe.js" not in html


def test_vue_is_vendored_locally():
    vendor = WEB / "assets" / "vendor" / "vue.global.prod.js"
    assert vendor.is_file()
    content = vendor.read_text(encoding="utf-8")
    assert "vue v3" in content
    assert len(content) > 50_000


@pytest.mark.parametrize(
    "module",
    [
        "main.js",
        "store.js",
        "api.js",
        "ui.js",
        "components/sidebar.js",
        "components/topbar.js",
        "components/chat.js",
        "components/details.js",
        "components/providers.js",
        "components/live.js",
    ],
)
def test_application_modules_exist(module):
    assert (APP_DIR / module).is_file()


def test_frontend_uses_endpoints_that_exist():
    """Cada rota chamada pela interface precisa existir na API (contrato front ↔ back)."""
    routes = {re.sub(r"\{[^}]+\}", "*", path) for path in _all_paths(app)}
    prefixes: set[str] = set()
    for path in APP_DIR.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"api\(\s*[`\"'](/[^`\"'$]*)", text):
            raw = match.group(1)
            raw = raw.split("${")[0].rstrip("/$")
            if raw:
                prefixes.add(raw)
    family = (
        "/projects",
        "/conversations",
        "/tasks",
        "/runs",
        "/providers",
        "/config",
        "/fs",
        "/mcp",
        "/tools",
        "/health",
    )
    checked = {prefix for prefix in prefixes if prefix.startswith(family)}
    assert checked, "a interface deveria chamar alguma rota da API"
    for prefix in checked:
        assert any(candidate.startswith(prefix) for candidate in routes), (
            f"rota usada pela interface não existe: {prefix}"
        )


def test_providers_view_uses_the_configuration_endpoints():
    text = (APP_DIR / "store.js").read_text(encoding="utf-8")
    assert "/providers/config" in text
    assert "/providers/" in text
    routes = _all_paths(app)
    assert "/providers/config" in routes
    assert "/providers/config/{name}/secret" in routes
