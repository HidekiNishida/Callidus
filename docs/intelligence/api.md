# API — Inteligência e Observabilidade

Endpoints unificados para todos os subsistemas de inteligência. A API é a fonte única de dados exibidos na interface e disponível para integrações externas.

## Prefixo

Todos os endpoints estão sob `/api/intelligence`.

## Métricas

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/metrics/overview` | GET | Visão geral agregada do workspace |
| `/metrics/runs/{run_id}` | GET | Métricas detalhadas de uma run |
| `/metrics/projects/{project_id}` | GET | Métricas agregadas de um projeto |
| `/metrics/models` | GET | Uso de modelos por run |
| `/metrics/timeline` | GET | Linha do tempo de métricas agregadas |

Parâmetros de query: `project_id`, `run_id`, `after`, `limit`, `types`, `task_id`, `tail`.

## Telemetria

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/events` | GET | Eventos persistidos paginados |
| `/events/{event_id}` | GET | Detalhe de um evento |
| `/runs/{run_id}/snapshot` | GET | Foto completa do estado de uma run |

## Grafo Cognitivo

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/graph/architecture` | GET | Topologia geral sem execução específica |
| `/graph/runs/{run_id}` | GET | Grafo de uma run com estados e arestas |
| `/graph/runs/{run_id}/history` | GET | Histórico de eventos do grafo |

## Benchmarks

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/benchmarks` | GET | Lista cenários |
| `/benchmarks` | POST | Cria cenário |
| `/benchmarks/{id}` | GET | Detalhe do cenário |
| `/benchmarks/{id}/run` | POST | Executa cenário |
| `/benchmarks/{id}/results` | GET | Resultados do cenário |
| `/benchmarks/compare` | GET | Compara execuções |

Corpo de execução: `{ "scenario_id": "...", "provider": "...", "model_id": "...", "config": {} }`.

## Diagnósticos

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/diagnostics` | GET | Lista diagnósticos (filtros opcionais) |
| `/diagnostics/{id}` | GET | Detalhe de um diagnóstico |
| `/diagnostics` | POST | Cria diagnóstico manualmente |
| `/diagnostics/runs/{run_id}/analyze` | POST | Diagnóstico determinístico sobre uma run |
| `/diagnostics/summary` | GET | Resumo agregado |

## SSE

Os eventos de telemetria também estão disponíveis via SSE nos endpoints existentes:
- `GET /runs/{run_id}/stream` — stream de eventos com reconexão por `after_seq`

## Exemplos

```bash
# Visão geral do projeto
curl http://127.0.0.1:8765/api/intelligence/metrics/overview?project_id=<uuid>

# Grafo cognitivo de uma run
curl http://127.0.0.1:8765/api/intelligence/graph/runs/<uuid>

# Executar benchmark
curl -X POST http://127.0.0.1:8765/api/intelligence/benchmarks/<id>/run \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama", "model_id": "llama3.2"}'

# Diagnósticos de uma run
curl http://127.0.0.1:8765/api/intelligence/diagnostics?run_id=<uuid>
```

## OpenAPI

A documentação interativa está disponível em `http://127.0.0.1:8765/docs` quando a API está em execução.
