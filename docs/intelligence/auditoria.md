# Auditoria — Inteligência e Observabilidade do Callidus

Diagnóstico do estado atual e plano de integração dos subsistemas de telemetria, analytics, grafo cognitivo, benchmarks e diagnósticos.

## 1. Arquitetura atual

O Callidus segue camadas com dependência sempre para dentro:

| Camada | Pasta | Responsável por |
|--------|-------|-----------------|
| Domínio | `src/agent/domain` | Enums, estado, schemas, falhas |
| Aplicação | `src/agent/services`, `src/agent/orchestrator` | Regras de negócio, orquestração |
| Infraestrutura | `src/agent/persistence`, `providers`, `tools`, `knowledge`, `memory` | SQLite, provedores, ferramentas, grafo, memória |
| Apresentação | `src/agent/api`, `web/static` | FastAPI, SSE, SPA Vue 3 |

O SQLite (`data/agent.db`) é a fonte da verdade. Há 36 modelos de persistência definidos em `persistence/models.py`, incluindo `EventLogModel`, `InferenceRecordModel`, `ContextSnapshotModel`, `OperationAttemptModel` e `EvidenceModel`.

## 2. Recursos existentes (reaproveitáveis)

### Observabilidade já implementada

- `src/agent/observability/bus.py` — `EventBus` com ring buffer por run, filas de assinantes SSE, operações ao vivo.
- `src/agent/observability/emitter.py` — `emit()` com contexto `observe`/`set_task`, persistência via SQLAlchemy listeners, publicação após commit.
- `src/agent/observability/contracts.py` — catálogo de tipos de evento, `EventEnvelope`, validação de payload, versão de esquema.
- `src/agent/observability/snapshot.py` — `run_snapshot()` e `events_page()` para leitura paginada.
- `src/agent/observability/batching.py` — `DeltaBatcher` para fragmentos de streaming.
- `src/agent/observability/sanitize.py` — remoção de dados sensíveis.
- Rotas SSE já existentes em `src/agent/api/observe_routes.py`: `/events`, `/observe`, `/stream`.

### Métricas já coletadas

- `InferenceRecordModel` grava cada inferência com `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cache_read_tokens`, `cache_write_tokens`, `estimated_prompt_tokens`, `estimated_completion_tokens`, `measurement` (exact/estimate/partial/unavailable), `duration_ms`, `status`, `failure_reason`, `cost_usd`, `budget_pressure`, `input_budget_used`, `output_reserve_used`.
- `ContextSnapshotModel` grava orçamento de contexto por tarefa com `estimated_tokens`, `categories_json`, `budget_pressure`.
- `metrics_service.py` agrega métricas de projeto e run (tarefas, tentativas, tokens, erros, requisitos, estagnação).
- `ledger.py` (`run_spend`, `consistency_report`) já separa uso reportado vs estimado.
- `providers/observed.py` já emite `agent.started`, `agent.output.delta`, `agent.output.completed/failed` com duração e uso.

### Métricas calculadas (não apenas coletadas)

- `fold_usage()` soma registros de inferência com qualidade de medição explícita.
- `spend_of()` prioriza valores reportados pelo provedor sobre estimativas locais.
- `consistency_report()` confere ledger vs metadados das tarefas.

### Informações persistidas

- Eventos de run (seq monotônico, payload JSON).
- Inferências (uso de tokens, duração, erro, medição).
- Snapshots de contexto (orçamento, categorias, pressão).
- Tentativas de operação (tipo, provedor, sucesso, erro).
- Evidências de verificação (verificador, aprovado/reprovado/inconclusivo).
- Tarefas (status, duração, metadados com uso).
- Runs (status, configuração, provider, modelo).

### Informações apenas em memória

- Estado volátil do `EventBus` (anel de últimos 3000 eventos, saídas streaming, operações abertas).
- Contador de passos ativos por run.
- Não há histórico de métricas agregadas ao longo do tempo (soma pontual por consulta).

### Eventos já emitidos

Veja `contracts.py` `EVENT_SPECS`: run.started/completed/failed/paused/resumed/cancelled, plan.started/updated, task.* (criado/iniciado/bloqueado/concluído/falhado/replanejado), agent.* (iniciado/status/delta/completado/failed), tool.* (iniciado/completado/failed), command.*, test.*, verification.*, file.*, strategy.formulated, skill.selected, budget.pressure/granted, context.history_compacted, work.explained, run.stagnation.

### Eventos com informações insuficientes

- Não há eventos de **tempo para o primeiro token** (TTFT) separado do tempo total.
- Não há eventos de **compactação de contexto** com antes/depois de tokens.
- Não há eventos de **recuperação de memória** (skills selecionadas, referências recuperadas).
- Não há eventos de **consumo de recursos do hardware** (CPU/RAM/VRAM).
- Não há evento de **tentativa de verificação** separado da conclusão.

### Informações disponibilizadas pela API

- `/runs/{id}/events` — histórico paginado de eventos.
- `/runs/{id}/observe` — snapshot completo da run.
- `/runs/{id}/stream` — SSE com eventos ao vivo.
- `/projects/{id}/metrics` — métricas agregadas do projeto.
- `/runs/{id}/metrics` — métricas agregadas da run.
- `/tasks/{id}/usage` — uso de tokens da tarefa.
- `/tasks/{id}/attempts` — tentativas da tarefa.
- `/tasks/{id}/evidences` — evidências da tarefa.
- `/tasks/{id}/context-snapshots` — snapshots de contexto.

### Informações que chegam à interface

- Feed de atividades do chat (pensamentos, ferramentas, arquivos).
- Estado live (saídas streaming, operações ativas).
- Inspector de tarefa (tentativas, evidências, snapshots, contrato, uso).
- Métricas do projeto (texto bruto JSON).
- Grafo de conhecimento do projeto (símbolos, imports).

### Novos instrumentos de coleta necessários

1. Métricas de recurso do sistema (CPU, RAM, VRAM) por período.
2. TTFT e latência de inferência por chamada.
3. Eventos de compactação de contexto (antes/depois).
4. Eventos de recuperação de memória e skills selecionadas.
5. Eventos de transição de estado do orquestrador com duração.
6. Cenários de benchmark e resultados persistidos.
7. Diagnósticos gerados a partir de evidências.

### Componentes reutilizáveis

- `EventBus`, `emit`, `observe` — infraestrutura de eventos pronta.
- `InferenceRecordModel` — já suporta medição de tokens com qualidade.
- `ContextSnapshotModel` — já suporta orçamento e pressão de orçamento.
- `snapshot.py` — já monta fotos de run para a API.
- `metrics_service.py` — já agrega métricas de run/projeto.
- SSE infraestrutura — já funciona com reconexão por `after_seq`.

## 3. Lacunas diagnosticadas

| Área | Lacuna | Impacto |
|------|--------|---------|
| Telemetria | Não há eventos de transição de estado do orquestrador com duração | Não é possível reconstruir o fluxo de execução no grafo |
| Telemetria | Não há eventos de compactação de contexto com antes/depois | Não é possível identificar compactações que aumentaram custo |
| Telemetria | Não há eventos de recuperação de memória/skills | Não é possível medir eficiência de recuperação |
| Telemetria | Não há consumo de hardware (CPU/RAM/VRAM) | Não há métricas de recursos |
| Analytics | Não há agregações temporais de métricas | Não há visualização de tendência |
| Analytics | Não há percentis (P50/P95/P99) de latência/tokens | Não há análise de desempenho |
| API | Não há endpoints para grafo cognitivo | Não há visualização de arquitetura |
| API | Não há endpoints para benchmarks | Não há laboratório de comparação |
| API | Não há endpoints para diagnósticos | Não há identificação de gargalos |
| Interface | Não há área integrada de inteligência | Não há visualização de métricas e grafo |
| Interface | Não há visualização de grafo cognitivo animado | Não há acompanhamento do fluxo real |
| Benchmark | Não há catálogo versionado de cenários | Não há comparação reprodutível |
| Benchmark | Não há pontuação por dimensão | Não há avaliação estruturada |
| Diagnóstico | Não há mecanismo de detecção de gargalos | Não há identificação de problemas |
| Retenção | Não há política de retenção de eventos | Crescimento ilimitado do SQLite |

## 4. Problemas de confiabilidade

- Eventos persistidos sobrevivem a reinicializações, mas não há limpeza automática de eventos antigos.
- Não há agregação em consultas para grandes volumes de eventos.
- Não há separação entre histórico detalhado (retenção curta) e agregações (retenção longa).

## 5. Mudanças necessárias

1. **Contratos de telemetria**: versão do schema, tipos de evento para transições de orquestrador, compactação, recuperação, recursos.
2. **Persistência**: novas tabelas para `telemetry_event`, `benchmark_scenario`, `benchmark_execution`, `benchmark_result`, `diagnostic`.
3. **Instrumentação**: orquestrador, provedores, contexto, ferramentas, verificação.
4. **Serviço de analytics**: agregações temporais, percentis, métricas de contexto, recursos, eficiência.
5. **API unificada**: endpoints para métricas, telemetria, grafo, benchmarks, diagnósticos.
6. **Cognitive Graph**: extração de topologia, estados visuais, interatividade frontend.
7. **Dashboard**: páginas Overview, Live Architecture, Performance, Benchmarks, Diagnostics.
8. **Benchmark Engine**: catálogo, execução isolada, pontuação, comparação, exportação.
9. **Diagnóstico**: detecção determinística de gargalos, anomalias, recomendações.
10. **Retenção**: política de retenção de eventos e agregações.

## 6. Riscos

- Overhead da telemetria prejudicando a execução do agente (mitigação: coleta assíncrona, falhas de analytics não bloqueiam execução).
- Crescimento ilimitado do SQLite (mitigação: política de retenção, agregação em consultas).
- Confundir estimativas com valores reais (mitigação: campo `measurement` já existente, preservar origem de cada métrica).
- Dependência de LLM para cálculos determinísticos (mitigação: diagnósticos são determinísticos, LLM apenas elabora explicações).

## 7. Dependências

- `psutil` ou equivalente para coleta de recursos do sistema (CPU, RAM, VRAM).
- Bibliotecas de visualização frontend (avaliar compatível com stack atual, sem dependências pesadas).
- Não requer novas dependências de backend pesadas.

## 8. Plano de implementação (por fases)

| Fase | Objetivo | Entregas |
|------|----------|----------|
| A | Auditoria e contratos | `docs/intelligence/auditoria.md`, contrato de eventos versionado |
| B | Telemetria | Instrumentação de orquestrador, provedores, contexto, ferramentas, verificação; novas tabelas de persistência |
| C | Analytics | Serviço de métricas de tokens, contexto, inferência, recursos, eficiência |
| D | API | Endpoints unificados, SSE para métricas e grafo, paginação, OpenAPI |
| E | Cognitive Graph | Topologia, estados, eventos, interatividade frontend |
| F | Dashboard | Páginas Overview, Live Architecture, Performance, Benchmarks, Diagnostics |
| G | Benchmark Engine | Catálogo de cenários, execução isolada, pontuação, comparação, exportação |
| H | Validação | Testes, desempenho, documentação, atualizar `resume.md` |

Cada fase termina com testes aprovados e documentação atualizada antes de avançar.
