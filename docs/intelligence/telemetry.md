# Telemetria

Contrato tipado e versionado para eventos de execução do Callidus. A telemetria é a fonte de verdade para todos os subsistemas de inteligência.

## Contrato de evento

Cada evento possui, quando aplicável:

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `event_id` | UUID | Identificador único do evento |
| `event_type` | string | Tipo do evento (ex.: `orchestrator.step.started`) |
| `schema_version` | int | Versão do contrato (atualmente 2) |
| `timestamp` | datetime | Instante do evento em UTC |
| `run_id` | UUID | Run à qual o evento pertence |
| `task_id` | UUID | Tarefa relacionada, quando aplicável |
| `attempt_id` | UUID | Tentativa relacionada, quando aplicável |
| `parent_event_id` | UUID | Evento pai na cadeia de correlação |
| `component` | string | Componente emissor |
| `operation` | string | Operação executada |
| `status` | string | Status (started, completed, failed, retrying, blocked, skipped, paused) |
| `duration_ms` | int | Duração em milissegundos |
| `measurement_quality` | string | `provider_reported`, `locally_counted`, `estimated`, `unavailable` |
| `metadata` | object | Dados adicionais específicos do tipo |

## Tipos de evento de telemetria

| Tipo | Categoria | Descrição |
|------|-----------|-----------|
| `orchestrator.step.started` | orchestrator | Início de um passo do orquestrador |
| `orchestrator.step.completed` | orchestrator | Término de um passo com ação e duração |
| `task.state.transitioned` | task | Mudança de estado de tarefa com motivo |
| `context.compacted` | context | Compactação com antes/depois de tokens |
| `memory.recovered` | context | Recuperação de memória e skills selecionadas |
| `provider.inference.started` | provider | Início de chamada ao provedor |
| `provider.inference.completed` | provider | Término de chamada com métricas de tokens |
| `resources.sampled` | resources | Amostra de CPU, RAM, VRAM |
| `verification.attempt.started` | verification | Início de tentativa de verificação |
| `verification.attempt.completed` | verification | Término de tentativa com resultado |

## Correlação

Eventos podem ser correlacionados por `run_id`, `task_id`, `attempt_id` e `parent_event_id`. Isso permite reconstruir o fluxo completo de execução: de uma run até uma chamada específica ao provedor dentro de uma tarefa.

## TelemetryService

O `TelemetryService` é o ponto único de emissão de eventos de telemetria. Métodos principais:

- `step_started(step_index, ...)` — início de passo do orquestrador
- `step_completed(step_index, action, duration_ms, ...)` — término de passo
- `state_transitioned(task_id, from_status, to_status, reason, ...)` — transição de tarefa
- `context_compacted(before_tokens, after_tokens, purpose, ...)` — compactação de contexto
- `memory_recovered(skills, sources, tokens, ...)` — recuperação de memória
- `provider_inference_started(provider, model, purpose, ...)` — início de inferência
- `provider_inference_completed(provider, model, duration_ms, prompt_tokens, completion_tokens, ...)` — término de inferência
- `resources_sampled(cpu_percent, ram_mb, vram_mb, ...)` — amostra de recursos
- `verification_attempt_started(verifier, ...)` — início de verificação
- `verification_attempt_completed(verifier, passed, duration_ms, ...)` — término de verificação

Falhas de telemetria nunca bloqueiam a execução: erros de coleta são absorvidos silenciosamente.

## Instrumentação do Orchestrator

O `RunOrchestrator` emite eventos em:

- `_step_locked`: `orchestrator.step.started` e `orchestrator.step.completed` com duração
- `_step_body`: `task.state.transitioned` em PENDING→PLANNING, PLANNING→READY, READY→RUNNING, RETRY_PENDING→READY, READY→BLOCKED

## Exemplos

```python
from agent.intelligence.telemetry import TelemetryService

telemetry = TelemetryService(session)

# Início de um passo
telemetry.step_started(step_index=1, run_id=run_id)

# Transição de tarefa
telemetry.state_transitioned(
    task_id=task.id,
    from_status="PENDING",
    to_status="PLANNING",
    reason="iniciou planejamento",
)

# Chamada ao provedor com métricas de tokens
telemetry.provider_inference_completed(
    provider="ollama",
    model="llama3.2",
    duration_ms=450,
    prompt_tokens=120,
    completion_tokens=80,
    measurement_quality="exact",
)
```

## Integração com EventBus

Eventos persistidos (`commit=True`) são publicados no `EventBus` após o commit da transação, permitindo que assinantes SSE recebam atualizações em tempo real. Fragmentos (`persist=False`) são publicados imediatamente, sem gravação no banco.
