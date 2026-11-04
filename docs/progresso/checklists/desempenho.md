# Checklist — desempenho

Custo e aceite do Callidus com o modelo local real.

Voltar: [checklists/](/docs/progresso/checklists/README.md) · Medição: [avaliacao.md](/docs/architecture/avaliacao.md)

> **Revisado em:** 2026-11-04 · **Atualizado em:** 2026-11-04 · **Mudança:** minor (comparação antes/depois adicionada; amostra ampla ainda parcial)

**Resumo:** ~45 % (estimado), 10 h restantes.

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Aceite nos cenários curtos | todos aceitos | 15/15 com `gpt-oss:20b` (*medido*, 2026-10-20) | ✅ |
| Custo da falha | parar cedo na repetição improdutiva | metade das chamadas na falha de formato (*medido*) | ✅ |
| Comparação da organização de engenharia | mesmo modelo/script, ≥3 rodadas por lado | `gpt-oss:20b`, 3 × 6 cenários; 14/18→13/18 conclusão, 18/21→16/21 requisitos; inconclusiva | 🟡 [benchmarking.md](/docs/engineering/benchmarking.md#-organização-de-engenharia--antes-e-depois-2026-11-04) |
| Sessão longa de produção | aceite e custo medidos | não medido | ☐ [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) · 10 h |
| Amostra ampla | ≥ 3 rodadas, ≥ 15 cenários | missão: 3 × 6 cenários; amostra ampla ainda insuficiente | 🟡 [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) |
| Tokens do provedor | medidos, não estimados | só estimativa de contexto | ☐ [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) |
| Disposição de qualidade | comparada com o modelo local | não medida | ☐ [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação |
