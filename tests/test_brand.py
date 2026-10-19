# tests/test_brand.py — identidade do produto e compatibilidade com o legado
from pathlib import Path

from agent.brand import (
    ATTACHMENTS_DIR,
    BRAND_FAVICON_PATH,
    BRAND_LOCKUP_PATH,
    BRAND_MARK_PATH,
    BRAND_NAME,
    BRAND_TAGLINE,
    INBOX_ROOT,
    LEGACY_ATTACHMENTS_DIR,
    LEGACY_INBOX_ROOT,
    LEGACY_UI_STORAGE_KEY,
    UI_STORAGE_KEY,
    USER_AGENT,
    is_attachments_dir,
)
from agent.services.attachments import _attachments_folder
from agent.services.inbox import is_inbox_path

WEB_STATIC = Path(__file__).resolve().parents[1] / "web" / "static"


def test_brand_name_is_callidus():
    assert BRAND_NAME == "Callidus"
    assert BRAND_TAGLINE


def test_ui_storage_key_migrates_from_legacy():
    assert UI_STORAGE_KEY == "callidus-ui-v1"
    assert LEGACY_UI_STORAGE_KEY == "agente-local-ui-v1"
    assert UI_STORAGE_KEY != LEGACY_UI_STORAGE_KEY


def test_inbox_accepts_legacy_prefix():
    assert INBOX_ROOT == "callidus-inbox://local"
    assert LEGACY_INBOX_ROOT == "agente-inbox://local"
    assert is_inbox_path(INBOX_ROOT)
    assert is_inbox_path(LEGACY_INBOX_ROOT)
    assert not is_inbox_path("/home/usuario/projeto")


def test_attachments_dir_falls_back_to_legacy(tmp_path: Path):
    assert ATTACHMENTS_DIR == ".callidus"
    assert LEGACY_ATTACHMENTS_DIR == ".agente"
    assert is_attachments_dir(".callidus/anexos/abc")
    assert is_attachments_dir(".agente/anexos/abc")
    assert not is_attachments_dir("src/agent")

    # Pasta legada vazia → usa a nova.
    assert _attachments_folder(str(tmp_path), "t1") == ".callidus/anexos/t1"

    # Pasta legada com arquivos → mantém a legada para não quebrar referências.
    legacy = tmp_path / LEGACY_ATTACHMENTS_DIR / "anexos" / "t1"
    legacy.mkdir(parents=True)
    (legacy / "01-nota.txt").write_text("x", encoding="utf-8")
    assert _attachments_folder(str(tmp_path), "t1") == ".agente/anexos/t1"

    # Tarefa nova na mesma raiz → pasta nova.
    assert _attachments_folder(str(tmp_path), "t2") == ".callidus/anexos/t2"


def test_user_agent_is_branded():
    assert USER_AGENT == "callidus"


def test_brand_assets_exist_on_disk():
    for url in (BRAND_MARK_PATH, BRAND_LOCKUP_PATH, BRAND_FAVICON_PATH):
        assert url.startswith("/assets/brand/")
        assert (WEB_STATIC / url.removeprefix("/")).is_file()


def test_brand_assets_are_valid_svg():
    for name in (
        "callidus-mark.svg",
        "callidus-mark-current.svg",
        "callidus-wordmark.svg",
        "callidus-lockup.svg",
        "callidus-lockup-vertical.svg",
        "favicon.svg",
    ):
        text = (WEB_STATIC / "assets" / "brand" / name).read_text(encoding="utf-8")
        assert text.startswith("<svg") or text.startswith("<?xml")
        assert 'viewBox="' in text
        assert "</svg>" in text


def test_source_brand_files_exist():
    media = Path(__file__).resolve().parents[1] / "media"
    for name in (
        "Callidus Logo.svg",
        "Callidus Name.svg",
        "Callidus Name + Logo Horizontal.svg",
        "Callidus Name + Logo Vertical.svg",
    ):
        assert (media / name).is_file()
