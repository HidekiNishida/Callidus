# tests/test_tools.py
import pytest

from agent.security.paths import PathSecurityError, resolve_under_root
from agent.tools.registry import ToolContext, build_default_registry


@pytest.mark.asyncio
async def test_read_write_file(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))
    out = await reg.execute("read_file", ctx, {"path": "a.txt"})
    assert out["success"] and out["content"] == "hello"
    w = await reg.execute("write_file", ctx, {"path": "b.txt", "content": "x"})
    assert w["success"]
    assert (tmp_path / "b.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_rewriting_a_python_file_drops_its_stale_bytecode(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    stale = cache / "calc.cpython-314.pyc"
    stale.write_bytes(b"velho")
    other = cache / "outro.cpython-314.pyc"
    other.write_bytes(b"outro")
    ctx = ToolContext(project_root=str(tmp_path))

    out = await build_default_registry().execute("write_file", ctx, {"path": "calc.py", "content": "x = 1\n"})

    assert out["success"] and not stale.exists() and other.exists()


def test_path_traversal_blocked(tmp_path):
    with pytest.raises(PathSecurityError):
        resolve_under_root(tmp_path, "/etc/passwd")
