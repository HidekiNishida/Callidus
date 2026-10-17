# Integração MCP

Gerenciador: `src/agent/mcp/manager.py`

Configuração exemplo: [`data/mcp.example.json`](/data/mcp.example.json) (copiar para `data/mcp.json`).

| Capacidade | Estado |
|------------|--------|
| Carregar servidores/tools declarativos | Implementado |
| Listar via API `GET /mcp/servers` | Implementado |
| Transporte stdio + execução real | **Pendente** — retorna erro explícito, não simula sucesso |

Próximo passo: subprocess MCP com handshake JSON-RPC e cache de tools descobertas.
