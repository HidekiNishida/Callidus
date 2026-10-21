# CALLIDUS — auditoria integral (frontend + backend)

Escopo: preservar identidade do produto; corrigir defeitos com evidência; validar fluxos reais.

## Arquitetura confirmada

- **Backend:** FastAPI em `src/agent/api`, SQLite `data/agent.db`, orquestrador em `src/agent/orchestrator`, eventos em `event_logs` + SSE `/runs/{id}/stream` e foto `/runs/{id}/observe`.
- **Frontend:** SPA Vue 3 em `web/static/assets/app/` — rotas por **view** (`main.js` NAV_ITEMS), não por URL.

## Inventário de telas (SPA)

| View | Componente | Função |
|------|------------|--------|
| Conversa | `chat.js` | Chat, feed de atividade, composer (provedor/modelo), plano de subtarefas |
| Execução | `live.js` | Painel ao vivo (redutor `live-state.js`) |
| Provedores | `providers.js` | CRUD de provedores e credenciais |
| Automações | `automations.js` | Gatilhos e ações |
| Ajustes | `settings.js` | Tema, execução, projetos, atalhos |
| Global | `sidebar.js`, `topbar.js`, `details.js`, `palette.js` | Navegação, inspetor (Detalhe/Tentativas/Diff/…), paleta ⌘K |

## Critérios de aceitação P1 (narração)

- [x] Narração dentro de `activity-items` (`integrateNarrative` + `.activity-narrations`)
- [x] Sem `<ol class="narrative">` no topo
- [x] Regressão com fixture real (`narrative-replay.test.mjs`)
- [x] Histórico: `hydrateFeedsFromHistory()` após `refreshTasks()`

## Ollama gpt-oss:20b

- Cenário A executado via `scripts/audit_ollama_smoke.sh` — run `7e2b2c40-…` **completed**, 64 eventos, 5× `work.explained`.
- `data/providers.yaml` mantido (`meu_ollama` default `llama3.2`); modelo passado em `run.config.model_id`.

## Estado

Concluído nesta auditoria: P1 narração + histórico do feed + testes + smoke Ollama A + inventário base.

Não executado de forma exaustiva: clique manual em cada aba do inspetor; cenários B–F completos (B/C parciais no smoke por decomposição); benchmark multilíngue.
