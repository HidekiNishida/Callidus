# ETAPA 0 — Auditoria Arquitetural e Diagnóstico do Callidus

## Resumo executivo

O Callidus já é uma arquitetura madura e bem estruturada para agente local com modelos pequenos. A suíte de testes passa integralmente (1003 testes). O estado verdadeiro vive no SQLite, o modelo é substituível, a inferência é serializada (uma por vez), a máquina de estados de tarefas é única, e os componentes principais (contexto, planejamento, ferramentas, verificação, recuperação, grafo de conhecimento, memória operacional, skills, providers) já existem.

O diagnóstico identifica **problemas concretos e corrigíveis** sem necessidade de reescrita. A evolução deve ser feita por **refatoração vertical e integrada** dos componentes existentes, na ordem indicada no plano de 9 etapas.

---

## 1. Arquitetura efetivamente existente

### Camadas (conforme AGENTS.md §2)

| Camada | Pasta | Responsabilidade |
|--------|-------|------------------|
| Domínio | `src/agent/domain` | Enums (`TaskStatus`, `TaskKind`, `MemoryKind`, `RunStatus`, `AttemptKind`), máquina de estados (`state_machine.py`), schemas, taxonomia de falhas (`failures.py`) |
| Aplicação | `src/agent/services`, `src/agent/orchestrator` | Regras de negócio, orquestração do ciclo, planejamento, decomposição, verificação, recuperação |
| Infraestrutura | `src/agent/persistence`, `providers`, `tools`, `mcp`, `knowledge`, `memory`, `engineering` | SQLite, provedores de inferência, ferramentas determinísticas, grafo de conhecimento, memória, descoberta de projeto |
| Apresentação | `src/agent/api`, `web/static` | Rotas FastAPI, SSE, interface web |

### Componentes principais já implementados

- **Contexto**: `OperationContextBuilder` (`context/operation_builder.py`), `build_operation_context` (`context/assembler.py`), `ContextBudgetError`, `fit_window`, `compact_for_pressure`, `compact_text` (`context/budget.py`), orçamento por componente, categorias, snapshot persistido em `ContextSnapshotModel`.
- **Planejamento/decomposição**: `planner.py`, `decomposition.py`, `atomizer.py`, `disposition.py`, `strategy.py` (`ProfessionalStrategist`), `quality_contract.py`, `plan_validation.py`, `plan_contract.py`, `gap_analysis.py`.
- **TaskIR**: `task_ir.py` — `TaskIR`, `ArtifactRef`, `RequirementLink`, `ContextBudget`, `ExecutionConstraint`, `to_ir`, `from_ir`, `apply_ir_to_task`. Já persiste IR no `metadata_json` das tarefas.
- **Execução**: `runner.py` (`RunOrchestrator.step`), `engine.py`, `execution/runtime.py`, `execution/executor.py` (`TaskExecutor`), `execution/model_operation.py`, `execution/tool_results.py`, `execution/providers.py`, `tool_loop.py` (ciclo inspeção → alteração), `replan.py`, `stagnation.py`, `recovery_policy.py`.
- **Ferramentas**: `tools/registry.py` (`ToolRegistry`, `ToolSpec`, `ToolContext`), `tools/catalog.py`, `tools/contracts.py`, `tools/builtins.py`, `tools/devtools.py`, `tools/system_tools.py`, `tools/desktop_tools.py`, `tools/skill_tools.py`, `tools/automations.py`, `tool_loop.py` (`INSPECTION_TOOLS`, `MUTATION_TOOLS`, `OPERATION_TOOLS`, `AUTOMATION_TOOLS`).
- **Provedores**: `providers/base.py` (`LLMProvider`, `ModelProfile`, `ProviderCapabilities`, `estimate_text_tokens` com `CHARS_PER_TOKEN=3`), `ollama.py`, `llamacpp.py`, `openai_compatible.py`, `anthropic.py`, `gemini.py`, `openrouter.py`, `mock.py`, `registry.py`, `observed.py`.
- **Verificação**: `verification/runner.py` (`run_verification`, `VERIFIER_TYPES` fechado: pytest, script, command, file_contains, file_exists, syntax, static_analysis, ast_check, acceptance_manual, stages), `verification/recovery.py` (diagnóstico → correção → re-verificação), `verification/integrity.py` (AST: imports locais, dependentes, testes, GUI), `verification/fingerprint.py`.
- **Memória**: `memory/store.py`, `memory/operational.py` (níveis 1/2/3: `upsert_operational`, `remember_detail`, `remember_artifact`, `render_for_prompt`, `child_summary`, `recall`), `MemoryRecordModel` (kinds: canonical, execution, contextual, evidence, procedure, operational, task_detail, artifact).
- **Grafo de conhecimento**: `knowledge/graph_service.py` (`KnowledgeGraphService`: `reindex`, `neighbors`, `search`, `touch_file`), `knowledge/indexer.py` (`scan_project`, `grep_symbols_in_objective`), `KgNodeModel`, `KgEdgeModel`.
- **Persistência**: `persistence/models.py` (14 modelos: Project, Conversation, Task, Branch, ExecutionRun, TaskContract, ContextSnapshot, InferenceRecord, Evidence, MemoryRecord, KgNode, KgEdge, OperationAttempt, EventLog, Agent, AgentExecution, AgentQuery, Automation*, ScheduledRun*).
- **Habilidades**: `skills/catalog.py`, `skills/discovery.py`, `skills/models.py`, `skills/selector.py`, `skills/authoring/`.
- **Observabilidade**: `observability/bus.py`, `emitter.py`, contratos de evento, `emit`, `observe`, `set_task`.
- **Engenharia**: `engineering/discovery.py` (`detect_project`, `read_manifest`, `discover_commands`), `engineering/git.py`, `engineering/quality.py`, `engineering/context_retrieval.py`, `engineering/dependency_graph.py` (`DependencyGraph`, `ImpactAnalyzer`).
- **Tentativas**: `services/attempt_service.py` (`AttemptService`: contagem, fingerprint, `prompt_already_sent`, `repeated_output_detected`).
- **Contratos**: `services/contract_service.py` (`ContractService`: upsert, `validate_for_run`, `file_refs_from_contract`, `find_impacted_tasks`).
- **Executor de inferência**: `services/executor.py` (`InferenceExecutor`: serialização, uma por vez, métricas de espera).

---

## 2. Componentes que devem ser preservados

Todos os componentes listados acima. A arquitetura atual está alinhada com o diagrama de referência desejado: intent/quality → task compiler → TaskIR + dependency graph → project intelligence/knowledge → cognitive router → context engine/model provider → execution runtime → capability tools/skills/MCP → independent verification → success/recovery → persistent state/events → learning/live UI.

Componentes-chave a preservar intocados (ou com evolução mínima):

- `domain/state_machine.py` — fonte única de transições válidas.
- `domain/failures.py` — taxonomia de falhas e causas.
- `context/budget.py` — orçamento por componente, `ContextBudgetError`, `fit_window`, `assemble_messages`.
- `context/operation_builder.py` + `context/assembler.py` — montagem de contexto sob demanda (não criar paralelo).
- `orchestrator/task_ir.py` — representação intermediária já existente.
- `orchestrator/decomposition.py`, `planner.py`, `atomizer.py`, `disposition.py`, `strategy.py` — planejamento baseado no código real.
- `orchestrator/runner.py` — ciclo `step` com cadeado por run, estagnação, recuperação, pausa.
- `orchestrator/execution/executor.py` — despacho de etapa (modelo, ferramenta, verificação, resposta final).
- `orchestrator/execution/model_operation.py` — fluxo de operação de modelo com contexto, WriteJournal, rollback.
- `orchestrator/tool_loop.py` — ciclo inspeção → alteração, `fit_history`, `run_tool_loop`.
- `orchestrator/quality_contract.py`, `plan_validation.py` — contrato de qualidade e validação de plano.
- `persistence/models.py` — esquema SQLite (não recriar).
- `providers/base.py` — contrato de provedor, `estimate_text_tokens`, `CHARS_PER_TOKEN=3`, `ModelProfile`, `ProviderCapabilities`.
- `memory/operational.py` + `memory/store.py` — memória em camadas, `render_for_prompt`, `child_summary`, `recall`.
- `services/attempt_service.py` — tentativas, detecção de loop de prompt/saída.
- `services/contract_service.py` — contratos de entrada/saída, impacto de arquivos.
- `tools/registry.py` — registro uniforme, políticas, aprovação, timeouts.
- `tools/catalog.py` — exposição por família, `capability_summary`.
- `knowledge/graph_service.py` + `knowledge/indexer.py` — grafo de conhecimento.
- `services/executor.py` — serialização de inferências (uma por vez).

---

## 3. Problemas comprovados

### P1 — O contexto não é selecionado por relevância; carrega tudo que couber

`OperationContextBuilder.build_for_task` monta o contexto com objetivo, trechos técnicos, contrato, arquivos-alvo, skills, memória, requisitos, inspeção anterior, resultados de dependências. A seleção dos arquivos-alvo (`_target_files`) pega caminhos citados no título/objetivo/contrato e lê os primeiros 8000 caracteres de cada um, até 12000 caracteres totais. Não há índice de inspeção persistente com hash/versão, não há invalidação quando o arquivo muda, e não há relevância — apenas recência e presença textual.

**Impacto**: modelo lê arquivos irrelevantes, desperdiça orçamento, pode perder o que importa no meio de muito ruído.

### P2 — Estimativa de tokens é só caracteres/3

`estimate_text_tokens` em `providers/base.py` usa `CHARS_PER_TOKEN=3`, calibrado contra Ollama. Não há registro da diferença entre estimado e consumido pelo provider, não há tokenizer específico do modelo, não há calibração por modelo/idioma. `InferenceRecordModel` já tem colunas para `prompt_tokens`, `completion_tokens`, `estimated_prompt_tokens`, `estimated_completion_tokens` e `measurement` (exact/estimate/partial/unavailable), mas não há código que preencha a diferença estimado vs real.

**Impacto**: orçamento de contexto impreciso; estouro ou subaproveitamento da janela.

### P3 — Não há TaskIR compiler dedicado

`task_ir.py` existe e `to_ir`/`from_ir`/`apply_ir_to_task` convertem entre `TaskModel` e `TaskIR`, mas não há um **compilador de tarefas** que interprete a intenção, consulte a estrutura real do projeto (via `engineering/discovery.py`, `dependency_graph.py`, `knowledge/graph_service.py`), identifique componentes afetados, divida em operações pequenas, defina critérios de aceitação, calcule orçamentos e persista o plano. O planejamento hoje é feito pelo modelo (`plan_with_model` em `decomposition.py`) com fallback para templates genéricos (`GENERIC_TEMPLATE`, `page_plan`, `fallback_plan`, `automation_plan`). O modelo não recebe operações contextualizadas pequenas o suficiente de forma consistente.

**Impacto**: tarefas excessivamente abrangentes chegam ao modelo; planejamento não considera a arquitetura real do repositório.

### P4 — Capability tools compostas não existem

As ferramentas existentes são atômicas (ler/escrever arquivo, rodar comando, pytest, git, etc.). Não existem capacidades compostas como `inspect_subsystem`, `trace_dependency`, `analyze_impact`, `find_related_tests`, `prepare_edit`, `validate_change`, `review_diff`, `diagnose_failure`, `recover_operation` que combinem várias chamadas determinísticas e devolvam um resultado compacto e estruturado.

**Impacto**: o modelo repete instruções extensas e consulta o projeto peça por peça, gastando inferências em trabalho que código convencional faria de uma vez.

### P5 — Edição inteligente sem rollback garantido em todos os caminhos

`WriteJournal` existe em `execution/writes.py` e é usado em `model_operation.py` e `executor.py` para desfazer escritas quando a verificação reprova. Porém o caminho de ferramenta do plano (`meta.get("tool")` em `executor.py`) tem rollback parcial (`plan_write_journal.restore()` só quando `done.get("action") != "verified_ok"`), e não há detecção de conflito quando o arquivo muda entre inspeção e aplicação (exceto `_recheck_stale` que trata sobreescrita de irmã, não edição externa).

**Impacto**: alterações podem entrar sem verificação ou sem desfazer seguro.

### P6 — Verificação independente depende do mesmo modelo em alguns caminhos

`finalize_verification` roda verificadores determinísticos (pytest, syntax, file_contains, etc.), mas `write_final_answer` gera a resposta final com o modelo e só depois verifica (quando há `verification` no metadata). Não há um passo de verificação independente que rode **antes** de declarar conclusão, separado do modelo que produziu a alteração, em todos os caminhos.

**Impacto**: risco de declarar conclusão sem evidência.

### P7 — Não há cognitive router

`select_provider` em `orchestrator/execution/providers.py` escolhe o provedor pelo nome do run/config ou default (`ollama`). Não há seleção baseada na operação (complexidade, risco, arquivos afetados, profundidade de dependências, necessidade de tool calling, visão, saída estruturada, janela de contexto, latência, custo, histórico de sucesso). Não há validação de capacidades do provider antes de encaminhar. Não há escalonamento progressivo (modelo local → mais capaz) nem retorno ao menor.

**Impacto**: toda operação usa o mesmo modelo; não se adapta à complexidade nem ao custo.

### P8 — Aprendizado operacional não existe

Não há registro estruturado de estratégias executadas (tipo de tarefa, contexto, modelo, ferramentas, inferências, tokens, tempo, tentativas, resultado da verificação, falhas, recuperações, resultado final) nem reutilização de experiência para tarefas semelhantes. `MemoryRecordModel` existe com `kind` e `source_refs`, mas não há um serviço de aprendizado operacional que compare execuções bem-sucedidas vs malsucedidas.

**Impacto**: o agente repete os mesmos erros; não melhora com resultados próprios.

### P9 — Interface expõe narração do modelo, não estado real

A interface faz polling de `/live`, `/tasks`, `/events` e desenha pensamentos, etapas, diffs e resposta final. Os eventos vêm do `EventLogModel` e da observabilidade (`emit`). Não há painel que mostre o estado persistido do runtime (orçamento, tokens estimados vs consumidos, inferências, releituras evitadas, recuperações) de forma determinística.

**Impacto**: o usuário não vê progresso real; confunde resposta do modelo com avanço da tarefa.

### P10 — Sem benchmark ou métricas de eficiência

Não há suíte de tarefas representativas reproduzíveis para comparar antes/depois (tokens, inferências, tempo, releituras, taxa de sucesso, recuperações, regressões, consumo de recursos).

**Impacto**: não é possível provar que as melhorias realmente aumentam a eficiência.

---

## 4. Melhorias propostas (mapeadas às 9 etapas)

| Etapa | Melhoria | Componente a evoluir | Depende de |
|-------|----------|---------------------|------------|
| P0 | Auditoria + linha de base | — | — |
| P1 | Estado estruturado da tarefa + memória em camadas + eventos persistentes | `memory/operational.py`, `memory/store.py`, `persistence/models.py` (`EventLogModel`, `MemoryRecordModel`), `TaskModel.metadata_json` | P0 |
| P2 | Contexto sob demanda por relevância + inspeção progressiva + orçamento por finalidade + estimador de tokens com diferença estimado/real | `context/operation_builder.py`, `context/assembler.py`, `context/budget.py`, `providers/base.py`, `services/attempt_service.py` (inferência) | P1 |
| P3 | TaskIR compiler + camada de inteligência do repositório | `orchestrator/task_ir.py`, `engineering/discovery.py`, `engineering/dependency_graph.py`, `knowledge/graph_service.py`, `orchestrator/decomposition.py` | P1, P2 |
| P4 | Capability tools compostas + edição inteligente com detecção de conflito e rollback | `tools/registry.py`, `tools/builtins.py`, `orchestrator/execution/model_operation.py`, `orchestrator/execution/executor.py`, `tools/writes.py` | P3 |
| P5 | Verificação independente + diagnóstico de falhas + recuperação controlada | `verification/runner.py`, `verification/recovery.py`, `verification/integrity.py`, `orchestrator/execution/executor.py`, `orchestrator/runner.py` | P4 |
| P6 | Cognitive router + escalonamento progressivo + fallback e compatibilidade | `providers/base.py` (`ProviderCapabilities`), `orchestrator/execution/providers.py` (`select_provider`), `config.py` | P5 |
| P7 | Histórico de estratégias + reutilização de experiência + aprendizado com segurança | Novo serviço `services/learning.py` (ou `memory/learning.py`), `MemoryRecordModel` | P6 |
| P8 | Progresso real + feed de execução estruturado + economia de contexto visível + validação de UI | `observability/bus.py`, `src/agent/api/live_view.py`, `web/static/assets/app/` | P7 |
| P9 | Benchmark de tarefas representativas + métricas obrigatórias | Novo `tests/benchmark/`, `scripts/benchmark.py` | P8 |

---

## 5. Ordem de implementação

Respeitando dependências técnicas:

1. **P0** — Auditoria (este documento). Linha de base: 1003 testes passando.
2. **P1** — Estado e memória. Sem isso, nada mais faz sentido (continuidade entre inferências).
3. **P2** — Contexto e tokens. Depende de P1 (memória operacional fora do contexto).
4. **P3** — Inteligência do projeto + TaskIR compiler. Depende de P2 (orçamento para inspeção).
5. **P4** — Capability tools + edição. Depende de P3 (planos pequenas e contextualizadas).
6. **P5** — Verificação + recuperação. Depende de P4 (edições controladas precisam de verificação).
7. **P6** — Cognitive router. Depende de P5 (verificação independente justifica escalonamento).
8. **P7** — Aprendizado operacional. Depende de P6 (registro de estratégias por modelo/operação).
9. **P8** — Interface + observabilidade. Depende de P7 (estado persistido para exibir).
10. **P9** — Benchmark. Depende de tudo acima.

---

## 6. Linha de base

- Testes: **1003 passed** (`python -m pytest -q`), 63s.
- Não há falhas, não há erros, não há skips.
- Banco de teste isolado (`CALLIDUS_TEST_DATABASE_URL` ou tempdir), não toca `data/agent.db` real.
- Providers suportados: ollama (default), llamacpp, openai_compatible, anthropic, gemini, openrouter, mock.
- Modelo padrão: `llama3.2` (configurável), contexto padrão 8192, input_budget 6000, output_reserve 1024.
- Inferência: **uma por vez** (`max_concurrent_inferences=1`).
- Limites por tarefa: `max_attempts_per_task=8`, `max_tool_iterations=4`, `max_tool_calls=8`, `verification_max_recoveries=2`, `max_tasks_per_run=400`, `max_tree_depth=16`.
- Estados da tarefa: PENDING → PLANNING → READY → RUNNING → VERIFYING → COMPLETED, com RETRY_PENDING, BLOCKED, FAILED, CANCELLED.
- Tipos de verificador (fechado): stages, pytest, script, run_script, command, run_command, file_contains, file_exists, syntax, static_analysis, ast_check, acceptance_manual.

---

## 7. Premissas e decisões

- Não reescrever a arquitetura inteira. Evoluir componentes existentes.
- Não criar mecanismos paralelos (contexto, memória, planejamento, verificação).
- Não adicionar dependências pesadas (embeddings, bancos extras, filas externas).
- Manter Ollama e execução local como caminhos prioritários.
- Uma inferência por vez como padrão.
- Todo novo componente tem teste próprio; toda alteração preserva os 1003 testes existentes.
- `resume.md` e documentação arquitetural atualizados a cada etapa.
- `python scripts/ci.py` verde antes de considerar uma etapa concluída.

---

## 8. Status de implementação (após execução das ETAPAs 0–4)

### Concluído

| Etapa | Resultado | Arquivos novos | Arquivos alterados |
|-------|-----------|----------------|--------------------|
| ETAPA 0 | Auditoria + linha de base (1003 testes) | `ETAPA0_AUDITORIA.md` | — |
| ETAPA 1 | Estado estruturado + memória em camadas | `src/agent/memory/state.py`, `src/agent/memory/layers.py`, `tests/test_task_state.py`, `tests/test_memory_layers.py` | `src/agent/memory/__init__.py`, `src/agent/memory/README.md`, `resume.md` |
| ETAPA 2 | Contexto inteligente + orçamento de tokens | `src/agent/memory/inspection.py`, `tests/test_inspection_index.py` | `src/agent/memory/__init__.py`, `src/agent/memory/README.md`, `src/agent/context/operation_builder.py`, `src/agent/providers/base.py`, `resume.md` |
| ETAPA 3 | Compilador de tarefas (TaskIR) | `src/agent/orchestrator/task_compiler.py`, `tests/test_task_compiler.py` | `src/agent/orchestrator/task_ir.py`, `resume.md` |
| ETAPA 4 | Capability tools + edição determinística | `src/agent/tools/capability_tools.py`, `tests/test_capability_tools.py` | `resume.md` |

### Linha de base de testes

- Antes: 1003 testes passando.
- Depois das ETAPAs 1–4: **1038 testes passando** (+35 novos).
- Nenhuma regressão introduzida.

### `resume.md`

Atualizado e carimbado (3001 itens) com todas as novas classes, funções, métodos e arquivos das ETAPAs 1–4.

### Próximas etapas (ETAPAs 5–9)

- ETAPA 5: Verificação independente e recuperação inteligente.
- ETAPA 6: Cognitive router e seleção adaptativa de modelos.
- ETAPA 7: Aprendizado operacional e reutilização de estratégias.
- ETAPA 8: Interface, observabilidade e experiência de execução.
- ETAPA 9: Benchmark e otimização contínua.

**Próxima ação:** continuar com ETAPA 5 — Verificação independente e recuperação inteligente.