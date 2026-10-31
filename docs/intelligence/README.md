# Inteligência e Observabilidade

Índice da documentação do sistema de inteligência operacional e observabilidade do Callidus.

## Sumário

| Documento | Finalidade | Quando consultar |
|-----------|-----------|-----------------|
| [architecture.md](./architecture.md) | Visão geral da arquitetura e camadas | Entender como os subsistemas se conectam |
| [telemetry.md](./telemetry.md) | Contrato de telemetria, eventos, correlação | Implementar ou consumir eventos de execução |
| [metrics.md](./metrics.md) | Métricas de tokens, contexto, inferência, recursos, eficiência | Consultar agregações e percentis |
| [cognitive-graph.md](./cognitive-graph.md) | Grafo cognitivo dinâmico, topologia, estados | Visualizar o fluxo de execução real |
| [benchmarks.md](./benchmarks.md) | Engine de benchmarking, cenários, pontuação | Comparar modelos e arquiteturas |
| [diagnostics.md](./diagnostics.md) | Motor de diagnóstico, gargalos, recomendações | Identificar problemas e oportunidades |
| [api.md](./api.md) | Endpoints unificados de inteligência | Integrar sistemas externos |
| [frontend.md](./frontend.md) | Páginas e componentes da interface | Entender a visualização de dados |
| [testing.md](./testing.md) | Testes de backend e frontend | Validar alterações |

## Subsistemas

O sistema de inteligência é composto por cinco subsistemas integrados:

1. **Telemetria** — coleta padronizada de eventos de execução com contrato tipado e versionado.
2. **Analytics** — agregação de métricas de tokens, contexto, inferência, recursos e eficiência.
3. **Cognitive Graph** — representação visual dinâmica da arquitetura percorrida pelo agente.
4. **Benchmark Engine** — laboratório de testes comparativos entre modelos e configurações.
5. **Diagnostic Engine** — identificação determinística de gargalos e oportunidades de otimização.

Todos os dados são persistidos no SQLite e disponibilizados por API HTTP e SSE, sem depender de modelos de linguagem para cálculos determinísticos.

## Princípios

- **Complexidade na arquitetura, não no prompt:** métricas e diagnósticos são calculados deterministicamente.
- **Origem da métrica explícita:** estimativas nunca são confundidas com valores reportados pelo provedor.
- **Sem dependência externa:** o sistema funciona 100% offline, sem servidores de monitoramento obrigatórios.
- **Falha de telemetria não bloqueia execução:** erros de coleta são absorvidos sem afetar o agente.

## Início rápido

```python
from agent.intelligence import TelemetryService, AnalyticsService, CognitiveGraph
from agent.persistence.database import build_session_factory, init_db
from sqlalchemy import create_engine

engine = create_engine("sqlite:///:memory:")
init_db(engine)
SessionLocal = build_session_factory(engine)
session = SessionLocal()

telemetry = TelemetryService(session)
analytics = AnalyticsService(session)
graph = CognitiveGraph(session, run_id=run_id)
```
