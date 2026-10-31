# Cognitive Graph

Grafo visual dinâmico que representa a arquitetura percorrida pelo Callidus durante a execução. Não é um fluxograma decorativo: é uma representação real dos componentes e seu fluxo de execução, atualizada conforme eventos são emitidos.

## Topologia

Os nós representam os componentes internos do Callidus:

| Nó | Tipo | Categoria |
|----|------|-----------|
| `user_request` | source | entrada |
| `api` | transport | transporte |
| `task_manager` | manager | orquestração |
| `run_manager` | manager | orquestração |
| `orchestrator` | core | orquestração |
| `planner` | component | planejamento |
| `decomposition` | component | planejamento |
| `atomizer` | component | planejamento |
| `context_assembly` | component | contexto |
| `context_budget` | component | contexto |
| `memory` | component | memória |
| `knowledge` | component | conhecimento |
| `skills` | component | habilidades |
| `provider` | provider | inferência |
| `tool_registry` | component | ferramentas |
| `tool_execution` | component | ferramentas |
| `verification` | component | verificação |
| `recovery` | component | recuperação |
| `replanning` | component | planejamento |
| `consolidation` | component | consolidação |
| `global_verify` | component | verificação |
| `closing` | component | consolidação |
| `persistence` | store | persistência |

## Estados dos nós

| Estado | Significado |
|--------|-------------|
| `idle` | Componente ocioso |
| `pending` | Aguardando execução |
| `active` | Em execução (animação discreta) |
| `completed` | Concluído com sucesso |
| `failed` | Falhou |
| `retrying` | Tentando novamente |
| `blocked` | Bloqueado |
| `skipped` | Ignorado |
| `paused` | Pausado |

## Arestas

As arestas representam fluxos possíveis entre componentes. Uma aresta é marcada como `traversed` quando o fluxo de execução a percorre. Conexões não utilizadas permanecem neutras.

## Eventos mapeados

Eventos de execução são mapeados para nós do grafo:

| Evento | Nó | Ação |
|--------|----|------|
| `agent.started/completed/failed` | provider | active → completed/failed |
| `tool.started/completed/failed` | tool_execution | active → completed/failed |
| `command.*` | tool_execution | active → completed/failed |
| `test.*` | tool_execution | active → completed/failed |
| `verification.*` | verification | active → completed/failed |
| `plan.started` | planner | active |
| `plan.updated` | decomposition | active |
| `decomposition.recursive` | decomposition | active |
| `context.compacted` | context_assembly | completed |
| `budget.pressure` | context_budget | active |
| `memory.recovered` | memory | completed |
| `skill.selected` | skills | completed |
| `orchestrator.step.started/completed` | orchestrator | active → completed |
| `task.state.transitioned` | task_manager | conforme estado `to` |
| `run.started` | run_manager | active |
| `run.completed/failed/paused` | closing | completed/failed/paused |
| `run.resumed` | run_manager | active |
| `strategy.formulated` | planner | completed |
| `run.stagnation` | replanning | active |
| `verification.recovery_planned` | recovery | active |

## Fluxos não lineares

O grafo representa:
- Retornos ao planner (replanejamento)
- Novas decomposições (decomposição recursiva)
- Recuperação de falhas (recovery → verification)
- Repetição de operações (retrying)
- Ramificações (múltiplos caminhos entre componentes)
- Consolidação e verificação global

## API

| Endpoint | Descrição |
|----------|-----------|
| `GET /api/intelligence/graph/architecture` | Topologia geral sem execução específica |
| `GET /api/intelligence/graph/runs/{run_id}` | Grafo de uma run com estados e arestas |
| `GET /api/intelligence/graph/runs/{run_id}/history` | Histórico de eventos do grafo |

## Frontend

O componente `CognitiveGraphView` renderiza o grafo em SVG com:
- Nós coloridos por estado
- Arestas destacadas quando percorridas
- Painel lateral com detalhes do nó (ativações, duração, erros, metadados)
- Reprodução histórica em velocidade configurável
- Suporte a `prefers-reduced-motion`

O grafo é separado do **Task Graph** (árvore de tarefas), integrado através de IDs de tarefas e eventos.
