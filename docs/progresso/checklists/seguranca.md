# Checklist — segurança

Permissões, segredos e proteção dos dados do usuário.

Voltar: [checklists/](/docs/progresso/checklists/README.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

**Resumo:** ~60 % (estimado), 8 h restantes.

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Pedido somente leitura | nenhuma escrita | vira permissão de ferramenta; 3/3 (*medido*) | ✅ |
| Ferramenta arriscada | aprovação item a item | só a flag `approve_risky_tools` por run | ☐ [G4](/docs/progresso/gaps.md#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui) · 8 h |
| Credenciais de provedor | nunca expostas | testes de segurança de provedor | ✅ |
| Banco do usuário | nunca apagado nem migrado à força | testes em banco temporário; sem fiscal automático | 🟡 [G6](/docs/progresso/gaps.md#g6-fiscais-automáticos-das-regras-de-engenharia) |
| Remoção em cascata | sem linha pendurada; 409 em vez de 500 | implementado | ✅ |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação |
