# Serviços (`services/`) — Regras de Negócio (11 Services)

Camada de aplicação sobre o ORM: CRUD, transições, worker autônomo, scheduler, métricas, contratos, memória, knowledge graph.

## Módulos (11 Services)

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
async def autonomous_loop(interval_sec=2.0):
    while not _stop.is_set():
        session = factory()
        runs = session.scalars(select(ExecutionRunModel).where(status=ACTIVE, config.autonomous=true))
        for run in runs:
            orch = RunOrchestrator(session, settings)
            await orch.step(run.id)
        session.commit()
        await asyncio.sleep(interval_sec)
```

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