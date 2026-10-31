/**
 * Arquivo: web/static/assets/app/components/intelligence-pages.js
 * Nome: intelligence-pages.js
 * Propósito: páginas da área Callidus Intelligence (Overview, Performance, Benchmarks, Diagnostics).
 * Responsabilidade: frontend/componente — consome a API unificada de inteligência e renderiza métricas, gráficos e tabelas.
 * Componentes: IntelligenceOverview, IntelligencePerformance, IntelligenceBenchmarks, IntelligenceDiagnostics.
 * Dependências: `../store.js` (estado e ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: gráficos em SVG leve, sem dependências externas; paginação e filtros via query params.
 */
import { state, loadIntelligenceOverview, loadRunMetrics, loadBenchmarkScenarios, runBenchmark, loadBenchmarkResults, compareBenchmarks, loadDiagnostics, loadDiagnosticsSummary, analyzeRunDiagnostics } from "../store.js";
import { icon } from "../ui.js";

const PERCENTILE_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

/**
 * Página Overview: métricas gerais do workspace e runs recentes.
 */
export const IntelligenceOverview = {
  name: "IntelligenceOverview",
  setup() {
    const loading = Vue.ref(false);

    async function load() {
      loading.value = true;
      await loadIntelligenceOverview();
      loading.value = false;
    }

    Vue.onMounted(load);

    return {
      state,
      loading,
      load,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Overview</h1>
        <p class="page-sub">Métricas agregadas de execução, consumo e desempenho do Callidus.</p>
        <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
      </div>

      <div v-if="!loading && state.intelligenceOverview" class="metrics-grid">
        <div class="metric-card">
          <div class="metric-value">{{ state.intelligenceOverview.runs_total }}</div>
          <div class="metric-label">Runs totais</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ (state.intelligenceOverview.completion_rate * 100).toFixed(1) }}%</div>
          <div class="metric-label">Taxa de conclusão</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ state.intelligenceOverview.tokens.total_tokens || 0 }}</div>
          <div class="metric-label">Tokens totais</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ state.intelligenceOverview.inference.calls }}</div>
          <div class="metric-label">Chamadas ao modelo</div>
        </div>
      </div>

      <div v-if="!loading && state.intelligenceOverview" class="charts-row">
        <div class="chart-panel">
          <h3>Modelos utilizados</h3>
          <div class="bar-chart" v-if="state.intelligenceOverview.models_used">
            <div v-for="(count, model) in state.intelligenceOverview.models_used" :key="model" class="bar-item">
              <span class="bar-label">{{ model }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.intelligenceOverview.models_used)) * 100) + '%' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
        </div>
        <div class="chart-panel">
          <h3>Provedores</h3>
          <div class="bar-chart" v-if="state.intelligenceOverview.providers_used">
            <div v-for="(count, provider) in state.intelligenceOverview.providers_used" :key="provider" class="bar-item">
              <span class="bar-label">{{ provider }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.intelligenceOverview.providers_used)) * 100) + '%' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!loading && state.intelligenceOverview" class="table-panel">
        <h3>Runs recentes</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Provedor</th>
              <th>Modelo</th>
              <th>Criada em</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in state.intelligenceOverview.recent_runs" :key="run.id">
              <td class="mono">{{ run.id.slice(0, 8) }}</td>
              <td><span class="status-badge" :class="`status-${run.status.toLowerCase()}`">{{ run.status }}</span></td>
              <td>{{ run.provider }}</td>
              <td>{{ run.model }}</td>
              <td>{{ run.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};

/**
 * Página Performance: gráficos de tokens, contexto, inferência e eficiência por run.
 */
export const IntelligencePerformance = {
  name: "IntelligencePerformance",
  props: {
    runId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);

    async function load() {
      loading.value = true;
      if (props.runId) {
        await loadRunMetrics(props.runId);
      } else {
        await loadIntelligenceOverview();
      }
      loading.value = false;
    }

    Vue.onMounted(load);
    Vue.watch(() => props.runId, load);

    return {
      state,
      loading,
      load,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Performance</h1>
        <p class="page-sub">Métricas de desempenho por run: tokens, contexto, inferência, recursos e eficiência.</p>
        <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>
      </div>

      <div v-if="!loading" class="metrics-grid">
        <div v-if="state.runMetrics" class="metric-card">
          <div class="metric-value">{{ state.runMetrics.tokens.total_tokens || 0 }}</div>
          <div class="metric-label">Tokens totais (run)</div>
        </div>
        <div v-if="state.runMetrics" class="metric-card">
          <div class="metric-value">{{ state.runMetrics.inference.calls }}</div>
          <div class="metric-label">Chamadas ao modelo</div>
        </div>
        <div v-if="state.runMetrics" class="metric-card">
          <div class="metric-value">{{ (state.runMetrics.efficiency.completion_rate * 100).toFixed(1) }}%</div>
          <div class="metric-label">Taxa de conclusão</div>
        </div>
        <div v-if="state.runMetrics" class="metric-card">
          <div class="metric-value">{{ state.runMetrics.resources.samples }}</div>
          <div class="metric-label">Amostras de recurso</div>
        </div>
      </div>

      <div v-if="!loading && state.runMetrics" class="charts-row">
        <div class="chart-panel">
          <h3>Tokens por medição</h3>
          <div class="metric-detail">
            <div><span>Entrada:</span> <span class="mono">{{ state.runMetrics.tokens.prompt_tokens || 0 }} ({{ state.runMetrics.tokens.prompt_measurement }})</span></div>
            <div><span>Saída:</span> <span class="mono">{{ state.runMetrics.tokens.completion_tokens || 0 }} ({{ state.runMetrics.tokens.completion_measurement }})</span></div>
            <div><span>Total:</span> <span class="mono">{{ state.runMetrics.tokens.total_tokens || 0 }} ({{ state.runMetrics.tokens.total_measurement }})</span></div>
          </div>
        </div>
        <div class="chart-panel">
          <h3>Latência de inferência</h3>
          <div class="metric-detail">
            <div><span>P50:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p50 || 0 }}ms</span></div>
            <div><span>P95:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p95 || 0 }}ms</span></div>
            <div><span>P99:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p99 || 0 }}ms</span></div>
            <div><span>Erros:</span> <span class="mono">{{ (state.runMetrics.inference.error_rate * 100).toFixed(1) }}%</span></div>
          </div>
        </div>
      </div>

      <div v-if="!loading && state.runMetrics" class="table-panel">
        <h3>Consumo por provedor</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>Provedor</th>
              <th>Chamadas</th>
              <th>Falhas</th>
              <th>Timeouts</th>
              <th>Taxa de erro</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(data, provider) in state.runMetrics.inference.by_provider" :key="provider">
              <td>{{ provider }}</td>
              <td>{{ data.calls }}</td>
              <td>{{ data.failed }}</td>
              <td>{{ data.timeout }}</td>
              <td>{{ (data.error_rate * 100).toFixed(1) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};

/**
 * Página Benchmarks: catálogo de cenários, execução e comparação.
 */
export const IntelligenceBenchmarks = {
  name: "IntelligenceBenchmarks",
  setup() {
    const loading = Vue.ref(false);
    const selectedScenario = Vue.ref(null);
    const benchmarkConfig = Vue.ref({ provider: "", model_id: "", config: {} });

    async function load() {
      loading.value = true;
      await loadBenchmarkScenarios();
      loading.value = false;
    }

    async function runSelected() {
      if (!selectedScenario.value) return;
      loading.value = true;
      const result = await runBenchmark(selectedScenario.value.id, benchmarkConfig.value);
      loading.value = false;
      if (result) {
        await loadBenchmarkResults(selectedScenario.value.id);
      }
    }

    Vue.onMounted(load);

    return {
      state,
      loading,
      selectedScenario,
      benchmarkConfig,
      load,
      runSelected,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Benchmarks</h1>
        <p class="page-sub">Laboratório de testes e comparações entre modelos e configurações arquiteturais.</p>
        <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
      </div>

      <div class="bench-layout">
        <div class="bench-sidebar">
          <h3>Cenários</h3>
          <div v-if="loading" class="skeleton-line"></div>
          <div v-if="!loading" class="scenario-list">
            <div
              v-for="sc in state.benchmarkScenarios"
              :key="sc.id"
              class="scenario-item"
              :class="{ selected: selectedScenario?.id === sc.id }"
              @click="selectedScenario = sc"
            >
              <div class="scenario-name">{{ sc.name }}</div>
              <div class="scenario-meta">
                <span class="badge">{{ sc.category }}</span>
                <span class="badge">{{ sc.difficulty }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="bench-main">
          <div v-if="!selectedScenario" class="empty-state">
            <p>Selecione um cenário para ver detalhes e executar.</p>
          </div>
          <div v-else class="scenario-detail">
            <h3>{{ selectedScenario.name }}</h3>
            <p>{{ selectedScenario.description }}</p>
            <div class="scenario-meta">
              <span><strong>Categoria:</strong> {{ selectedScenario.category }}</span>
              <span><strong>Dificuldade:</strong> {{ selectedScenario.dificuldade || selectedScenario.difficulty }}</span>
              <span><strong>Orçamento de tokens:</strong> {{ selectedScenario.token_budget || '—' }}</span>
            </div>
            <div class="scenario-prompt">
              <strong>Objetivo:</strong> {{ selectedScenario.prompt }}
            </div>

            <div class="bench-actions">
              <label class="field">
                <span>Provedor</span>
                <select v-model="benchmarkConfig.provider">
                  <option value="ollama">Ollama</option>
                  <option value="llamacpp">llama.cpp</option>
                  <option value="mock">Mock</option>
                </select>
              </label>
              <label class="field">
                <span>Modelo</span>
                <input v-model="benchmarkConfig.model_id" type="text" placeholder="ex.: llama3.2" />
              </label>
              <button type="button" class="btn-primary" @click="runSelected" :disabled="loading">
                {{ loading ? 'Executando…' : 'Executar benchmark' }}
              </button>
            </div>

            <div v-if="state.lastBenchmarkResult" class="result-card">
              <h4>Última execução</h4>
              <div class="metric-detail">
                <div><span>Concluída:</span> <span class="mono">{{ state.lastBenchmarkResult.task_completed ? 'Sim' : 'Não' }}</span></div>
                <div><span>Tokens:</span> <span class="mono">{{ state.lastBenchmarkResult.total_tokens }}</span></div>
                <div><span>Tempo:</span> <span class="mono">{{ state.lastBenchmarkResult.total_time_seconds.toFixed(2) }}s</span></div>
                <div><span>Pontuação geral:</span> <span class="mono">{{ ((state.lastBenchmarkResult.scores?.reduce((s, d) => s + d.score, 0) || 0) / (state.lastBenchmarkResult.scores?.length || 1)).toFixed(1) }}</span></div>
              </div>
            </div>

            <div v-if="state.benchmarkResults.length" class="table-panel">
              <h3>Resultados</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Execução</th>
                    <th>Provedor</th>
                    <th>Modelo</th>
                    <th>Status</th>
                    <th>Tokens</th>
                    <th>Tempo (s)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in state.benchmarkResults" :key="r.execution_id">
                    <td class="mono">{{ r.execution_id.slice(0, 8) }}</td>
                    <td>{{ r.provider }}</td>
                    <td>{{ r.model_id }}</td>
                    <td>{{ r.status }}</td>
                    <td>{{ r.total_tokens }}</td>
                    <td>{{ r.total_time_seconds.toFixed(2) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};

/**
 * Página Diagnostics: problemas identificados, gargalos e recomendações.
 */
export const IntelligenceDiagnostics = {
  name: "IntelligenceDiagnostics",
  props: {
    runId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);

    async function load() {
      loading.value = true;
      await loadDiagnostics(props.runId || null);
      await loadDiagnosticsSummary(props.runId || null);
      loading.value = false;
    }

    async function analyze() {
      if (!props.runId) return;
      loading.value = true;
      await analyzeRunDiagnostics(props.runId);
      await loadDiagnostics(props.runId);
      loading.value = false;
    }

    Vue.onMounted(load);
    Vue.watch(() => props.runId, load);

    return {
      state,
      loading,
      load,
      analyze,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Diagnósticos</h1>
        <p class="page-sub">Problemas identificados, gargalos e recomendações a partir de evidências.</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
          <button
            v-if="props.runId"
            type="button"
            class="btn-secondary"
            @click="analyze"
            :disabled="loading"
            v-html="icon('bug', 16)"
          >
            Analisar run
          </button>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>
      </div>

      <div v-if="!loading && state.diagnosticsSummary" class="summary-cards">
        <div class="metric-card">
          <div class="metric-value">{{ state.diagnosticsSummary.total }}</div>
          <div class="metric-label">Diagnósticos</div>
        </div>
        <div class="metric-card">
          <div class="metric-value" style="color: #ef4444">{{ state.diagnosticsSummary.critical }}</div>
          <div class="metric-label">Críticos</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ state.diagnosticsSummary.open }}</div>
          <div class="metric-label">Abertos</div>
        </div>
      </div>

      <div v-if="!loading && state.diagnosticsSummary" class="charts-row">
        <div class="chart-panel">
          <h3>Por categoria</h3>
          <div class="bar-chart">
            <div v-for="(count, cat) in state.diagnosticsSummary.by_category" :key="cat" class="bar-item">
              <span class="bar-label">{{ cat }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.diagnosticsSummary.by_category)) * 100) + '%' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
        </div>
        <div class="chart-panel">
          <h3>Por severidade</h3>
          <div class="bar-chart">
            <div v-for="(count, sev) in state.diagnosticsSummary.by_severity" :key="sev" class="bar-item">
              <span class="bar-label">{{ sev }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.diagnosticsSummary.by_severity)) * 100) + '%', backgroundColor: sev === 'critica' ? '#ef4444' : sev === 'alta' ? '#f59e0b' : '#3b82f6' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!loading" class="table-panel">
        <h3>Detalhes</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>Categoria</th>
              <th>Severidade</th>
              <th>Estado</th>
              <th>Métrica afetada</th>
              <th>Causa provável</th>
              <th>Recomendação</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in state.diagnostics" :key="d.id">
              <td>{{ d.category }}</td>
              <td><span class="severity-badge" :class="`sev-${d.severity}`">{{ d.severity }}</span></td>
              <td><span class="status-badge" :class="`status-${d.state}`">{{ d.state }}</span></td>
              <td class="mono">{{ d.metric_affected || '—' }}</td>
              <td>{{ d.probable_cause || '—' }}</td>
              <td>{{ d.recommendation || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};
