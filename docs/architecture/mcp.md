# Integração MCP

![integracoes](/media/icons/integracoes.svg){width=48}

A integração com servidores MCP por stdio.

Gerenciador: [src/agent/mcp/](/src/agent/mcp/README.md)

## ⚙️ Configuração (padrão)

1. Copie [data/mcp.example.json](/data/mcp.example.json) para `data/mcp.json`.
2. Ajuste `servers[].command` (argv completo: executável + args).
3. `enabled: true` apenas para servidores confiáveis.

## 🔌 API

| Método | Rota | Função |
|--------|------|--------|
| GET | `/mcp/servers` | Config + tools em cache |
| POST | `/mcp/discover` | Conecta via stdio e registra tools (`mcp:{server}:{name}`) |
| POST | `/mcp/call` | Body `{ "tool_id", "arguments" }` |

## 🔄 Orquestrador

Metadata de tarefa:

```json
{ "mcp_tool": "mcp:filesystem:read_file", "mcp_args": { "path": "..." } }
```

## 🔌 Transporte

Implementado com SDK **`mcp`** (`stdio_client` + `ClientSession`). Falhas de spawn/conexão retornam erro explícito — não simulam sucesso.

Voltar: [architecture/README.md](/docs/architecture/README.md)