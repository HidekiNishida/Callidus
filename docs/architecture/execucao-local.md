# Execução local

## Instalação

```bash
cd "~/Documents/Projetos/Agente de IA Local"
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # opcional
```

## Padrões (documentação e runtime)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_PROVIDER` | `ollama` | Runs sem config usam Ollama |
| `DEFAULT_MODEL_ID` | `llama3.2` | Modelo na decomposição |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | HTTP Ollama |
| `AGENT_DATA_DIR` | `./data` | SQLite + `mcp.json` |
| `ALLOW_MOCK_FALLBACK` | `false` | Testes podem habilitar |

Ordem de decomposição: **builtin e2e** (objetivo contém `e2e`) → **Ollama** → template genérico → mock (se permitido).

## API e UI

```bash
agente-api
# http://127.0.0.1:8765/  — UI
# http://127.0.0.1:8765/docs
```

Demo sem Ollama: objetivo com `e2e` usa provider `mock` automaticamente na UI.

## MCP

```bash
cp data/mcp.example.json data/mcp.json
curl -X POST http://127.0.0.1:8765/mcp/discover
```

## Testes

```bash
pytest
```

Índice de pastas: [readmes-pastas.md](/docs/regras/readmes-pastas.md).

Voltar: [architecture/README.md](/docs/architecture/README.md)
