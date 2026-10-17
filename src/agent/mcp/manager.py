# src/agent/mcp/manager.py — gerenciamento de servidores MCP (config + execução limitada)
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class McpServerConfig:
    id: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class McpManager:
    """Carrega configuração e expõe ferramentas registradas manualmente por servidor."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._servers: list[McpServerConfig] = []
        self._tools: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._servers = []
        self._tools = {}
        if not self._config_path.is_file():
            return
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        for item in data.get("servers", []):
            self._servers.append(McpServerConfig(**item))
        for tool in data.get("tools", []):
            self._tools[tool["id"]] = tool

    def list_servers(self) -> list[McpServerConfig]:
        return list(self._servers)

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools.values())

    async def call_tool(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(tool_id)
        if spec is None:
            return {"success": False, "error": "ferramenta MCP não registrada"}
        server_id = spec.get("server_id")
        server = next((s for s in self._servers if s.id == server_id), None)
        if server is None or not server.enabled:
            return {"success": False, "error": "servidor MCP indisponível ou desabilitado"}
        return {
            "success": False,
            "error": "conexão MCP stdio não iniciada neste ambiente",
            "hint": "Configure o servidor e implemente transporte na próxima iteração",
            "server": server.id,
            "tool": tool_id,
            "arguments": arguments,
        }
