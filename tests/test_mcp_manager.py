# tests/test_mcp_manager.py
import json
from pathlib import Path

import pytest

from agent.mcp.manager import McpManager


def test_parse_mcp_tool_id(tmp_path: Path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [{"id": "s1", "command": ["echo", "mcp"], "enabled": False}],
                "tools": [],
            }
        ),
        encoding="utf-8",
    )
    mgr = McpManager(cfg)
    assert mgr._parse_tool_id("mcp:s1:read") == ("s1", "read")
    assert mgr._parse_tool_id("local:read") is None


@pytest.mark.asyncio
async def test_call_disabled_server(tmp_path: Path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [{"id": "s1", "command": ["true"], "enabled": False}],
                "tools": [],
            }
        ),
        encoding="utf-8",
    )
    mgr = McpManager(cfg)
    out = await mgr.call_tool("mcp:s1:tool", {})
    assert out["success"] is False
