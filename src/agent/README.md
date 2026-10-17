# Pacote `agent`

Núcleo do **Agente de IA Local**: orquestração explícita, persistência SQLite, modelos locais e ferramentas.

## Módulos

| Pasta | README | Responsabilidade |
|-------|--------|------------------|
| `api/` | [README.md](/src/agent/api/README.md) | FastAPI, UI estática |
| `domain/` | [README.md](/src/agent/domain/README.md) | Enums, schemas, máquina de estados |
| `persistence/` | [README.md](/src/agent/persistence/README.md) | SQLAlchemy, SQLite |
| `services/` | [README.md](/src/agent/services/README.md) | CRUD projetos/tarefas/runs |
| `orchestrator/` | [README.md](/src/agent/orchestrator/README.md) | Ciclo de execução |
| `tools/` | [README.md](/src/agent/tools/README.md) | Ferramentas determinísticas |
| `providers/` | [README.md](/src/agent/providers/README.md) | Ollama, llama.cpp, mock |
| `context/` | [README.md](/src/agent/context/README.md) | Orçamento de contexto |
| `knowledge/` | [README.md](/src/agent/knowledge/README.md) | Grafo de conhecimento |
| `verification/` | [README.md](/src/agent/verification/README.md) | pytest, checks |
| `security/` | [README.md](/src/agent/security/README.md) | Paths autorizados |
| `mcp/` | [README.md](/src/agent/mcp/README.md) | MCP stdio |
| `vision/` | [README.md](/src/agent/vision/README.md) | Referências de imagem |
| `util/` | [README.md](/src/agent/util/README.md) | JSON, helpers |

Configuração: [`config.py`](/src/agent/config.py) · Padrão **Ollama** documentado em [execucao-local.md](/docs/architecture/execucao-local.md).

Voltar: [src/README.md](/src/README.md)
