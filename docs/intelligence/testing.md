# Testes — Inteligência e Observabilidade

Suíte de testes para todos os subsistemas de inteligência.

## Testes de backend

| Arquivo | Escopo |
|---------|--------|
| `tests/test_intelligence_telemetry.py` | TelemetryService, eventos tipados, correlação |
| `tests/test_intelligence_analytics.py` | AnalyticsService, métricas de tokens, contexto, inferência, recursos, eficiência |
| `tests/test_intelligence_graph.py` | CognitiveGraph, topologia, estados, arestas, aplicação de eventos |
| `tests/test_intelligence_benchmarks.py` | BenchmarkEngine, cenários, execuções, resultados, comparação, pontuação |
| `tests/test_intelligence_diagnostics.py` | DiagnosticEngine, categorias, severidades, detecção automática |

## Executar

```bash
# Todos os testes de inteligência
python -m pytest tests/test_intelligence_*.py -v

# Um subsistema específico
python -m pytest tests/test_intelligence_telemetry.py -v

# Suíte completa (inclui inteligência)
python -m pytest -q
```

## Casos extremos cobertos

- Zero tokens, métricas ausentes, valores nulos
- Contagens estimadas vs reportadas
- Provedor indisponível, execução interrompida
- Run retomada, contexto excedido
- Banco reiniciado (banco em memória por teste)
- Grande quantidade de eventos (paginação)

## Testes de frontend

Não há testes de frontend automatizados nesta fase. A validação visual e funcional deve ser feita acessando a interface em `http://127.0.0.1:8765/` e verificando:

- Renderização dos gráficos SVG
- Atualizações em tempo real via SSE
- Filtros e comparações
- Estados vazios e de erro
- Reconexão SSE
- Navegação entre páginas
- Responsividade em telas pequenas

## Determinismo

Todos os testes usam banco SQLite em memória, sem rede, sem credencial real e sem relógio real. Os resultados são determinísticos.
