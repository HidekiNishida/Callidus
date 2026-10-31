# Arquitetura — Inteligência e Observabilidade

Visão geral dos subsistemas de inteligência, suas dependências e como se integram ao Callidus existente.

## Camadas

O sistema de inteligência segue a mesma organização em camadas do Callidus, com dependência sempre apontando para dentro:

```text
Apresentação (API + Frontend)
         ↓
Aplicação (TelemetryService, AnalyticsService, BenchmarkEngine, DiagnosticEngine, CognitiveGraph)
         ↓
Domínio (contratos de evento, schemas versionados)
         ↓
Infraestrutura (SQLite models, EventBus, emit)
```

## Subsistemas e responsabilidades

| Subsistema | Módulo | Responsabilidade | Depende de |
|------------|--------|-----------------|------------|
| Telemetria | `agent/intelligence/telemetry.py` | Eventos tipados, correlação, emissão | `agent.observability` |
| Analytics | `agent/intelligence/analytics.py` | Agregação de métricas | `agent.persistence.models` |
| Cognitive Graph | `agent/intelligence/graph.py` | Topologia, estados, arestas | `agent.persistence.models` |
| Benchmark Engine | `agent/intelligence/benchmarks.py` | Cenários, execução, pontuação | `agent.intelligence.analytics` |
| Diagnostic Engine | `agent/intelligence/diagnostics.py` | Gargalos, anomalias, recomendações | `agent.intelligence.analytics` |
| API | `agent/api/intelligence_routes.py` | Endpoints unificados | Todos os subsistemas acima |

## Fluxo de dados

1. O **Orchestrator** emite eventos de telemetria (steps, transições de estado) via `TelemetryService`.
2. Provedores, contexto, ferramentas e verificação emitem eventos via `observed.py` e `emit`.
3. Os eventos são persistidos em `EventLogModel`, `InferenceRecordModel`, `ContextSnapshotModel`.
4. **AnalyticsService** lê esses modelos e calcula agregações com percentis.
5. **CognitiveGraph** reconstrói o estado da execução a partir dos eventos persistidos.
6. **BenchmarkEngine** executa cenários isolados e salva resultados em tabelas próprias.
7. **DiagnosticEngine** analisa runs e gera diagnósticos a partir de evidências.
8. A **API** expõe tudo por endpoints REST e SSE.

## Novos modelos de persistência

| Modelo | Tabela | Finalidade |
|--------|--------|------------|
| `BenchmarkScenarioModel` | `benchmark_scenarios` | Cenários versionados de benchmark |
| `BenchmarkExecutionModel` | `benchmark_executions` | Execuções de cenário |
| `BenchmarkResultModel` | `benchmark_results` | Resultados e pontuações |
| `DiagnosticModel` | `diagnostics` | Diagnósticos gerados |
| `TelemetryAggregateModel` | `telemetry_aggregates` | Agregações temporais com retenção distinta |

Os modelos existentes (`EventLogModel`, `InferenceRecordModel`, `ContextSnapshotModel`) continuam sendo usados sem alteração.

## Retenção

- **Histórico detalhado** (`event_logs`): retenção curta, eventos individuais.
- **Agregações** (`telemetry_aggregates`): retenção longa, métricas pré-calculadas por período.
