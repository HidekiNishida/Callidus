# Métricas — Inteligência e Observabilidade

Sistema de agregação de métricas de desempenho e consumo do Callidus. Todas as métricas são calculadas determinísticamente a partir de registros persistidos, sem dependência de modelos de linguagem.

## AnalyticsService

Ponto único de consulta de métricas. Métodos principais:

| Método | Retorna | Descrição |
|--------|---------|-----------|
| `token_metrics(...)` | dict | Consumo de tokens com qualidade de medição |
| `context_metrics(...)` | dict | Orçamento, ocupação e compactação de contexto |
| `inference_metrics(...)` | dict | Latência, taxa de erro, timeout, retry |
| `resource_metrics(...)` | dict | CPU, RAM, VRAM amostrados |
| `efficiency_metrics(...)` | dict | Tokens por tarefa, chamadas por tarefa, progresso |
| `overview(...)` | dict | Visão geral agregada para dashboard |

## Métricas de tokens

Todas as métricas de tokens informam a **origem e qualidade** da medição:

| Qualidade | Significado |
|-----------|-------------|
| `exact` | Valor informado pelo provedor, completo |
| `partial` | Parte informada pelo provedor, parte estimada |
| `estimate` | Estimativa local (caracteres/3) |
| `unavailable` | Nenhum dado disponível |

Campos:
- `prompt_tokens` / `prompt_measurement` / `prompt_missing`
- `completion_tokens` / `completion_measurement` / `completion_missing`
- `total_tokens` / `total_measurement`
- `reasoning_tokens`, `cache_read_tokens`, `cache_write_tokens` (mantidos separados do total)
- `estimated_prompt_tokens`, `estimated_completion_tokens`

**Estimativas nunca são somadas a valores reportados como se fossem equivalentes.** Cada métrica carrega seu campo de medição.

## Métricas de inferência

| Campo | Descrição |
|-------|-----------|
| `calls` | Total de chamadas |
| `completed` / `failed` / `timed_out` / `truncated` | Contagem por status |
| `error_rate` | Taxa de falha (0 a 1) |
| `timeout_rate` | Taxa de timeout (0 a 1) |
| `total_duration_ms` | Duração total acumulada |
| `duration_ms.p50/p95/p99/min/max` | Percentis de duração |
| `by_provider` | Agrupamento por provedor |

TTFT (Time to First Token) é capturado pela diferença entre `agent.started` e o primeiro `agent.output.delta`, quando disponível.

## Métricas de contexto

| Campo | Descrição |
|-------|-----------|
| `snapshots` | Número de snapshots de contexto |
| `estimated_tokens_total` | Soma de tokens estimados |
| `budget_pressure_count` | Número de ocorrências de pressão de orçamento |
| `compaction_events` | Número de compactações |
| `tokens_removed_estimated` | Tokens removidos por compactação |
| `occupancy_by_snapshot` | Série temporal de ocupação |

## Métricas de recursos

| Campo | Descrição |
|-------|-----------|
| `samples` | Número de amostras |
| `cpu_percent.avg/max/count` | CPU média, máxima, contagem |
| `ram_mb.avg/max/count` | RAM média, máxima, contagem |
| `vram_mb.avg/max/count` | VRAM média, máxima, contagem |

Coleta de GPU é independente do fornecedor: Apple Silicon, NVIDIA, AMD, CPU-only e servidores externos são suportados. Quando não há suporte, o campo é `null` (não zero).

## Métricas de eficiência

| Campo | Descrição |
|-------|-----------|
| `tasks_total/completed/failed/blocked` | Contagem por estado |
| `completion_rate` | Taxa de conclusão (0 a 1) |
| `tokens_per_completed_task` | Tokens por tarefa concluída |
| `calls_per_completed_task` | Chamadas por tarefa concluída |
| `calls_without_progress` | Chamadas sem progresso verificável |
| `progress_rate` | Taxa de progresso (chamadas produtivas / total) |
| `recovery_count` | Número de recuperações |

Uma chamada ao modelo não é considerada produtiva apenas por gerar resposta. O progresso está relacionado a mudanças verificáveis no estado da execução.

## Exemplos

```python
from agent.intelligence.analytics import AnalyticsService

analytics = AnalyticsService(session)

# Métricas de tokens de uma run
tokens = analytics.token_metrics(run_id=run_id)
print(f"Total: {tokens['total_tokens']} ({tokens['total_measurement']})")

# Visão geral do projeto
overview = analytics.overview(project_id=project_id)
print(f"Conclusão: {overview['completion_rate']:.1%}")
print(f"Modelos: {overview['models_used']}")
```
