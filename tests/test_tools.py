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


def test_path_traversal_blocked(tmp_path):
    with pytest.raises(PathSecurityError):
        resolve_under_root(tmp_path, "/etc/passwd")
