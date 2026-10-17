# Context Builder por operação

Cada chamada ao modelo para uma tarefa passa por `OperationContextBuilder`, que monta mensagens mínimas e persiste um `ContextSnapshotModel`.

## Entradas

- Memória canônica do projeto (até 5 registros recentes).
- Objetivo e critérios da tarefa.
- Trechos técnicos (arquivos/símbolos sugeridos pelo grafo).
- Regras globais fixas e resumo de ferramentas autorizadas.

## Orçamento

`build_operation_context` aplica limite do `ModelProfile`, reserva de saída e estratégias de redução (duplicações, truncamento documentado em `strategy_notes_json`).

## Inspeção

- `GET /tasks/{id}/context-snapshots`
- `GET /context-snapshots/{id}`
- Aba **Contexto** na UI web.

Código: [operation_builder.py](/src/agent/context/operation_builder.py)
