# API (`api/`) — FastAPI HTTP + SSE + SPA Estática

Interface HTTP do agente: rotas REST, Server-Sent Events (streaming tempo real) e serving da SPA estática.

## 📁 Arquivos

| Arquivo | Responsabilidade |
|---------|------------------|
| [`main.py`](main.py) | **App FastAPI** — lifespan (engine, background worker, agendador), montagem dos roteadores, montagem da SPA e `run()` (ponto de entrada) |
| [`system_routes.py`](system_routes.py) | **Rotas de sistema** — health, provedores embutidos, ferramentas, MCP, defaults da interface e debug do chat |
| [`project_routes.py`](project_routes.py) | **Rotas de projeto** — CRUD do projeto, computador remoto, filesystem, grafo de conhecimento, métricas, visão ao vivo, eventos e memória |
| [`conversation_routes.py`](conversation_routes.py) | **Rotas de conversa** — conversas soltas, mover, renomear, bifurcar, ativar ramo e conversas do projeto |
| [`task_routes.py`](task_routes.py) | **Rotas de tarefa** — criação/leitura, status, dependências, contrato, snapshots de contexto, tentativas e evidências |
| [`run_routes.py`](run_routes.py) | **Rotas de execução** — iniciar, avançar, pausar, retomar, cancelar, modo autônomo e métricas do run |
| [`presenters.py`](presenters.py) | **Apresentação de leitura** — `present_task` e `present_conversation` (payload único para toda a API) |
| [`live_view.py`](live_view.py) | **Visão ao vivo** — linha do tempo de pensamentos, texto legível das ações e tradução por idioma |
| [`observe_routes.py`](observe_routes.py) | **Rotas de observabilidade** — SSE `/events`, `/live`, `/snapshot`, histórico, diff git |
| [`agent_routes.py`](agent_routes.py) | **Rotas da hierarquia de agentes** — árvore, suspender, retomar, descartar, consultar e métricas de recursos |
| [`automation_routes.py`](automation_routes.py) | **Rotas das automações** — definição, gatilhos, ações, disparos e supervisor |
| [`provider_routes.py`](provider_routes.py) | **Rotas de configuração de provedores** — catálogo, modelos, diagnóstico e credencial |
| [`deps.py`](deps.py) | **Dependências FastAPI** — `db_session`, `read_settings`, `get_engine`, `ToolRegistry`, `McpManager` |

## 🔌 Rotas Principais (Resumo)

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Health check + versão |
| `GET` | `/providers/ollama/models` | Lista modelos Ollama |
| `GET` | `/providers/llamacpp/models` | Lista modelos llama.cpp |
| `GET` | `/tools` | Lista ferramentas registradas (specs) |
| `GET` | `/tools/availability` | Pré-requisitos presentes e ausentes |
| `GET` | `/tools/families` | Famílias habilitadas e piso de risco |
| `GET` | `/system/diagnose` | Sistema, sessão, permissões e dependências |
| `GET` | `/skills` | Skills instaladas, versão e estado |
| `GET/POST` | `/mcp/servers`, `/mcp/discover`, `/mcp/call` | MCP stdio |
| `POST` | `/projects` | Cria projeto |
| `GET` | `/projects`, `/projects/{id}` | Lista/obtém projeto |
| `PATCH` | `/projects/{id}` | Atualiza projeto |
| `GET/POST` | `/conversations`, `/conversations/{id}/*` | CRUD conversas + branches + fork |
| `GET/POST` | `/projects/{id}/conversations` | Conversas do projeto |
| `GET/POST` | `/projects/{id}/tasks` | CRUD tarefas do projeto |
| `PATCH` | `/tasks/{id}/status` | Transição de status (valida state_machine) |
| `POST` | `/tasks/{id}/dependencies` | Adiciona dependência |
| `POST/GET` | `/projects/{id}/runs` | Cria/lista execuções |
| `POST` | `/runs/{id}/step` | **Um passo do orquestrador** |
| `POST` | `/runs/{id}/execute` | Múltiplos passos (`run_until_idle`) |
| `POST` | `/runs/{id}/pause\|resume\|cancel\|autonomous/enable\|disable` | Controle de run |
| `GET` | `/projects/{id}/live` | Estado atual para UI (thoughts, focus, action) |
| `GET` | `/projects/{id}/overview` | Resumo (tasks por status, run ativa) |
| `GET` | `/tasks/{id}/attempts\|evidences\|context-snapshots\|contract` | Detalhes da tarefa |
| `GET/POST` | `/projects/{id}/memory` | CRUD memória |
| `POST` | `/projects/{id}/knowledge/reindex\|search\|neighbors` | Grafo de conhecimento |
| `GET` | `/projects/{id}/metrics\|events` | Métricas + timeline de eventos |
| `GET` | `/config/ui-defaults` | Defaults para UI (provider, model, approve_tools) |
| `GET` | `/projects/{id}/agents` | Árvore de agentes do projeto |
| `GET` | `/agents/{id}` | Agente: papel, estado, execuções, descobertas e checkpoint |
| `GET` | `/agents/{id}/executions` | Histórico de execuções do agente |
| `POST` | `/agents/{id}/suspend` | Suspende a execução (persiste estado, libera contexto) |
| `POST` | `/agents/{id}/resume` | Retoma a execução a partir do estado persistido |
| `POST` | `/agents/{id}/discard` | Descarta o estado recuperável (preserva resultado e artefatos) |
| `GET/POST` | `/agents/{id}/queries` | Consultas entre agentes: pendentes e criação (resposta dirigida) |
| `GET` | `/metrics/resources` | Concorrência de inferências, espera e estado da hierarquia |
| `GET` | `/fs/browse`, `/fs/pick-folder` | Navegação de pastas |
| `POST` | `/fs/mkdir` | Cria uma pasta dentro do alcance permitido (seletor de pastas) |
| `GET` | `/projects/{id}/git-diff` | Diff git do projeto |
| `GET`/`PUT`/`DELETE` | `/projects/{id}/remote` | Computador remoto do projeto (SSH): ler, configurar ou voltar para a máquina local |
| `POST` | `/projects/{id}/remote/test` | Testa a conexão com o computador remoto |
| `DELETE` | `/projects/{id}` | Remove o projeto e o que pertence a ele (conversas, tarefas, execuções, memória, grafo). **Os arquivos da pasta não são apagados** |
| `POST` | `/debug/chat/ollama` | Chat direto Ollama (debug) |

## 🔌 Provedores (configuração)

Rotas em [`provider_routes.py`](provider_routes.py):

| Método | Rota | Função |
|--------|------|--------|
| `GET` | `/providers` | Catálogo (configurados + embutidos), sem credenciais |
| `GET` | `/providers/{nome}/models` | Modelos do servidor |
| `GET` | `/providers/{nome}/health` | Diagnóstico de conectividade (sempre 200, com `ok` true/false) |
| `POST` | `/providers/{nome}/test` | Testa a conexão (mesmo que health, com POST) |
| `GET` | `/providers/config` | Configuração em uso + caminho do arquivo + situação da credencial |
| `PUT` | `/providers/config` | Valida e grava a configuração de provedores |
| `DELETE` | `/providers/config/{nome}` | Remove um provedor (e a credencial gravada) |
| `PUT` | `/providers/config/{nome}/secret` | Grava a credencial em arquivo `0600` e aponta a configuração |
| `DELETE` | `/providers/config/{nome}/secret` | Apaga a credencial |

## 📊 Observabilidade (SSE + EventBus)

- **`GET /events?run_id=...&after_seq=...`** — Stream de eventos (ring buffer + assinantes)
- **`GET /live?run_id=...`** — Estado live (outputs streaming, operations, seq, stats)
- **`GET /snapshot?run_id=...`** — Foto completa (run, tasks, events, outputs, operations)
- **EventBus** ([`../observability/bus.py`](../observability/bus.py)): ring buffer (seq monotônico), assinantes com queue, operations live (model streaming, tool output)

## 🔌 SPA Estática

- Servida em `/` (index.html) + `/assets/*` — SPA **Vue 3** em [`web/static/assets/app/`](/web/static/assets/app/)
  (vendor do Vue versionado em `/assets/vendor/`); detalhes em [frontend.md](/docs/architecture/frontend.md)
- Headers `Cache-Control: no-cache` para evitar cache agressivo do navegador
- Pasta configurável via `STATIC_WEB_DIR` ou `web/static` (padrão)

## ⚙️ Lifespan (Startup/Shutdown)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()                    # Cria engine SQLAlchemy
    settings = read_settings()
    if settings.enable_background_worker:
        start_background_worker()   # AutonomousWorker loop
    try:
        yield
    finally:
        if settings.enable_background_worker:
            await stop_background_worker()
```

## ⚙️ Configuração via Settings

Todas as opções em [`../config.py`](../config.py) — `api_host`, `api_port`, `shutdown_grace_seconds`, `static_web_dir`, `mcp_config_path`, `enable_background_worker`, limites de observabilidade (`event_text_limit`, `stream_delta_interval_ms`, `stream_subscriber_queue`, `stream_ring_size`, `stream_max_seconds`).

## 🧪 Testes

```bash
# API HTTP
pytest tests/test_api.py -v

# Observabilidade (SSE, streaming, snapshot)
pytest tests/test_observability_*.py -v

# Evolução da API
pytest tests/test_evolution_api.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)