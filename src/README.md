# Código-fonte (`src/`)

O mapa do código-fonte: onde fica cada camada.

Pacote Python instalável **`callidus`** (`pip install -e .`).

## 🏗️ Estrutura

| Caminho | README | Responsabilidade |
|---------|--------|------------------|
| [`agent/`](agent/README.md) | [README.md](agent/README.md) | **Runtime completo do Callidus** (API, orquestrador, ferramentas, provedores, persistência, domínio, serviços, observabilidade, memória, conhecimento, verificação, MCP, visão, utilitários, i18n, security, context, guides) |
| `agent/api/` | [README.md](agent/api/README.md) | FastAPI HTTP + SSE + SPA estática |
| `agent/domain/` | [README.md](agent/domain/README.md) | Enums, máquina de estados, schemas Pydantic, classificação de falhas |
| `agent/persistence/` | [README.md](agent/persistence/README.md) | SQLAlchemy 2 + SQLite (models, database, engine, session) |
| `agent/services/` | [README.md](agent/services/README.md) | 11 services: CRUD projetos/tarefas/runs/conversas/memória/contratos + worker autônomo + scheduler + métricas + tentativas |
| `agent/orchestrator/` | [README.md](agent/orchestrator/README.md) | **Ciclo de execução** (runner, planner, decomposition, atomizer, validation, consolidation, global_verify, requirements, progress, stagnation, replan, closing, usage, resume) |
| `agent/tools/` | [README.md](agent/tools/README.md) | Registro central + 17 ferramentas builtins + browser + diffing + aliases |
| `agent/providers/` | [README.md](agent/providers/README.md) | Ollama, llama.cpp, mock + interface comum + observed (streaming) |
| `agent/context/` | [README.md](agent/context/README.md) | Orçamento de tokens + montagem de prompt + compactação |
| `agent/verification/` | [README.md](agent/verification/README.md) | Verificações determinísticas (pytest, script, command, file_contains, syntax) + fingerprint |
| `agent/observability/` | [README.md](agent/observability/README.md) | EventBus (memória: ring, assinantes SSE, operations live) + emitter + batching + snapshot + sanitize + contratos |
| `agent/memory/` | [README.md](agent/memory/README.md) | Extração e gravação de memória (project + conversation) |
| `agent/knowledge/` | [README.md](agent/knowledge/README.md) | Grafo de conhecimento (símbolos, imports, arquivos) + indexador AST |
| `agent/guides/` | [README.md](agent/guides/README.md) | Descoberta de guias por modelo (`capability_line`, `guide_digest`) |
| `agent/mcp/` | [README.md](agent/mcp/README.md) | MCP stdio (manager, transport, config models) |
| `agent/security/` | [README.md](agent/security/README.md) | Resolução segura de paths sob `project_root` |
| `agent/vision/` | [README.md](agent/vision/README.md) | Referências de imagem para contexto futuro |
| `agent/util/` | [README.md](agent/util/README.md) | Parse JSON tolerante |
| `agent/i18n/` | [README.md](agent/i18n/README.md) | Detecção de idioma + instrução no prompt |

## 📁 Arquivos-chave na raiz do `agent/`

| Arquivo | Propósito |
|---------|-----------|
| [`config.py`](agent/config.py) | **Configuração central** (pydantic-settings): todas as variáveis de ambiente, `resolved_database_url()`, `get_settings()` |
| [`__init__.py`](agent/__init__.py) | Define `__version__ = "0.1.0"` (versão do pacote; API anuncia 0.5.0) |

## ⚙️ Execução

```bash
# Instalação
pip install -e ".[dev]"

# API + UI
callidus-api  # http://127.0.0.1:8765/

# Testes
pytest
```

## 📚 Documentação Relacionada

- [Arquitetura — visão geral](/docs/architecture/visao-geral.md)
- [Modelo de dados](/docs/architecture/modelo-dados.md)
- [Máquina de estados](/docs/architecture/maquina-estados.md)
- [Execução local](/docs/architecture/execucao-local.md)
- [Requisitos, verificação, progresso](/docs/architecture/requisitos-verificacao-progresso.md)

---

**Voltar:** [README raiz](/README.md) · **Regra de READMEs:** [readmes-pastas.md](/docs/regras/readmes-pastas.md)