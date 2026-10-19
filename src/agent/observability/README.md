# Observabilidade (`observability/`) — EventBus, SSE, Streaming e Snapshots

Barramento de eventos em memória para entrega tempo real (SSE), anel de histórico, operações ao vivo e snapshots de run.

## Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`bus.py`](bus.py) | `EventBus`, `Subscription`, `get_bus()` | **Coração** — ring buffer (seq monotônico/run), assinantes SSE com queue, operations live (model streaming, tool output), `publish()`, `subscribe()`, `recent()`, `live()` |
| [`emitter.py`](emitter.py) | `emit(type, data, task_id, commit)` | **Emissor único** — publica no EventBus + opcionalmente grava `EventLogModel` (se `commit=True`) |
| [`batching.py`](batching.py) | `DeltaBatcher` | **Agrupamento de fragmentos** — buffer por intervalo/tamanho (`stream_delta_interval_ms`, `stream_delta_max_chars`) → `emit` único |
| [`snapshot.py`](snapshot.py) | `build_run_snapshot(run_id, session, bus)` | **Foto do estado** — run, tasks, events, outputs, operations, seq (para `/snapshot` API) |
| [`sanitize.py`](sanitize.py) | `is_sensitive_path(path)`, `sanitize_event_data(data)` | **Sanitização** — remove diff de paths sensíveis (`.env`, `secrets`, `keys`, `passwords`, `tokens`) |
| [`contracts.py`](contracts.py) | `EventEnvelope`, `AgentStarted`, `ToolStarted`, `ToolOutput`, `ModelOutputDelta`, `RunProgress`, etc. | **Tipos TypedDict** — contratos dos eventos para type safety |

## EventBus (`bus.py`)

```python
class EventBus:
    def __init__(self, ring_size=3000, queue_size=1000, max_runs=64):
        self._runs: OrderedDict[str, _RunState]  # LRU por run_id
        self._subs: dict[str, set[Subscription]]  # run_id → assinantes SSE
    
    def publish(self, env: dict):           # env = {"type", "run_id", "seq", "data", ...}
    def subscribe(self, run_id, loop) -> Subscription:  # retorna queue asyncio
    def unsubscribe(self, sub): 
    def recent(self, run_id, after_seq) -> list[dict]:  # anel → eventos > after_seq
    def live(self, run_id) -> dict:         # outputs streaming + operations ativas
    def allocate_seq(self, run_id, initial) -> int:     # seq monotônico por run
    def step_started/finished(run_id):       # contadores de passos ativos
```

### `_RunState` (por run)
- `seq: int` — monotônico
- `ring: deque[dict]` — últimos `ring_size` eventos (auto-eviction)
- `outputs: dict[output_id, dict]` — model streaming ativo (text acumulado, status, seq)
- `operations: dict[key, dict]` — tool/command/test ativos (output acumulado tail)

## Emissor (`emitter.py`)

```python
def emit(event_type: str, data: dict, task_id: UUID|None=None, commit: bool=False):
    env = {
        "type": event_type,
        "run_id": current_run_id(),      # contextvar
        "task_id": str(task_id) if task_id else None,
        "seq": bus.allocate_seq(run_id, initial_seq_from_db),
        "data": data,
        "ts": datetime.now(timezone.utc).isoformat(),
        "persisted": commit,
    }
    bus.publish(env)
    if commit:
        session.add(EventLogModel(...))  # grava no SQLite
```

## Eventos Principais

| Evento | Quando | Data-Chave |
|--------|--------|------------|
| `agent.started` | Início inferência | `output_id`, `task_id`, `agent`, `provider`, `model`, `streaming`, `purpose` |
| `agent.output.delta` | Fragmento streaming | `output_id`, `text` (batched) |
| `agent.output.completed/failed` | Fim inferência | `output_id` |
| `tool.started/completed/failed` | Execução tool | `call_id`, `tool`, `args` (preview), `duration_ms`, `summary` |
| `command.started/output/completed/failed` | Comando shell | `call_id`, `command`, `stream`, `text` (streaming) |
| `test.started/output/completed/failed` | Pytest/script | `call_id`, `counts` (passed/failed/skipped) |
| `file.read/changed/created/deleted` | Operação arquivo | `path`, `diff` (added/removed), `sensitive` |
| `orchestrator.action` | Cada step | `action`, `task_id`, `thought`, `progress` |
| `run.started/progress/completed/failed/paused/resumed/cancelled` | Ciclo run | `reason`, `limit`, `pending`, `requirements` |
| `run.stagnation` | Estagnação detectada | `signature`, `strategy`, `count`, `diagnosis`, `next_action` |
| `plan.validated` | Validação plano | `verdict`, `findings`, `coverage`, `fixes`, `version`, `fingerprint` |
| `verification.started/passed/failed/inconclusive` | Verificação | `verifier`, `criterion`, `summary`, `exit_code` |

## Streaming Real (Modelo)

```python
# providers/observed.py → observed_chat
async def observed_chat(provider, request, purpose, stream=True):
    output_id = uuid.uuid4().hex[:12]
    emit("agent.started", {"output_id": output_id, "task_id": ..., "provider": ..., "model": ..., "streaming": stream, "purpose": purpose})
    
    if stream and provider.supports_streaming:
        batcher = DeltaBatcher(lambda text: emit("agent.output.delta", {"output_id": output_id, "text": text}))
        resp = await provider.chat_streaming(request, on_delta=batcher.add)
        batcher.flush()
        emit("agent.output.completed", {"output_id": output_id})
    else:
        resp = await provider.chat(request)
        emit("agent.output.completed", {"output_id": output_id, "text": resp.content})
    return resp
```

## SSE Endpoints (API)

| Rota | Descrição |
|------|-----------|
| `GET /events?run_id=...&after_seq=...` | Stream de eventos (reconexão via `after_seq`) |
| `GET /live?run_id=...` | Estado live: outputs streaming + operations ativas + seq + stats |
| `GET /snapshot?run_id=...` | Foto completa: run, tasks, events, outputs, operations |

## Configuração (Settings)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `stream_ring_size` | `3000` | Tamanho do anel por run |
| `stream_subscriber_queue` | `1000` | Tamanho da queue por assinante SSE |
| `stream_delta_interval_ms` | `120` | Intervalo de flush do `DeltaBatcher` |
| `stream_delta_max_chars` | `2000` | Max chars antes de flush forçado |
| `stream_max_seconds` | `60.0` | Max vida de conexão SSE (navegador reabre do último `seq`) |
| `event_text_limit` | `20000` | Truncamento por campo de evento |
| `event_output_limit` | `200000` | Limite maior para resposta final |

## Testes

```bash
# Observabilidade unitária
pytest tests/test_observability_unit1.py -v

# Streaming + SSE
pytest tests/test_observability_streaming.py -v

# Executor (events emission)
pytest tests/test_observability_executor.py -v

# E2E observabilidade
pytest tests/test_observability_e2e.py -v

# API observabilidade
pytest tests/test_observability_api.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)