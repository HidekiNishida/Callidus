# MCP (`agent.mcp`)

Integração **stdio** com SDK `mcp`.

| Módulo | Função |
|--------|--------|
| [config_models.py](/src/agent/mcp/config_models.py) | Tipos de config |
| [manager.py](/src/agent/mcp/manager.py) | Config, discover, call |
| [stdio_transport.py](/src/agent/mcp/stdio_transport.py) | Sessão ClientSession |

Config: copiar [mcp.example.json](/data/mcp.example.json) → `data/mcp.json` · API: `POST /mcp/discover`, `POST /mcp/call`

Doc: [mcp.md](/docs/architecture/mcp.md)

Voltar: [agent/README.md](/src/agent/README.md)
