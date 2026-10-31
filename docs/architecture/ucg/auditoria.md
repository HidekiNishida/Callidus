# Auditoria do Unified Cognitive Graph (UCG)

Inventário da arquitetura vigente do Callidus, dos problemas comprovados e da evolução proposta para o UCG.

## Sumário

1. [Contexto da auditoria](#contextodaauditoria)
2. [Inventário por domínio](#inventáriopordomínio)
3. [Duplicações identificadas](#duplicaçõesidentificadas)
4. [Problemas comprovados](#problemascomprovadosmapeadosàsetapas)
5. [Linha de base de testes](#linhadebasedetestes)
6. [Evolução proposta](#evoluçãopropostaordemdedependência)

## Contexto da auditoria

O Callidus já é um agente local maduro com 1003 testes passando (baseline antes das ETAPAs 1–4) e 1038 após as ETAPAs 1–4, sem regressões. O estado verdadeiro vive no SQLite (`data/agent.db`), o modelo é substituível, a inferência é serializada (uma por vez) e a máquina de estados de tarefas é única.

Os componentes principais já existem:

- Contexto: `context/operation_builder.py`, `context/assembler.py`, `context/budget.py` (`ContextBudgetError`, `fit_window`, orçamento por componente).
- Planejamento/decomposição: `orchestrator/task_ir.py`, `orchestrator/task_compiler.py` (ETAPA 3), `orchestrator/decomposition.py`, `orchestrator/planner.py`, `orchestrator/strategy.py`.
- Execução: `orchestrator/runner.py`, `orchestrator/execution/executor.py`, `orchestrator/execution/model_operation.py`, `orchestrator/tool_loop.py`.
- Ferramentas: `tools/registry.py`, `tools/catalog.py`, `tools/capability_tools.py` (ETAPA 4), `tools/builtins.py`.
- Provedores: `providers/base.py` (`LLMProvider`, `estimate_text_tokens`), `providers/registry.py`.
- Verificação: `verification/runner.py`, `verification/recovery.py`, `verification/integrity.py`, `verification/fingerprint.py`.
- Memória: `memory/store.py`, `memory/operational.py`, `memory/state.py` (ETAPA 1), `memory/layers.py` (ETAPA 1), `memory/inspection.py` (ETAPA 2).
- Grafo de conhecimento: `knowledge/graph_service.py`, `knowledge/indexer.py`, modelos `KgNodeModel`/`KgEdgeModel`.
- Habilidades: `src/agent/skills/catalog/`, `src/agent/skills/discovery.py`, `src/agent/skills/models.py`, `src/agent/skills/selector.py`.
- MCP: `mcp/manager.py`, `mcp/config_models.py`.
- Observabilidade: `observability/bus.py`, `observability/emitter.py`.

## Inventário por domínio

| Item | Situação atual | Problema | Evolução proposta |
|------|----------------|----------|-------------------|
| Knowledge Graph | `knowledge/graph_service.py` com `KgNodeModel`/`KgEdgeModel`; busca textual simples sobre `ref`/`label`; reindexação substitui todo o grafo do projeto. | Sem tipos de relação controlados, sem validação de aresta (origem/destino permitidos), sem proveniência, sem validade temporal, sem índice de inspeção persistente entre reindexações. | Camada UCG sobre as mesmas tabelas: vocabulário de relações tipado, validação de aresta, metadados de proveniência e validade nos metadados JSON existentes. |
| Memory | `memory/store.py`, `memory/operational.py` (níveis 1/2/3), `memory/state.py` (TaskStateService), `memory/layers.py` (camadas imediata/tarefa/projeto/arquivo), `memory/inspection.py` (hash + relevância). | Memórias não se relacionam entre si; não há grafo de relações entre memória, tarefa e arquivos; promoção de episódica para semântica não é controlada; não há detecção de conflitos de validade. | Memory Graph sobre `memory_records` com relações tipadas para tarefas, arquivos e decisões; validade e confiança nos metadados; promoção controlada por validação. |
| Context Builder | `context/operation_builder.py` monta contexto com objetivo, contrato, arquivos-alvo (primeiros 8000 caracteres, até 12000 totais), skills e memória. `_target_files` usa recência e presença textual, não relevância. | Carrega tudo que couber; sem índice de inspeção com hash/versão; sem invalidação quando o arquivo muda; sem relevância. | PCR integrado ao `InspectionIndex` existente (hash, relevância, cache) e ao `TaskStateService`, carregando conteúdo integral apenas do selecionado. |
| Skills | `src/agent/skills/catalog/`, `src/agent/skills/discovery.py`, `src/agent/skills/selector.py`, `src/agent/skills/authoring/`. | Catálogo não é grafo de capacidades com dependências, permissões, custo, disponibilidade com TTL ou aplicabilidade por ambiente. | Capability Graph integrando skills, MCPs e ferramentas como nós com relações `USES`, `REQUIRES`, `IMPLEMENTS`, `VALIDATED_BY`. |
| MCP | `mcp/manager.py`, `mcp/config_models.py`; registros de servidor e ferramentas. | Disponibilidade registrada sem TTL; não vinculada a capacidades nem invalidada quando o servidor sai do ar. | Nós `MCP` no Capability Graph com relação `AVAILABLE_TO` e TTL de disponibilidade. |
| Task Graph | `orchestrator/task_ir.py` (TaskIR com operações, dependências, orçamento), `TaskDependencyModel`, `task_compiler.py` (ETAPA 3). | Árvore pai/filho existe, mas o grafo de dependências não é usado para seleção de contexto mínimo nem para reutilização de resultados entre tarefas equivalentes. | Execution Graph sobre `TaskDependencyModel` + `TaskModel`, com fingerprints de artefatos e idempotência para reutilização segura. |
| Verification | `verification/runner.py` (verificadores fechados), `verification/recovery.py`, `verification/integrity.py`, `verification/fingerprint.py`, `services/attempt_service.py`. | Verificação existe, mas não há registro estruturado de decisões, hipóteses e alternativas com evidências vinculadas à tarefa. | Decision Graph sobre `evidence` e `memory_records` (decisão, hipótese, alternativa, evidência, resultado). |

## Duplicações identificadas

- `TaskModel.metadata_json` armazena inspeção, cache, orçamento e tentativa em campos sobrepostos (`inspection`, `cache`, `failures`, `pending_edits`). Não há duplicação de tabela, mas há campos com semânticas distintas misturados em JSON. Mantido por compatibilidade; o UCG lê via `TaskStateService` sem criar tabelas paralelas.
- `KnowledgeItemModel`/`KnowledgeRelationModel` (camada knowledge) e `KgNodeModel`/`KgEdgeModel` (grafo do projeto) tratam de entes semelhantes em tabelas diferentes. O UCG usa `KgNodeModel`/`KgEdgeModel` como fonte para o grafo do projeto e não duplica registros.

## Problemas comprovados (mapeados às ETAPAs)

| Problema | Componente afetado | Impacto | Status |
|----------|--------------------|---------|--------|
| Contexto não selecionado por relevância; carrega tudo que couber | `context/operation_builder.py` | Modelo lê arquivos irrelevantes, desperdiça orçamento | ETAPA 2 (inspeção + relevância) concluída; integração UCG em andamento |
| Estimativa de tokens só caracteres/3 | `providers/base.py` | Orçamento impreciso | Registro estimado vs real pendente (`InferenceRecordModel` já tem as colunas) |
| Não há TaskIR compiler dedicado | `orchestrator/task_ir.py` (conversão sem interpretação de intenção) | Tarefas amplas chegam ao modelo | ETAPA 3 concluída (`task_compiler.py`) |
| Capability tools compostas não existem | `tools/*` atômicas | Modelo repete instruções extensas | ETAPA 4 concluída (`capability_tools.py`) |
| Não há cognitive router | `providers/registry.py`, `select_provider` | Todo operação usa o mesmo modelo | Pendente (ETAPA 6 do plano de auditoria) |
| Aprendizado operacional não existe | `MemoryRecordModel` sem serviço de aprendizado | Repetição de erros | Pendente (ETAPA 7 do plano de auditoria) |
| Sem benchmark de eficiência | — | Não é possível provar ganho | Pendente (ETAPA 9 do plano de auditoria) |

## Linha de base de testes

- Antes das ETAPAs 1–4: **1003 testes passando** (`python -m pytest -q`), 63s, sem falhas, sem erros, sem skips.
- Após ETAPAs 1–4: **1038 testes passando** (+35 novos), sem regressão introduzida.
- Banco de teste isolado (`CALLIDUS_TEST_DATABASE_URL` ou tmp_path), não toca `data/agent.db` real.
- `python scripts/ci.py` verde antes de considerar uma etapa concluída.

## Evolução proposta (ordem de dependência)

| Fase | Entrega | Depende de |
|------|---------|------------|
| Fase 0 | Auditoria + docs/architecture/ucg/ | — |
| Fase 1 | Contrato e modelo do UCG (tipos de nó, relacionamento, proveniência, escopo) | Fase 0 |
| Fase 2 | Graph Foundation + Graph Query Engine (consulta seletiva com limites) | Fase 1 |
| Fase 3 | Progressive Context Reduction (descoberta seletiva de capacidades) | Fase 2 |
| Fase 4 | Capability Graph — Skills, MCPs e ferramentas | Fase 3 |
| Fase 5 | Memory Graph (camadas, validade, promoção) | Fase 3 |
| Fase 6 | Execution Graph e orquestração (DAG, checkpoints, reutilização) | Fase 4, Fase 5 |
| Fase 7 | Agent Graph (perfis, seleção, handoff) | Fase 6 |
| Fase 8 | Knowledge Gap Resolver + Research Graph | Fase 2, Fase 5 |
| Fase 9 | Decision Graph (decisões, hipóteses, evidências) | Fase 5 |
| Fase 10 | Quality Graph (critérios antecipados, evidências) | Fase 6, Fase 9 |
| Fase 11 | Strategy Graph (estratégias, aprendizado) | Fase 10 |
| Fase 12 | Observabilidade e interface | Fase 11 |
| Fase 13 | Benchmark, estabilização e ativação gradual | todas |

A ordem de detalhes internos pode ser ajustada quando houver dependências comprovadas, mas nenhum domínio ou critério é eliminado sem justificativa registrada em [decisoes.md](decisoes.md).

## Verificação

```bash
source .venv/bin/activate && python scripts/ci.py --rapido
python -m pytest tests/test_knowledge_graph.py tests/test_task_state.py tests/test_memory_layers.py tests/test_inspection_index.py tests/test_task_compiler.py tests/test_capability_tools.py -q
```

## Links cruzados

- [roadmap do UCG](roadmap.md)
- [decisões do UCG](decisoes.md)
- [auditoria anterior (ETAPA 0)](../../../ETAPA0_AUDITORIA.md)
- [Hub de regras](../../regras/README.md)
