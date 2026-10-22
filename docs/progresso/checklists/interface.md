# Checklist — interface

O que a SPA precisa mostrar e em que estado cada parte está.

Voltar: [checklists/](/docs/progresso/checklists/README.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

**Resumo:** ~65 % (estimado), 10 h restantes. 57 testes da interface passam (*medido*).

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Conversa, feed e plano de subtarefas | acompanhar o trabalho ao vivo | implementado | ✅ |
| Histórico do feed ao reabrir | o feed volta como estava | reidrata a run mais recente | 🟡 [G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed) · 5 h |
| Narração junto da operação | cada explicação no item certo | sem `correlation_id`, cai na última linha | 🟡 [G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed) |
| Tokens ao vivo | ver a resposta chegando | não exposto | ☐ [G10](/docs/progresso/gaps.md#g10-streaming-de-tokens-na-interface) · 5 h |
| Provedores, automações e ajustes | administrar pela UI | implementado | ✅ |
| Inspetor (Detalhe, Tentativas, Diff) | conferir cada aba | não clicado exaustivamente na auditoria | 🟡 estimado |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação |
