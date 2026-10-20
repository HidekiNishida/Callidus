# Pacote `agent` — Runtime do Callidus

Núcleo do **Callidus**: orquestração explícita, persistência SQLite, modelos locais e ferramentas determinísticas.

## Módulos (Subpacotes)

| Pasta | README | Responsabilidade Principal |
|-------|--------|---------------------------|
| [`api/`](api/README.md) | [README.md](api/README.md) | **FastAPI** — rotas HTTP, SSE, SPA estática, deps (DB, Settings, ToolRegistry) |
| [`domain/`](domain/README.md) | [README.md](domain/README.md) | **Contratos de domínio** — enums, máquina de estados, schemas Pydantic, falhas |
| [`persistence/`](persistence/README.md) | [README.md](persistence/README.md) | **SQLAlchemy 2 + SQLite** — models (20 tabelas), database (engine/session), migrações manuais |
| [`automation/`](automation/README.md) | [README.md](automation/README.md) | **Automações persistentes** — definição aprovada, gatilhos (temporal/evento), ações (Callidus/script), dependências, disparo idempotente, supervisor headless e adaptadores nativos (launchd/systemd/Windows) |
| [`services/`](services/README.md) | [README.md](services/README.md) | **Regras de negócio** — 15 services: Project, Conversation, Task, Run, Contract, Memory, KnowledgeGraph, Metrics, AutonomousWorker, Scheduler, Attempt + **Executor compartilhado**, **AgentService**, **QueryService**, **AgentScheduler** |
| [`orchestrator/`](orchestrator/README.md) | [README.md](orchestrator/README.md) | **Ciclo de execução** — runner (step, run_until_idle), planner, strategy (abordagem profissional), decomposition, atomizer, plan_validation, consolidation, global_verify, requirements, progress, stagnation, replan, closing, usage, resume |
| [`tools/`](tools/README.md) | [README.md](tools/README.md) | **Ferramentas** — registry central, 17 builtins (arquivos, comandos, git, testes, browser, memória), browser (Playwright), diffing, aliases |
| [`providers/`](providers/README.md) | [README.md](providers/README.md) | **Provedores de inferência** — Ollama, llama.cpp, OpenRouter, OpenAI-compatível, Anthropic, Gemini, mock + interface `LLMProvider`, registro declarativo e `observed_chat` (streaming real) |
| [`context/`](context/README.md) | [README.md](context/README.md) | **Contexto do modelo** — orçamento de tokens (`ContextBudgetError`), montagem de componentes, compactação, builder por operação |
| [`verification/`](verification/README.md) | [README.md](verification/README.md) | **Verificação independente** — runner (pytest, script, command, file_contains, syntax, file_exists, static_analysis), recovery (diagnóstico → correção → re-verificação), fingerprint (hash artefatos) |
| [`observability/`](observability/README.md) | [README.md](observability/README.md) | **EventBus em memória** — ring buffer, assinantes SSE, operations live, emitter, batching (streaming), snapshot, sanitize, contratos |
| [`memory/`](memory/README.md) | [README.md](memory/README.md) | **Memória** — extração de pedidos (`remember`) + gravação (project + conversation scopes) |
| [`knowledge/`](knowledge/README.md) | [README.md](knowledge/README.md) | **Grafo de conhecimento** — indexador AST (símbolos, imports), reindex, search, neighbors |
| [`guides/`](guides/README.md) | [README.md](guides/README.md) | **Guias por modelo** — `capability_line(model_id)`, `guide_digest(project_root, objective)` |
| [`mcp/`](mcp/README.md) | [README.md](mcp/README.md) | **MCP stdio** — manager (servers, tools, call_tool), transport JSON-RPC 2.0, config models |
| [`security/`](security/README.md) | [README.md](security/README.md) | **Paths seguros** — `resolve_under_root(root, raw)` → `Path` absoluto + `PathSecurityError` |
| [`vision/`](vision/README.md) | [README.md](vision/README.md) | **Referências de imagem** — para contexto futuro (base64/data URI) |
| [`util/`](util/README.md) | [README.md](util/README.md) | **Utilitários** — `parse_json_object` (extração tolerante de JSON do modelo) |
| [`i18n/`](i18n/README.md) | [README.md](i18n/README.md) | **Internacionalização** — `detect_language(text)` → `pt`/`en`/`es` + `language_instruction(locale)` |
| [`skills/`](skills/README.md) | [README.md](skills/README.md) | **Skills sob demanda** — contrato (`SkillSpec`), catálogo em Markdown, `SkillRegistry`, `SkillSelector` (seleção e injeção no prompt) |

## Arquivos na Raiz do `agent/`

| Arquivo | Propósito | Funções/Classes Exportadas |
|---------|-----------|---------------------------|
| [`config.py`](config.py) | **Configuração central** via `.env` + variáveis de ambiente (pydantic-settings) | `Settings` (todas as opções), `Settings.resolved_database_url()`, `get_settings()` |
| [`__init__.py`](__init__.py) | Marca pacote + versão | `__version__ = "0.1.0"` |

## Fluxo Principal (Orquestrador)

```mermaid
flowchart LR
  API[API /runs/{id}/step] --> ORCH[RunOrchestrator.step]
  ORCH --> PICK[_pick_next_task]
  PICK -->|PENDING| PLAN[PLANNING: decomposition]
  PICK -->|READY| RUN[RUNNING: execute]
  PICK -->|VERIFYING| VER[VERIFYING: verify]
  PLAN --> DECOMP[resolve_decomposition_plan]
  DECOMP --> APPLY[apply_decomposition]
  APPLY --> VALID[validate_and_repair]
  RUN --> CTX[OperationContextBuilder]
  CTX --> PROV[Provider: Ollama/llamacpp/mock]
  PROV --> TOOLS[ToolRegistry.execute]
  TOOLS --> VERIF[VerificationRunner]
  VERIF --> EVID[EvidenceModel]
  EVID --> CONSOL[consolidate_parent]
  CONSOL --> GLOBAL[global_verify]
  GLOBAL --> CLOSE[closing.final_answer]
  CLOSE --> DONE[RunStatus.COMPLETED]
```

## Configuração (Variáveis-Chave)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_PROVIDER` | `ollama` | Provedor usado quando run não especifica (ou nome do arquivo de provedores) |
| `PROVIDERS_CONFIG_PATH` | — | Arquivo YAML/JSON com os provedores nomeados (ver [provedores.md](../../docs/architecture/provedores.md)) |
| `DEFAULT_MODEL_ID` | `llama3.2` | Modelo na decomposição e operações |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Endpoint HTTP Ollama |
| `LLAMACPP_BASE_URL` | `http://127.0.0.1:8080` | llama.cpp server (OpenAI compat) |
| `DEFAULT_CONTEXT_LIMIT` | `8192` | Janela de contexto do modelo |
| `DEFAULT_INPUT_BUDGET` | `6000` | Tokens para prompt (entrada) |
| `DEFAULT_OUTPUT_RESERVE` | `1024` | Reserva para completion |
| `MAX_ATTEMPTS_PER_TASK` | `8` | Tentativas máximas por tarefa |
| `MAX_ORCHESTRATOR_STEPS` | `100` | Passos máximos por `run_until_idle` |
| `ENABLE_BACKGROUND_WORKER` | `true` | Liga `AutonomousWorker` no startup |

## Documentação Técnica Relacionada

| Documento | Foco |
|-----------|------|
| [Visão geral da arquitetura](/docs/architecture/visao-geral.md) | Camadas, fases, ADRs |
| [Modelo de dados](/docs/architecture/modelo-dados.md) | 14 tabelas, campos, relações |
| [Máquina de estados](/docs/architecture/maquina-estados.md) | TaskStatus, RunStatus, transições |
| [Execução local](/docs/architecture/execucao-local.md) | Instalação, padrões, conversas, memória, UI |
| [Requisitos, verificação, progresso](/docs/architecture/requisitos-verificacao-progresso.md) | Rastreabilidade, validação plano, verificação independente, estagnação, pausa/retomada |

## Testes Relacionados

```bash
# Orquestrador E2E (mock)
pytest tests/test_e2e_orchestrator.py -v

# Decomposição + validação
pytest tests/test_decomposition.py tests/test_plan_validation.py -v

# Verificação independente
pytest tests/test_independent_verification.py -v

# Estagnação + limites + retomada
pytest tests/test_stagnation_limits.py tests/test_run_termination.py -v

# Observabilidade (SSE, streaming, snapshot)
pytest tests/test_observability_*.py -v
```

---

**Voltar:** [src/README.md](../README.md) · **Raiz:** [README.md](../../README.md) · **Regra de READMEs:** [docs/regras/readmes-pastas.md](../../docs/regras/readmes-pastas.md)