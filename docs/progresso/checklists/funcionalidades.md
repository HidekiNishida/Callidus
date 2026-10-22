# Checklist — funcionalidades

O que o agente precisa fazer e em que estado cada capacidade está.

Voltar: [checklists/](/docs/progresso/checklists/README.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

**Resumo:** ~60 % (estimado), 58 h restantes.

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Plano e decomposição | pedido vira tarefas atômicas verificáveis | micro-plano determinístico + decomposição hierárquica | ✅ |
| Decomposição em repositório grande | plano útil sem estourar o contexto | reserva genérica e grossa | ☐ [G2](/docs/progresso/gaps.md#g2-decomposição-em-repositórios-grandes) · 16 h |
| Verificação independente | quem executa não aprova | aceite global por requisito | ✅ |
| Recuperação da verificação | estratégia alternativa quando reprova | reexecuta o mesmo verificador | ☐ [G3](/docs/progresso/gaps.md#g3-recuperação-quando-a-verificação-reprova) · 8 h |
| Estagnação e retomada | não repetir o improdutivo; retomar após falha | memória de abordagem, limite por problema, pausa | ✅ |
| Seleção de skills e estratégia | escolher pela intenção | lexical, domínios fixos | 🟡 [G7](/docs/progresso/gaps.md#g7-seleção-lexical-de-skills-estratégia-e-consulta) · 12 h |
| Grafo de conhecimento | várias linguagens, relações precisas | Python-first, heurístico | 🟡 [G8](/docs/progresso/gaps.md#g8-grafo-de-conhecimento-multi-linguagem) · 14 h |
| Contratos | impacto propagado | validação manual | 🟡 [G9](/docs/progresso/gaps.md#g9-propagação-de-impacto-de-contratos) · 8 h |
| Hierarquia de agentes | consulta e execução separadas | implementada e medida (13/15) | ✅ |
| Automações persistentes | agendar e administrar pela conversa | implementadas com testes | ✅ |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação |
