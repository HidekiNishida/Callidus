"""
Arquivo: src/agent/mcp/stdio_transport.py
Nome: stdio_transport.py
Propósito: conversar com servidores MCP via stdio usando o SDK oficial.
Responsabilidade: camada de infraestrutura — listar e invocar as ferramentas de um servidor MCP.
Componentes: list_server_tools, invoke_tool.
Dependências: mcp (SDK oficial), agent.mcp.config_models.
Observações: cada operação abre e fecha a sessão do servidor; o processo é encerrado ao final.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.mcp.config_models import McpServerConfig

logger = logging.getLogger(__name__)


def _parameters(server: McpServerConfig) -> StdioServerParameters:
    """Monta os parâmetros de inicialização do processo do servidor MCP.

    Args:
        server: configuração do servidor.

    Returns:
        Os parâmetros de stdio aceitos pelo SDK.

    Raises:
        ValueError: quando a configuração não traz comando executável.
    """
    if not server.command:
        raise ValueError("comando MCP vazio")
    return StdioServerParameters(
        command=server.command[0],
        args=server.command[1:],
        env=server.env or None,
    )


async def list_server_tools(server: McpServerConfig) -> list[dict[str, Any]]:
    """Lista as ferramentas expostas por um servidor MCP.

    Args:
        server: configuração do servidor.

    Returns:
        A lista de ferramentas, cada uma com identificador, servidor, nome, descrição e schema.
    """
    params = _parameters(server)
    tools: list[dict[str, Any]] = []
    async with stdio_client(params) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            listed = await session.list_tools()
            for tool in listed.tools:
                tool_id = f"mcp:{server.id}:{tool.name}"
                tools.append(
                    {
                        "id": tool_id,
                        "server_id": server.id,
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema or {},
                    }
                )
    return tools


async def invoke_tool(
    server: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Invoca uma ferramenta de um servidor MCP.

    Args:
        server: configuração do servidor.
        tool_name: nome da ferramenta no servidor.
        arguments: argumentos passados à ferramenta.

    Returns:
        O resultado com sucesso, marcação de erro, conteúdo textual e resultado estruturado.
    """
    params = _parameters(server)
    async with stdio_client(params) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            blocks = []
            for block in result.content:
                if hasattr(block, "text"):
                    blocks.append(block.text)
                else:
                    blocks.append(str(block))
            return {
                "success": not bool(result.isError),
                "is_error": bool(result.isError),
                "content": "\n".join(blocks),
                "structured": result.structuredContent,
            }
