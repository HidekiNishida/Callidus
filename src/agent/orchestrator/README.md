# Orquestrador (`orchestrator/`) — Ciclo de Execução do Callidus

**Coração do agente**: transforma um objetivo em tarefas atômicas, executa ferramentas/modelo, verifica resultados, consolida, replaneja falhas e escreve a resposta final.

## Módulos

| Arquivo | Classe/Função Principal | Responsabilidade |
|---------|------------------------|------------------|
| [`runner.py`](runner.py) | `RunOrchestrator` | **Ciclo completo**: `step()` → `_step_body()` → `_pick_next_task` → `PLANNING`/`RUNNING`/`VERIFYING` → `_execute_task` → `_finalize_verification` → `consolidate_parent` → `global_verify` → `closing` |
| [`planner.py`](planner.py) | `ensure_canonical_memory_for_objective` | Grava memória canônica ("Objetivo global") no início do run |
| [`strategy.py`](strategy.py) | `ProfessionalStrategist`, `ProfessionalStrategy` | **Abordagem profissional**: classifica o pedido (domínio, complexidade, especialidades, riscos, aceite) e devolve a estratégia executável, preservando a intenção original |
| [`tool_loop.py`](tool_loop.py) | `run_tool_loop`, `tool_schemas` | **Ciclo de ferramentas da operação**: o modelo inspeciona o projeto (`read_file`, `list_dir`, …) e/ou aplica a alteração (`write_file`, `edit_file`) pelo registro de ferramentas antes de responder; orçamento de leituras e resposta final forçada |
| [`decomposition.py`](decomposition.py) | `resolve_decomposition_plan` | **Decomposição hierárquica**: builtin e2e → modelo (Ollama/llama.cpp) → template genérico → mock; `apply_decomposition`, `seal_repeated_steps`, `plan_copies_siblings` |
| [`atomizer.py`](atomizer.py) | `adaptive_decompose_operation`, `micro_decompose_operation`, `should_decompose_further`, `depth_guard` | **Decomposição recursiva adaptativa**: escolhe a trilha pelo domínio (diagnóstico → correção → verificação) e protege profundidade e ciclos |
| [`plan_validation.py`](plan_validation.py) | `validate_and_repair`, `PlanValidation` | **Validação determinística do plano**: 16 regras (objetivo, etapas, requisitos, cobertura, dependências, ferramentas, duplicatas, orçamento) → veredito + fixes + blocked |
| [`consolidation.py`](consolidation.py) | `consolidate_parent`, `children_of`, `settled`, `verification_evidence_ok` | Consolida pai ← filhos concluídos com evidência válida |
| [`global_verify.py`](global_verify.py) | `evaluate_global_acceptance`, `reopen_verification_gaps`, `correct_requirement_gaps`, `ensure_global_verification_task` | **Aceite global por requisito**: run só completa se todo requisito obrigatório `satisfied` |
| [`requirements.py`](requirements.py) | `ensure_requirements`, `effective_covers`, `root_of`, `requirement_status` | Requisitos rastreáveis (derive do contrato/objetivo + cobertura declarada `covers`) |
| [`progress.py`](progress.py) | `progress_state`, `made_progress` | **Progresso real** (não atividade): mais tarefas verificadas ou menos pendências sem perder verificadas |
| [`stagnation.py`](stagnation.py) | `diagnose`, `limit_reached`, `error_signature`, `strategy_signature`, `repeated_failures` | Diagnóstico de estagnação (assinatura normalizada da falha + estratégia) |
| [`replan.py`](replan.py) | `replan_under`, `replan_decision` | Replanejamento dirigido por diagnóstico de estagnação |
| [`closing.py`](closing.py) | `compose_final_markdown`, `compose_incomplete_markdown`, `ensure_closing_stages` | Resposta final (markdown + fontes) ou mensagem de "não concluído" |
| [`usage.py`](usage.py) | `accumulate_usage`, `remember_usage` | Acúmulo de tokens (prompt + completion) por tarefa |
| [`resume.py`](resume.py) | `resume_root` | Resumo de onde parou (para UI: `POST /tasks/{id}/resume-brief`) |
| [`engine.py`](engine.py) | — | Legado mínimo (compatibilidade) |

## Fluxo de um Step (`RunOrchestrator.step`)

```mermaid
flowchart TD
  STEP[step(run_id)] --> LOAD[Carrega run + root_task + project]
  LOAD --> LIMITS{limit_reached?}
  LIMITS -->|sim| PAUSE[_pause_run: PAUSED + diagnóstico + próxima ação]
  LIMITS -->|não| REPLAN[replan_under: replaneja se diagnóstico novo]
  REPLAN -->|revisado| RET[retorna revised]
  REPLAN -->|sem mudanças| PICK[_pick_next_task: prioridade RUNNING>VERIFYING>READY>RETRY>PLANNING>PENDING]
  PICK -->|nenhuma| GLOBAL{ensure_global_verification_task}
  GLOBAL -->|adicionou| RET[global_verification_added]
  GLOBAL -->|nada| ALL_TERM{_all_terminal_under?}
  ALL_TERM -->|sim + COMPLETED| ACCEPT[evaluate_global_acceptance]
  ACCEPT -->|ok| FINAL[_ensure_final_message + COMPLETED]
  ACCEPT -->|falhou| REOPEN[reopen_verification_gaps / correct_requirement_gaps]
  ALL_TERM -->|não| STALL[_stall_run: FAILED + relatório]
  PICK -->|task| STATUS{task.status}
  STATUS -->|PENDING| PLANNING[update PLANNING + canonical_memory + requirements]
  STATUS -->|PLANNING| DECOMP{filhos?}
  DECOMP -->|sem filhos + executable_leaf| LEAF[_run_as_leaf: operation_ready]
  DECOMP -->|sem filhos| ATOMIZE{atomize ou tentativas≥2?}
  ATOMIZE -->|sim| MICRO[micro_decompose_operation]
  ATOMIZE -->|não| MODEL_PLAN[resolve_decomposition_plan com modelo]
  MODEL_PLAN --> APPLY[apply_decomposition + seal + validate]
  APPLY -->|válido| RET[decomposed]
  APPLY -->|inválido| BLOCK[_block_invalid_plan: BLOCKED + failure]
  DECOMP -->|com filhos| WAIT[planning_wait_children]
  STATUS -->|READY| PROMOTE[promote_ready_if_dependencies_met]
  STATUS -->|RUNNING| EXEC[_execute_task]
  EXEC -->|mcp_tool| MCP[McpManager.call_tool]
  EXEC -->|final_answer| FINAL_ANS[_write_final_answer]
  EXEC -->|model_operation| CTX[OperationContextBuilder.build_for_task]
  CTX --> PROV[observed_chat streaming]
  PROV --> PARSE[parse_json_object → edit_file/write_file]
  PARSE --> TOOL[ToolRegistry.execute]
  TOOL --> VERIF[_finalize_verification]
  EXEC -->|tool| TOOL2[ToolRegistry.execute]
  TOOL2 --> VERIF
  EXEC -->|verification| VERIF
  VERIF --> SPEC{spec?}
  SPEC -->|não| COMPLETED[completed_without_verification]
  SPEC -->|sim| RUN_VERIF[run_verification: pytest/script/command/file_contains/syntax]
  RUN_VERIF --> EVID[EvidenceModel + AttemptService.record]
  EVID -->|passed| COMPLETED2[COMPLETED + consolidate_parent]
  EVID -->|failed| RETRY[RETRY_PENDING + failure]
  EVID -->|blocked/inconclusive| BLOCKED2[BLOCKED + failure]
```

## Máquina de Estados (TaskStatus)

```
PENDING → PLANNING → READY → RUNNING → VERIFYING → COMPLETED
                    ↓           ↓           ↓
                   BLOCKED   RETRY_PENDING  BLOCKED
                    ↓           ↓
                  PLANNING   READY
                    ↓
                  CANCELLED (qualquer estado)
```

**Transições válidas** em [`domain/state_machine.py`](../domain/state_machine.py) — `InvalidTransitionError` se inválida.

## Decomposição — Ordem de Prioridade

1. **Builtin E2E** — objetivo contém `e2e` ou `calc.py` → plano fixo de 3 etapas (inspecionar, corrigir, testar)
2. **Direct Answer** — pergunta curta sem pedido de alteração → 1 etapa `final_answer`
3. **Modelo (Ollama/llama.cpp)** — `plan_with_model` com prompt estruturado (ferramentas, requisitos, capability_line)
4. **Template Genérico** — 3 etapas: inspecionar → aplicar (model_operation) → verificar (pytest)
5. **Mock Fallback** — se `ALLOW_MOCK_FALLBACK` ou provider=mock

> `align_verification`: pedidos de página/site trocam `pytest` por `file_contains <html>`.

## Estratégia Profissional e Decomposição Recursiva

Na raiz da run, `ProfessionalStrategist.analyze(objective)` classifica o pedido (domínio, complexidade,
especialidade líder, riscos, critérios de aceite) e grava a estratégia em
`task.metadata_json["professional_strategy"]`. Os filhos herdam `lead_specialty` e, quando a estratégia é
complexa, recebem `atomize: True` — o gatilho da decomposição interna.

| Trilha | Etapas geradas por `adaptive_decompose_operation()` |
|--------|------------------------------------------------------|
| `debugging_root_cause` | reproduzir e diagnosticar → corrigir na causa raiz → verificar não-regressão |
| `refactoring_clean_code` | inspecionar estrutura → refatorar incrementalmente → validar paridade |
| `technical_writing` | inspecionar referências → escrever → validar integridade |
| demais | inspecionar contexto → implementar → verificar |

Proteções: `max_tree_depth` (16), `max_tasks_per_run` (400), `depth_guard()` (repetição de título) e
`apply_decomposition()` (ignora dependência inválida ou circular — o plano nunca cria auto-ciclo).

Detalhes: [skills-estrategia.md](../../../docs/architecture/skills-estrategia.md)

## Validação do Plano (16 Regras Determinísticas)

| Categoria | Regra | Falha → |
|-----------|-------|---------|
| **Estrutura** | Objetivo global + critérios; requisito obrigatório com critério | `incompleto` |
| **Etapas** | Plano com etapas; cada etapa com resultado esperado | `incompleto` |
| **Cobertura** | Requisito obrigatório sem etapa responsável | `incompleto` |
| **Verificabilidade** | Etapa que cobre requisito sem critério verificável | `incompleto` |
| **Consistência** | Cobertura cita requisito inexistente | `inconsistente` |
| **Dependências** | Dependência inexistente, outro projeto, cancelada, circular, si mesma | `inconsistente` |
| **Duplicatas** | Etapa idêntica a outra (título, objetivo, tool, args) | `inconsistente` |
| **Ferramentas** | Ferramenta inexistente | `inconsistente` |
| **Ressalvas** | Tool precisa aprovação / browser off / external | `válido com ressalvas` (listada em `blocked`) |
| **Recursos** | Run passaria `MAX_TASKS_PER_RUN`; todas bloqueadas | `inviável` |

**Correção automática** (`validate_and_repair`): remove deps inválidas, cancela duplicata, tool inexistente → model_operation, requisito inexistente sai do `covers`, etapa sem critério vira apoio, requisito sem responsável ganha etapa `Atender Rn`.

## Verificação Independente (Proporcional ao Risco)

| Nível | Verificador | Quando |
|-------|-------------|--------|
| Estrutura/Arquivo | `file_contains` (lê arquivo inteiro como gravado) | Escrita de arquivo |
| Existência | `file_exists` (tamanho mínimo opcional) | Artefato que precisa existir |
| Sintaxe | `syntax` (Python `ast`, JSON) | `file_contains` com `syntax: true` |
| Lint estático | `static_analysis` (AST em todos os `.py` do caminho) | Verificação sem depender de ferramenta externa |
| Testes | `pytest`, `script`, `command` | Projetos com testes |
| Aceite Global | Etapa `Verificação global` (root `global_verification`) | Fim do run |

**Recuperação** (`verification/recovery.py`): verificação reprovada vira diagnóstico (causa + ação) e nova
tentativa com orientação no prompt — até `verification_max_recoveries` (2); depois disso, a tarefa é
bloqueada com diagnóstico, nunca reprovada em silêncio.

**Evidência** (`EvidenceModel`): `verifier`, `passed` (true/false/null), `summary`, `detail_json` (criteria, artifacts, exit_code, reason, state). Estado `desatualizado` marcado por `reopen_verification_gaps` se arquivo mudou.

## Estagnação, Limites, Pausa e Retomada

### Estagnação (`_check_stagnation`)
- Mesmo `signature` (categoria, causa, texto normalizado) + mesma `strategy` (tool/args/verification/mode) → conta repetição
- Atinge `attempts_per_strategy` (padrão 3) → `diagnose` (kind: contexto/planejamento/implementação/ferramenta/config/dependência/verificação)
- Se `automatic=true` + política de replan aceita → `stagnation_replan` (replaneja pai)
- Senão → `_pause_run` com diagnóstico

### Limites Operacionais (configuráveis por run em `config.limits`)

| Chave | Settings | Padrão | Ação ao Atingir |
|-------|----------|--------|-----------------|
| `attempts_per_strategy` | `max_attempts_per_strategy` | 3 | Estagnação → diagnóstico + replan/pausa |
| `steps_without_progress` | `max_steps_without_progress` | 60 | Pausa (progresso = `made_progress`) |
| `seconds` | `max_run_seconds` | 14400 | Pausa |
| `model_calls` | `max_model_calls_per_run` | 400 | Pausa |
| `tool_calls` | `max_tool_calls_per_run` | 600 | Pausa |
| `tokens` | `max_tokens_per_run` | 5M | Pausa |
| `replans` | `max_replans_per_run` | 80 | Pausa |

### Pausa (`_pause_run`)
- Run → `PAUSED` (nenhuma task muda de estado)
- Root `metadata.pause`: limite, valor, max, motivo, próxima ação, progresso, pendências, requisitos, diagnóstico
- Evento `run.paused` + mensagem "Não concluído" com "Próxima ação"

### Retomada (`POST /runs/{id}/resume`)
- Run → `ACTIVE`, pausa → `metadata.pauses`, **contadores reiniciam**
- `retry_blocked=true` → tasks `BLOCKED` → `PLANNING`
- Evidências desatualizadas reabertas no aceite global

## Testes-Chave

```bash
# Orquestrador E2E completo
pytest tests/test_e2e_orchestrator.py -v

# Decomposição + validação
pytest tests/test_decomposition.py tests/test_plan_validation.py -v

# Verificação independente
pytest tests/test_independent_verification.py tests/test_proportional_verification.py -v

# Requisitos + cobertura + global_verify
pytest tests/test_requirements.py tests/test_global_acceptance.py tests/test_global_verify.py -v

# Estagnação + limites + retomada
pytest tests/test_stagnation_limits.py tests/test_run_termination.py tests/test_resume_integrity.py -v

# Progresso real
pytest tests/test_progress_metrics.py -v
```

## Arquivos Relacionados Fora do `orchestrator/`

| Arquivo | Papel no Ciclo |
|---------|----------------|
| [`../services/task_service.py`](../services/task_service.py) | CRUD tasks + transições de status (valida `state_machine`) |
| [`../services/run_service.py`](../services/run_service.py) | CRUD runs + pause/resume/cancel |
| [`../services/attempt_service.py`](../services/attempt_service.py) | Tentativas: dedup (prompt_fp), fingerprint, contadores |
| [`../services/contract_service.py`](../services/contract_service.py) | Contratos (inputs/outputs/invariants/acceptance) |
| [`../services/autonomous_worker.py`](../services/autonomous_worker.py) | Loop background: `step()` runs autônomos a cada 2s |
| [`../context/operation_builder.py`](../context/operation_builder.py) | `OperationContextBuilder.build_for_task` (orçamento + ContextSnapshot) |
| [`../context/budget.py`](../context/budget.py) | `assemble_messages`, `compact_text`, `ContextBudgetError` |
| [`../verification/runner.py`](../verification/runner.py) | `run_verification` (pytest, script, command, file_contains, syntax) |
| [`../providers/ollama.py`](../providers/ollama.py) | Provider Ollama (HTTP + streaming real) |
| [`../providers/observed.py`](../providers/observed.py) | `observed_chat` (emite eventos streaming no EventBus) |
| [`../tools/registry.py`](../tools/registry.py) | `ToolRegistry.execute` (aliases, approval, eventos tool.*) |
| [`../observability/bus.py`](../observability/bus.py) | `EventBus` (ring, assinantes SSE, operations live) |

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Arquitetura:** [docs/architecture/visao-geral.md](../../../docs/architecture/visao-geral.md)