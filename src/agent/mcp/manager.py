"""
Arquivo: src/agent/mcp/manager.py
Nome: manager.py
Propósito: gerenciar a configuração, a descoberta e a execução das ferramentas MCP.
Responsabilidade: camada de aplicação — ciclo de vida dos servidores MCP e das ferramentas registradas.
Componentes: McpManager.
Dependências: agent.mcp.config_models, agent.mcp.stdio_transport.
Observações: uma falha de um servidor não impede a descoberta dos demais; o erro é registrado e devolvido.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent.mcp import stdio_transport
from agent.mcp.config_models import McpServerConfig

logger = logging.getLogger(__name__)


class McpManager:
    """Gerencia os servidores MCP configurados e as ferramentas que eles expõem.

    Atributos:
        _config_path: arquivo de configuração MCP consultado no arranque e no recarregamento.
        _servers: servidores declarados na configuração.
        _tools: ferramentas conhecidas, indexadas pelo identificador.
        _auto_discover: quando `True`, a descoberta roda automaticamente.
    """

    def __init__(self, config_path: Path) -> None:
        """Cria o gerenciador e carrega a configuração.

        Args:
            config_path: caminho do arquivo de configuração MCP.
        """
        self._config_path = config_path
        self._servers: list[McpServerConfig] = []
        self._tools: dict[str, dict[str, Any]] = {}
        self._auto_discover = True
        self.reload()

    def reload(self) -> None:
        """Recarrega a configuração MCP, descartando servidores e ferramentas anteriores.

        Observações:
            Um arquivo ausente deixa o gerenciador vazio, sem erro.
        """
        self._servers = []
        self._tools = {}
        self._auto_discover = True
        if not self._config_path.is_file():
            return
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        self._auto_discover = bool(data.get("auto_discover", True))
        for item in data.get("servers", []):
            self._servers.append(McpServerConfig(**item))
        for tool in data.get("tools", []):
            self._tools[tool["id"]] = tool

    def list_servers(self) -> list[McpServerConfig]:
        """Servidores declarados na configuração.

        Returns:
            Uma cópia da lista de servidores.
        """
        return list(self._servers)

    def list_tools(self) -> list[dict[str, Any]]:
        """Ferramentas MCP conhecidas.

        Returns:
            Uma cópia da lista de ferramentas registradas.
        """
        return list(self._tools.values())

    async def discover(self) -> dict[str, Any]:
        """Descobre as ferramentas expostas pelos servidores habilitados.

        Returns:
            Um dicionário com a contagem de ferramentas descobertas, as ferramentas e os erros por servidor.
        """
        discovered: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for server in self._servers:
            if not server.enabled:
                continue
            try:
                items = await stdio_transport.list_server_tools(server)
                for item in items:
                    self._tools[item["id"]] = item
                discovered.extend(items)
            except Exception as exc:
                logger.warning("MCP discover falhou %s: %s", server.id, exc)
                errors.append({"server_id": server.id, "error": str(exc)})
        return {"discovered": len(discovered), "tools": discovered, "errors": errors}

    def _parse_tool_id(self, tool_id: str) -> tuple[str, str] | None:
        """Separa o identificador `mcp:<servidor>:<ferramenta>`.

        Args:
            tool_id: identificador da ferramenta.

        Returns:
            Tupla com servidor e ferramenta, ou `None` quando o identificador não é do formato MCP.
        """
        if not tool_id.startswith("mcp:"):
            return None
        parts = tool_id.split(":", 2)
        if len(parts) != 3:
            return None
        return parts[1], parts[2]

    async def call_tool(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Executa uma ferramenta MCP pelo identificador informado.

        Args:
            tool_id: identificador da ferramenta (`mcp:<servidor>:<ferramenta>` ou id registrado).
            arguments: argumentos passados à ferramenta.

        Returns:
            O resultado da chamada; em caso de falha, um dicionário com `success` falso e o erro.
        """
        parsed = self._parse_tool_id(tool_id)
        if parsed is not None:
            server_id, tool_name = parsed
            server = next((s for s in self._servers if s.id == server_id), None)
            if server is None or not server.enabled:
                return {"success": False, "error": "servidor MCP indisponível", "tool": tool_id}
            try:
                out = await stdio_transport.invoke_tool(server, tool_name, arguments)
                out["tool"] = tool_id
                return out
            except Exception as exc:
                return {"success": False, "error": str(exc), "tool": tool_id}

        spec = self._tools.get(tool_id)
        if spec is None:
            return {"success": False, "error": "ferramenta MCP não registrada", "tool": tool_id}
        server_id = spec.get("server_id")
        server = next((s for s in self._servers if s.id == server_id), None)
        if server is None or not server.enabled:
            return {"success": False, "error": "servidor MCP indisponível ou desabilitado"}
        name = spec.get("name") or tool_id
        try:
            return await stdio_transport.invoke_tool(server, name, arguments)
        except Exception as exc:
            return {"success": False, "error": str(exc), "tool": tool_id}
