# Diagnóstico e evolução (v0.5)

## Estado anterior (v0.4)

- Orquestrador explícito com decomposição (builtin E2E, Ollama, template, mock).
- Persistência SQLite: tarefas, runs, tentativas, evidências, memória.
- Ferramentas locais, verificação pytest, MCP stdio, UI web com árvore e inspetor.

## Lacunas endereçadas nesta evolução

| Responsabilidade | Módulo | Status |
|------------------|--------|--------|
| Planner persistente | `orchestrator/planner.py` + memória canônica | Parcial — objetivo canônico no root |
| Atomizador | `orchestrator/atomizer.py` | Micro-decomposição após falhas / flag `atomize` |
| Context Builder | `context/operation_builder.py` + snapshots | Operacional |
| Knowledge Graph | `knowledge/*` + SQLite `kg_*` | Indexação AST Python + API |
| Verifier | `verification/runner.py` | Existente; consolidação hierárquica incremental |
| Execução autônoma | `services/autonomous_worker.py` | Loop em background + API enable/disable |
| Contratos | `services/contract_service.py` | Validação quando `requires_contract` |
| Métricas | `services/metrics_service.py` | Agregados por projeto |

## Incrementos v0.5.1

- Consolidação exige evidência passante em subtarefas de verificação; reabertura hierárquica.
- Verificação global antes de `run_completed`; gaps reabrem tarefas de verificação.
- Contratos com detecção de impacto (`PUT /tasks/{id}/contract`) e bloqueio em `PLANNING → READY`.
- Grafo: arestas `imports` via AST.
- Máquina de estados: `COMPLETED → VERIFYING` para correções auditáveis.

## Próximos incrementos

- Indexação multi-linguagem e relações `calls` mais precisas.
- UI gráfica do grafo e diff de contexto por snapshot.
- Comparativo reproduzível decomposição vs contexto monolítico (métricas A/B).

Ver também: [knowledge-graph.md](./knowledge-graph.md), [context-builder.md](./context-builder.md), [execucao-autonoma.md](./execucao-autonoma.md).
