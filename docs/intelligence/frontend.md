# Frontend — Callidus Intelligence

Área integrada na interface existente do Callidus, reutilizando a SPA Vue 3, sistema visual e componentes já existentes.

## Páginas

| Página | Componente | Descrição |
|--------|------------|-----------|
| Overview | `IntelligenceOverview` | Execuções recentes, taxa de conclusão, tokens, modelos, recursos |
| Live Architecture | `CognitiveGraphView` | Grafo cognitivo com estados e arestas percorridas |
| Performance | `IntelligencePerformance` | Gráficos de tokens, contexto, inferência, eficiência |
| Benchmarks | `IntelligenceBenchmarks` | Catálogo de cenários, execução, comparação |
| Diagnostics | `IntelligenceDiagnostics` | Problemas identificados, gargalos, recomendações |

## Navegação

As páginas são acessíveis pela barra de navegação inferior da interface, ao lado de Conversa, Execução, Provedores, Automações e Ajustes.

## Visualizações

Os gráficos são renderizados em SVG leve, sem dependências externas:

- **Barras:** modelos utilizados, provedores, diagnósticos por categoria/severidade
- **Detalhes métricas:** tokens por medição, latência por percentil
- **Tabelas:** runs recentes, consumo por provedor, resultados de benchmark, detalhes de diagnóstico

Cada gráfico exibe unidade, período, origem e descrição. Métricas sem amostras suficientes não são exibidas como conclusivas.

## Estados

O frontend respeita:
- `prefers-reduced-motion`: animações desativadas quando o usuário preferir
- Tema claro/escuro: variáveis CSS do sistema
- Responsividade: layout adapta-se a telas pequenas
- Reconexão SSE: o grafo e métricas se reconectam automaticamente após interrupção

## Integração com a API

Todas as páginas consomem a API unificada em `/api/intelligence/*`. Nenhuma métrica é calculada exclusivamente no frontend.

## Componentes

| Componente | Arquivo | Responsabilidade |
|------------|---------|-----------------|
| `CognitiveGraphView` | `intelligence-graph.js` | Grafo SVG interativo com painel de detalhes |
| `IntelligenceOverview` | `intelligence-pages.js` | Visão geral com cards de métrica |
| `IntelligencePerformance` | `intelligence-pages.js` | Gráficos de desempenho por run |
| `IntelligenceBenchmarks` | `intelligence-pages.js` | Laboratório de benchmarks |
| `IntelligenceDiagnostics` | `intelligence-pages.js` | Lista e resumo de diagnósticos |

## Store

Ações adicionadas em `store.js`:
- `loadIntelligenceOverview()` — métricas gerais
- `loadRunMetrics(runId)` — métricas de uma run
- `loadArchitectureGraph()` — grafo da arquitetura
- `loadRunGraph(runId)` — grafo de uma run
- `loadRunGraphHistory(runId)` — histórico de eventos
- `loadBenchmarkScenarios()` — catálogo de cenários
- `runBenchmark(scenarioId, config)` — executa benchmark
- `loadBenchmarkResults(scenarioId)` — resultados
- `compareBenchmarks(scenarioId, executionIds)` — comparação
- `loadDiagnostics(runId)` — lista diagnósticos
- `analyzeRunDiagnostics(runId)` — diagnóstico automático
- `loadDiagnosticsSummary(runId)` — resumo
