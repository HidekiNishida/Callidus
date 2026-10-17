# Context Builder por operação

Cada chamada ao modelo para uma tarefa passa por `OperationContextBuilder`, que monta mensagens mínimas e persiste um `ContextSnapshotModel`.

## Entradas

- Memória canônica do projeto (até 5 registros recentes).
- Objetivo e critérios da tarefa.
- Trechos técnicos (arquivos/símbolos sugeridos pelo grafo).
- Guias do repositório na raiz: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, Copilot, `.cursor/rules`, `llms.txt`, índice de `SKILL.md`. Um `AGENTS.md` de subpasta entra só se o pedido cita essa pasta.
- Regras globais fixas e resumo de ferramentas autorizadas.

A resposta final usa os formatos que o chat desenha (título, lista, tabela, código, mermaid e fontes). Visão só entra se o id do modelo indica um modelo visual.

## Orçamento

`build_operation_context` aplica limite do `ModelProfile`, reserva de saída e estratégias de redução (duplicações, truncamento documentado em `strategy_notes_json`).

## Inspeção

- `GET /tasks/{id}/context-snapshots`
- `GET /context-snapshots/{id}`
- Aba **Contexto** na UI web.

Código: [operation_builder.py](/src/agent/context/operation_builder.py)
