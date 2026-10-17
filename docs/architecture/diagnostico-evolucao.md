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

## Próximos incrementos

- Impacto de contratos via grafo ao alterar interfaces.
- Verificação global automática reabrindo subtarefas.
- Indexação multi-linguagem e relações `imports`/`calls` mais precisas.
- UI: visualização gráfica do grafo e diff de contexto por snapshot.

Ver também: [knowledge-graph.md](./knowledge-graph.md), [context-builder.md](./context-builder.md), [execucao-autonoma.md](./execucao-autonoma.md).
