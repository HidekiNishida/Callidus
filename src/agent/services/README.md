# Serviços (`services/`) — Regras de Negócio (15 Services)

Camada de aplicação sobre o ORM: CRUD, transições, worker autônomo, scheduler, métricas, contratos, memória, knowledge graph — e a camada de **agentes** (agente lógico, execução, consulta e escalonador).

## Módulos (15 Services)

| Arquivo | Classe | Responsabilidade |
|---------|--------|------------------|
| [`project_service.py`](project_service.py) | `ProjectService` | CRUD projetos + `add_memory/list_memory` + `touch_file` (KG) |
| [`conversation_service.py`](conversation_service.py) | `ConversationService` | CRUD conversas + branches + `fork_message` + `activate_branch` + `tasks_for_branch` |
| [`task_service.py`](task_service.py) | `TaskService` | CRUD tarefas + `add_dependency` + `dependencies_satisfied` + `promote_ready_if_dependencies_met` + `update_status` (valida `state_machine`) |
| [`run_service.py`](run_service.py) | `RunService` | CRUD runs + `start_run` + `pause_run` + `resume_run` + `cancel_run` |
| [`attempt_service.py`](attempt_service.py) | `AttemptService` | `record` (dedup via `prompt_fp`), `count_attempts`, `attempts_exhausted`, `repeated_output_detected`, `fingerprint` |
| [`contract_service.py`](contract_service.py) | `ContractService` | `get`/`upsert_with_impact` contratos + `validate_for_run` (inputs/outputs/invariants) |
| [`memory_store.py`](memory_store.py) | — | `extract_memory_request` (detecta "lembre-se") + `memory_saver` para tool `remember` |
| [`knowledge/graph_service.py`](knowledge/graph_service.py) | `KnowledgeGraphService` | `reindex` (AST), `search`, `neighbors`, `touch_file` |
| [`metrics_service.py`](metrics_service.py) | `MetricsService` | `project_metrics` (tasks por status, tokens, tentativas, evidências) + `run_metrics` |
| [`autonomous_worker.py`](autonomous_worker.py) | `autonomous_loop`, `start_background_worker`, `stop_background_worker`, `enable_autonomous_on_run` | **Loop background**: a cada 2s, `step()` runs `ACTIVE` + `autonomous=true` |
| [`scheduler.py`](scheduler.py) | `start_scheduler`, `stop_scheduler` | APScheduler para `ScheduledRunModel` (cron) |
| [`inbox.py`](inbox.py) | `effective_root`, `is_inbox_project` | Resolve pasta do usuário (`Path.home()`) para projetos/conversas sem pasta |
| [`fs_browse.py`](fs_browse.py) | `browse_directories`, `pick_folder_native` | API `/fs/browse` + `/fs/pick-folder` (macOS `osascript`) |
| [`attachments.py`](attachments.py) | `materialize_attachments`, `attachment_note` | Salva anexos (imagens/docs) em `data/attachments/{task_id}/` |
| [`executor.py`](executor.py) | `InferenceExecutor`, `get_executor`, `reset_executor` | **Executor compartilhado** — limita inferências de LLM simultâneas (padrão 1) e mede concorrência/espera |
| [`agent_service.py`](agent_service.py) | `AgentService` | **Agente lógico** — `ensure_agent`, `start_execution`, `suspend`, `resume`, `save_checkpoint`, `record_finding`, `discard` |
| [`query_service.py`](query_service.py) | `QueryService` | **Consultas entre agentes** — `ask`, `resolve`, `answer_from_persisted`, `pending_for` |
| [`agent_scheduler.py`](agent_scheduler.py) | `AgentScheduler` | **Escalonador por eventos** — fila de operações elegíveis, uma por vez, sem espera que gasta token |

## Fluxos Principais

### Criação de Tarefa (`TaskService.create_task`)
```python
task = TaskModel(project_id, conversation_id, branch_id, parent_id, title, objective, ...)
session.add(task)
session.flush()
_log_event("task.created", ...)
# Se tem attachments → materialize_attachments + atualiza objective
# Se pede memória → extract_memory_request → ProjectService.add_memory
```

### Transição de Status (`TaskService.update_status`)
```python
validate_transition(current, target)  # domain/state_machine.py
task.status = target.value
if RUNNING and not started_at: started_at = now
if TERMINAL: completed_at = now
if BLOCKED/FAILED: metadata_json.blocked_reason = reason
_log_event(f"task.{target.value.lower()}", ...)
```

### Worker Autônomo (`autonomous_worker.py`)
```python
async def autonomous_loop(interval_sec=2.0, scheduler=None):
    while not _stop.is_set():
        session = factory()
        # Descoberta: consulta ao SQLite. Nenhuma inferência para descobrir trabalho.
        runs = session.scalars(select(ExecutionRunModel).where(status=ACTIVE, config.autonomous=true))
        for run in runs:
            scheduler.submit("run_step", f"run:{run.id}", {"run_id": str(run.id)})
        for query in consultas_pendentes(session):
            scheduler.submit("query", f"query:{query.id}", {"query_id": str(query.id)})
        session.commit()
        # Execução: uma operação por vez, em sessão própria.
        await scheduler.run_once()
        await asyncio.sleep(interval_sec)
```

### Agente, execução e consulta (`agent_service.py`, `query_service.py`)
```python
agent = AgentService(session).ensure_agent(task.id)   # agente lógico da tarefa
AgentService(session).start_execution(agent.id)         # execução ocupa memória de inferência
AgentService(session).save_checkpoint(agent.id, {"step": "analisando"})
AgentService(session).suspend(agent.id)                 # libera a execução, guarda o estado

query = QueryService(session).ask(pai.id, filho.id, "causa da falha?")
resposta = await QueryService(session).resolve(query.id)  # estado persistido primeiro

### Tentativas (`AttemptService`)
- **Dedup**: `prompt_fp` = hash(messages + generation params) — mesmo prompt não reenvia
- **Fingerprint**: hash da resposta (stdout/stderr/result) — detecta loop de output
- **Contadores**: `count_attempts(task_id)`, `attempts_exhausted(task_id)` (respeita `max_attempts_per_task`)

## Testes

```bash
# CRUD básico
pytest tests/test_api.py -v

# Conversas + branches + memory + i18n
pytest tests/test_conversations_memory_i18n.py -v

# Tentativas + loops
pytest tests/test_attempt_loop.py tests/test_failures.py -v

# Worker autônomo
pytest tests/test_e2e_orchestrator.py -v  # usa mock provider

# Scheduler
pytest tests/test_mcp_manager.py -v  # inclui scheduled runs
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)