"""
Arquivo: tests/test_mcp_manager.py
Nome: test_mcp_manager.py
Propósito: Verificar o gerente de servidores MCP.
Responsabilidade: camada de testes — leitura do identificador de ferramenta e chamada a servidor desativado.
Componentes: identificador de ferramenta MCP e recusa de chamada a servidor desligado.
Dependências: agent.mcp.manager.
Observações: arquivo de configuração MCP temporário em tmp_path; nenhum servidor é iniciado.
"""

import json
from pathlib import Path

import pytest

from agent.mcp.manager import McpManager


def test_parse_mcp_tool_id(tmp_path: Path):
    """O identificador de ferramenta MCP é decomposto em servidor e ferramenta, e identificadores locais são ignorados."""
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
    """Chamar ferramenta de servidor desativado devolve falha em vez de tentar executá-la."""
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
