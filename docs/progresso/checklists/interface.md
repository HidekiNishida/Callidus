# Checklist — interface

O que a SPA precisa mostrar e em que estado cada parte está.

Voltar: [checklists/](/docs/progresso/checklists/README.md)

> **Revisado em:** 2026-11-02 · **Atualizado em:** 2026-11-02 · **Mudança:** minor (narração em tempo real)

**Resumo:** ~70 % (estimado), 7 h restantes. 124 testes da interface passam (*medido*, 2026-11-02).

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Conversa, feed e plano de subtarefas | acompanhar o trabalho ao vivo | implementado | ✅ |
| Histórico do feed ao reabrir | o feed volta como estava | reidrata a run mais recente | 🟡 [G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed) · 5 h |
| Narração junto da operação | cada explicação no item certo | sem `correlation_id`, cai na última linha | 🟡 [G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed) |
| Narração ao vivo | ver o agente explicar enquanto trabalha | fala pública do modelo em tempo real na linha do tempo; depende de o modelo escrever prosa | 🟡 [G10](/docs/progresso/gaps.md#g10-streaming-de-tokens-na-interface) · 2 h |
| Provedores, automações e ajustes | administrar pela UI | implementado | ✅ |
| Inspetor (Detalhe, Tentativas, Diff) | conferir cada aba | não clicado exaustivamente na auditoria | 🟡 estimado |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-11-02 | minor | Narração em tempo real; testes da interface recontados |
| 2026-10-21 | major | Criação |
