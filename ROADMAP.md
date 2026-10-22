# Roadmap do Callidus

Em que estágio o Callidus está e quanto falta para o próximo.

Detalhes: [docs/progresso/](/docs/progresso/README.md) · Fila: [gaps.md](/docs/progresso/gaps.md) · Formato: [progresso.md](/docs/regras/progresso.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

**Estágio:** alpha · **Próximo:** beta (critérios propostos, aguardando o dono)

## 📊 Números principais

| | Valor | Tipo |
|---|-------|------|
| Fluxos centrais que passam no portão do alpha | 6 / 6 (1 com ressalvas) | medido |
| Cenários aceitos com o modelo local (`gpt-oss:20b`) | 15 / 15 | medido (2026-10-20) |
| Testes Python / testes da interface | 847 funções `test_` / 57 passam | medido (2026-10-21) |
| Qualidade geral | ~61 % | estimado |
| Horas até o beta | ~43 h | estimado |
| Horas para fechar toda a fila | ~117 h | estimado |

## 📐 Por dimensão

| Dimensão | % | Horas | Checklist |
|----------|---|-------|-----------|
| Funcionalidades | ~60 | 58 | [funcionalidades.md](/docs/progresso/checklists/funcionalidades.md) |
| Interface | ~65 | 10 | [interface.md](/docs/progresso/checklists/interface.md) |
| Desempenho | ~45 | 10 | [desempenho.md](/docs/progresso/checklists/desempenho.md) |
| Segurança | ~60 | 8 | [seguranca.md](/docs/progresso/checklists/seguranca.md) |
| Plataformas | ~50 | 23 | [plataformas.md](/docs/progresso/checklists/plataformas.md) |
| Qualidade | ~80 | 8 | [qualidade.md](/docs/progresso/checklists/qualidade.md) |

## ⏭️ Próximos

1. [G1 Avaliação real ampla e repetível](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) — sem ela, toda nota é estimativa.
2. [G2 Decomposição em repositórios grandes](/docs/progresso/gaps.md#g2-decomposição-em-repositórios-grandes)
3. [G3 Recuperação quando a verificação reprova](/docs/progresso/gaps.md#g3-recuperação-quando-a-verificação-reprova)
4. [G4 Aprovação granular de ferramentas arriscadas na UI](/docs/progresso/gaps.md#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui)

## 📝 Log de progresso

| Data | O que entrou |
|------|--------------|
| 2026-10-21 | Documentos de progresso, comando único de verificação (`python scripts/ci.py`), ritual de sessão e decisões do dono no [AGENTS.md](/AGENTS.md) |
| 2026-10-21 | Automação de sistema/desktop, tarefas agendadas pela conversa, piso de qualidade, feed com narração |
| 2026-10-20 | Estratégia de resolução medida: −34 % de chamadas ao modelo, 15/15 aceitos |
| 2026-10-17 | Fatia vertical: núcleo persistente, orquestrador, ferramentas, UI e E2E |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação a partir do kit de agentes de IA |
