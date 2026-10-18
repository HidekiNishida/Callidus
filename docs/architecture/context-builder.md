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

`build_operation_context` aplica limite do `ModelProfile`, reserva de saída e margem de segurança (256 tokens). Regras globais, objetivo, critérios e formato de saída são **obrigatórios**; regras do projeto, contexto técnico e ferramentas entram se couberem, e os omitidos ficam em `refs_json` e `strategy_notes_json`.

### Quando o obrigatório não cabe

1. `assemble_messages` lança `ContextBudgetError` com o custo de cada componente.
2. O builder grava um snapshot do estouro (`strategy_notes_json` começa com `estouro:`).
3. O runner tenta de novo com `compact=True`: `compact_text` tira espaços repetidos, linhas em branco seguidas e linhas duplicadas, sem cortar conteúdo.
4. Se ainda não couber, nada é enviado ao modelo: a tentativa vira falha `change_strategy/context_budget`, a tarefa passa a `BLOCKED` com a explicação (parte maior, tokens, orçamento) e a ação é `blocked_context`. Conteúdo obrigatório nunca é truncado para caber.

## Inspeção

- `GET /tasks/{id}/context-snapshots`
- `GET /context-snapshots/{id}`
- Aba **Contexto** na UI web.

Código: [operation_builder.py](/src/agent/context/operation_builder.py)
