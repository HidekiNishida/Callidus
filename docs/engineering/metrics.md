# Indicadores de entrega

Os indicadores que dizem se o Callidus entrega trabalho correto e comprovado — com numerador, denominador e tipo de medida.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Código: `AnalyticsService.delivery_metrics` em [analytics.py](/src/agent/intelligence/analytics.py) · API: `GET /api/intelligence/metrics/delivery?project_id=…`

## 📏 Indicadores

| Indicador | Numerador / denominador |
|-----------|-------------------------|
| Lead time | criação → conclusão verificada; P50 sempre, P95 com 20 amostras, P99 com 100 |
| First-pass acceptance | encerradas aprovadas sem reprovação antes / encerradas com evidência |
| Rework rate | com ao menos uma reprovação / com evidência |
| Regression rate | aprovadas que depois reprovaram / aprovadas ao menos uma vez |
| Recovery success | reprovadas que terminaram verificadas / reprovadas e encerradas |
| Verified throughput | concluídas cuja última evidência aprovou (contagem, com o total de tarefas) |
| Review latency | conclusão → primeira revisão registrada |
| Model efficiency | chamadas de modelo / tarefas verificadas |
| Context efficiency | já medido em [Consumo de contexto](/docs/architecture/observabilidade-contexto.md); não é duplicado |
| Defect escape rate | concluídas que uma revisão independente reprovou depois / concluídas revisadas |

Sem denominador, o indicador volta `kind: "unavailable"` e `value: null` — a interface mostra "indisponível", nunca zero.

## 🧭 O que não é medido de propósito

Quantidade de tarefas, chamadas ou linhas: premiar volume incentiva o agente a fragmentar trabalho. A métrica central é a entrega aprovada pela verificação independente. Os indicadores de tokens, contexto, inferência e recursos continuam nos endpoints de `/api/intelligence/metrics/*` ([docs/intelligence/metrics.md](/docs/intelligence/metrics.md)).
