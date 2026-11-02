/**
 * Arquivo: web/static/assets/app/components/intelligence-pages.js
 * Nome: intelligence-pages.js
 * Propósito: páginas da área Callidus Intelligence (Overview, Performance, Benchmarks, Diagnostics).
 * Responsabilidade: frontend/componente — consome a API unificada de inteligência e renderiza métricas, gráficos e tabelas.
 * Componentes: IntelligenceOverview, IntelligencePerformance, IntelligenceBenchmarks, IntelligenceDiagnostics.
 * Dependências: `../store.js` (estado e ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: gráficos em SVG leve, sem dependências externas; paginação e filtros via query params.
 */
import { state, loadIntelligenceOverview, loadRunMetrics, loadBenchmarkScenarios, runBenchmark, loadBenchmarkResults, compareBenchmarks, loadDiagnostics, loadDiagnosticsSummary, analyzeRunDiagnostics, loadContextConsumptionOverview, loadContextConsumptionByType, loadContextConsumptionByComponent, loadContextConsumptionMatrix, loadContextConsumptionCompare, loadContextConsumptionTimeline, loadContextConsumptionOpportunities } from "../store.js";
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

      <div v-if="!loading && !state.intelligenceOverview" class="empty-state">
        <p>Nenhuma métrica disponível. Execute alguma tarefa para gerar dados.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
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
          <p v-else class="muted small">Nenhum modelo registrado ainda.</p>
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
          <p v-else class="muted small">Nenhum provedor registrado ainda.</p>
        </div>
      </div>

      <div v-if="!loading && state.intelligenceOverview" class="table-panel">
        <h3>Runs recentes</h3>
        <table class="data-table" v-if="state.intelligenceOverview.recent_runs?.length">
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th><span class="picker-ico" v-html="icon('server', 13)"></span></th>
              <th><span class="picker-ico" v-html="icon('spark', 13)"></span></th>
              <th>Criada em</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in state.intelligenceOverview.recent_runs" :key="run.id">
              <td class="mono">{{ run.id.slice(0, 8) }}</td>
              <td><span class="status-badge" :class="'status-' + run.status.toLowerCase()">{{ run.status }}</span></td>
              <td>{{ run.provider }}</td>
              <td>{{ run.model }}</td>
              <td>{{ run.created_at }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted small">Nenhuma run recente.</p>
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

      <div v-if="!loading && !state.runMetrics" class="empty-state">
        <p>Selecione uma execução no acompanhamento ou execute uma tarefa para ver métricas de desempenho.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && state.runMetrics" class="metrics-grid">
        <div class="metric-card">
          <div class="metric-value">{{ state.runMetrics.tokens.total_tokens || 0 }}</div>
          <div class="metric-label">Tokens totais (run)</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ state.runMetrics.inference.calls }}</div>
          <div class="metric-label">Chamadas ao modelo</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ (state.runMetrics.efficiency.completion_rate * 100).toFixed(1) }}%</div>
          <div class="metric-label">Taxa de conclusão</div>
        </div>
        <div class="metric-card">
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
        <table class="data-table" v-if="state.runMetrics.inference.by_provider && Object.keys(state.runMetrics.inference.by_provider).length">
          <thead>
            <tr>
              <th><span class="picker-ico" v-html="icon('server', 13)"></span></th>
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
        <p v-else class="muted small">Nenhum dado de provedor disponível.</p>
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
          <div v-if="!loading && state.benchmarkScenarios?.length" class="scenario-list">
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
          <p v-if="!loading && !state.benchmarkScenarios?.length" class="muted small">Nenhum cenário disponível. Crie um via API ou adicione ao banco.</p>
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
                <span class="picker-ico" v-html="icon('server', 13)"></span>
                <select v-model="benchmarkConfig.provider">
                  <option value="ollama">Ollama</option>
                  <option value="llamacpp">llama.cpp</option>
                  <option value="mock">Mock</option>
                </select>
              </label>
              <label class="field">
                <span class="picker-ico" v-html="icon('spark', 13)"></span>
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
                    <th><span class="picker-ico" v-html="icon('server', 13)"></span></th>
                    <th><span class="picker-ico" v-html="icon('spark', 13)"></span></th>
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
            <p v-else class="muted small">Nenhum resultado ainda. Execute o benchmark para ver resultados.</p>
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
      runId: props.runId,
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
            v-if="runId"
            type="button"
            class="btn-secondary"
            @click="analyze"
            :disabled="loading"
          >
            <span v-html="icon('bug', 16)"></span>
            Analisar run
          </button>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>
      </div>

      <div v-if="!loading && !state.diagnosticsSummary" class="empty-state">
        <p>Nenhum diagnóstico disponível. Execute uma tarefa e use "Analisar run" para gerar diagnósticos.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
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
          <div class="bar-chart" v-if="state.diagnosticsSummary.by_category && Object.keys(state.diagnosticsSummary.by_category).length">
            <div v-for="(count, cat) in state.diagnosticsSummary.by_category" :key="cat" class="bar-item">
              <span class="bar-label">{{ cat }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.diagnosticsSummary.by_category)) * 100) + '%' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
          <p v-else class="muted small">Nenhuma categoria registrada.</p>
        </div>
        <div class="chart-panel">
          <h3>Por severidade</h3>
          <div class="bar-chart" v-if="state.diagnosticsSummary.by_severity && Object.keys(state.diagnosticsSummary.by_severity).length">
            <div v-for="(count, sev) in state.diagnosticsSummary.by_severity" :key="sev" class="bar-item">
              <span class="bar-label">{{ sev }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(state.diagnosticsSummary.by_severity)) * 100) + '%', backgroundColor: sev === 'critica' ? '#ef4444' : sev === 'alta' ? '#f59e0b' : '#3b82f6' }"></div>
              </div>
              <span class="bar-value">{{ count }}</span>
            </div>
          </div>
          <p v-else class="muted small">Nenhuma severidade registrada.</p>
        </div>
      </div>

      <div v-if="!loading" class="table-panel">
        <h3>Detalhes</h3>
        <table class="data-table" v-if="state.diagnostics?.length">
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
              <td><span class="severity-badge" :class="'sev-' + d.severity">{{ d.severity }}</span></td>
              <td><span class="status-badge" :class="'status-' + d.state">{{ d.state }}</span></td>
              <td class="mono">{{ d.metric_affected || '—' }}</td>
              <td>{{ d.probable_cause || '—' }}</td>
              <td>{{ d.recommendation || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted small">Nenhum diagnóstico para exibir.</p>
      </div>
    </div>
  `,
};

/**
 * Página Consumo e Gestão de Contexto: consumo e tokens por inferência.
 */
export const IntelligenceContextConsumption = {
  name: "IntelligenceContextConsumption",
  props: {
    runId: { type: String, default: null },
    projectId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);

    async function load() {
      loading.value = true;
      await Promise.all([
        loadContextConsumptionOverview(props.runId || null, props.projectId || null),
        loadContextConsumptionByType(props.runId || null, props.projectId || null),
        loadContextConsumptionByComponent(props.runId || null, props.projectId || null),
        loadContextConsumptionMatrix(props.runId || null, props.projectId || null),
        loadContextConsumptionCompare(props.runId || null, props.projectId || null, "model"),
        loadContextConsumptionTimeline(props.runId || null, props.projectId || null, "day"),
        loadContextConsumptionOpportunities(props.runId || null, props.projectId || null),
      ]);
      loading.value = false;
    }

    Vue.onMounted(load);
    Vue.watch(() => props.runId, load);
    Vue.watch(() => props.projectId, load);

    const barColor = (value, max) => (max ? Math.min(100, (value / max) * 100) : 0) + "%";
    const maxTypeTotal = Vue.computed(() => {
      const groups = state.contextConsumptionByType?.groups || [];
      return groups.reduce((max, g) => Math.max(max, g.total_tokens.value || 0), 0);
    });

    return {
      state,
      loading,
      load,
      icon,
      barColor,
      maxTypeTotal,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Consumo e Gestão de Contexto</h1>
        <p class="page-sub">Medição, classificação e otimização do consumo de contexto e tokens por inferência.</p>
        <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>
      </div>

      <div v-if="!loading && !state.contextConsumptionOverview" class="empty-state">
        <p>Nenhum dado de consumo disponível. Execute alguma tarefa para gerar inferências.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && state.contextConsumptionOverview" class="section-panel">
        <h3>Visão geral</h3>
        <div class="metrics-grid">
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.input_tokens.value ?? 0 }}</div>
            <div class="metric-label">Tokens de entrada</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.input_tokens.measurement }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.output_tokens.value ?? 0 }}</div>
            <div class="metric-label">Tokens de saída</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.output_tokens.measurement }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.total_tokens.value ?? 0 }}</div>
            <div class="metric-label">Tokens totais</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.total_tokens.measurement }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.inferences_total }}</div>
            <div class="metric-label">Inferências totais</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ (state.contextConsumptionOverview.avg_tokens_per_inference.mean ?? 0).toFixed(0) }}</div>
            <div class="metric-label">Média de tokens por inferência</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.avg_tokens_per_inference.count }} amostra(s)</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.avg_window_occupancy_pct.value ?? 0 }}%</div>
            <div class="metric-label">Janela média utilizada</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.avg_window_occupancy_pct.count }} amostra(s)</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.compaction.events }}</div>
            <div class="metric-label">Compactações</div>
            <div class="metric-note small">{{ state.contextConsumptionOverview.compaction.tokens_removed_estimated }} tokens removidos</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.contextConsumptionOverview.tokens_saved_estimated }}</div>
            <div class="metric-label">Tokens economizados (est.)</div>
          </div>
        </div>

        <div class="table-panel" style="margin-top: 16px;">
          <h4>Consumo por status</h4>
          <table class="data-table">
            <thead>
              <tr><th>Status</th><th>Quantidade</th></tr>
            </thead>
            <tbody>
              <tr v-for="(count, status) in state.contextConsumptionOverview.by_status" :key="status">
                <td>{{ status }}</td>
                <td>{{ count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionByType" class="section-panel">
        <h3>Consumo por tipo de inferência</h3>
        <div class="charts-row">
          <div class="chart-panel">
            <h4>Tokens totais por tipo</h4>
            <div class="bar-chart">
              <div v-for="g in state.contextConsumptionByType.groups" :key="g.type" class="bar-item">
                <span class="bar-label">{{ g.label }}</span>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: barColor(g.total_tokens.value || 0, maxTypeTotal) + '%' }"></div>
                </div>
                <span class="bar-value">{{ g.total_tokens.value ?? 0 }}</span>
              </div>
            </div>
            <p v-if="!state.contextConsumptionByType.groups?.length" class="muted small">Sem dados.</p>
          </div>
          <div class="chart-panel">
            <h4>Estatísticas por tipo</h4>
            <table class="data-table">
              <thead>
                <tr>
                  <th>Tipo</th><th>Amostras</th><th>Média</th><th>Mediana</th><th>P90</th><th>P95</th><th>Mín.</th><th>Máx.</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="g in state.contextConsumptionByType.groups" :key="g.type">
                  <td>{{ g.label }}</td>
                  <td>{{ g.total_tokens.count }}</td>
                  <td class="mono">{{ g.total_tokens.mean ?? 0 }}</td>
                  <td class="mono">{{ g.total_tokens.median ?? 0 }}</td>
                  <td class="mono">{{ g.total_tokens.p90 ?? '—' }}</td>
                  <td class="mono">{{ g.total_tokens.p95 ?? '—' }}</td>
                  <td class="mono">{{ g.total_tokens.min ?? 0 }}</td>
                  <td class="mono">{{ g.total_tokens.max ?? 0 }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionByComponent" class="section-panel">
        <h3>Composição do contexto</h3>
        <div class="charts-row">
          <div class="chart-panel" style="flex: 2;">
            <h4>Tokens acumulados por categoria</h4>
            <div class="bar-chart">
              <div v-for="g in state.contextConsumptionByComponent.groups" :key="g.category" class="bar-item">
                <span class="bar-label">{{ g.category }}</span>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: barColor(g.tokens_total, state.contextConsumptionByComponent.grand_total_tokens) + '%' }"></div>
                </div>
                <span class="bar-value">{{ g.tokens_total }} ({{ g.percent_of_consumption }}%)</span>
              </div>
            </div>
            <p v-if="!state.contextConsumptionByComponent.groups?.length" class="muted small">Sem dados.</p>
          </div>
          <div class="chart-panel">
            <h4>Tabela de componentes</h4>
            <table class="data-table">
              <thead>
                <tr>
                  <th>Categoria</th><th>Tokens</th><th>Média/inf.</th><th>% consumo</th><th>Ocorrências</th><th>Pot. otimização</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="g in state.contextConsumptionByComponent.groups" :key="g.category">
                  <td>{{ g.category }}</td>
                  <td class="mono">{{ g.tokens_total }}</td>
                  <td class="mono">{{ g.avg_tokens_per_inference ?? 0 }}</td>
                  <td>{{ g.percent_of_consumption }}%</td>
                  <td>{{ g.occurrences }}</td>
                  <td>{{ g.optimization_potential }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionMatrix" class="section-panel">
        <h3>Matriz de consumo (tipo × componente)</h3>
        <div class="table-panel">
          <table class="data-table">
            <thead>
              <tr>
                <th>Tipo de inferência</th>
                <th v-for="cat in state.contextConsumptionMatrix.categories" :key="cat">{{ cat }}</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in state.contextConsumptionMatrix.matrix" :key="row.type">
                <td><strong>{{ row.type }}</strong></td>
                <td v-for="cat in state.contextConsumptionMatrix.categories" :key="cat" class="mono">{{ row[cat] ?? 0 }}</td>
                <td class="mono">{{ row.total }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionCompare" class="section-panel">
        <h3>Comparação por {{ state.contextConsumptionCompare.group_by }}</h3>
        <div class="table-panel">
          <table class="data-table">
            <thead>
              <tr>
                <th>{{ state.contextConsumptionCompare.group_by }}</th><th>Amostras</th><th>Total tokens</th><th>Média</th><th>Máx.</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="g in state.contextConsumptionCompare.groups" :key="g.key">
                <td>{{ g.key }}</td>
                <td>{{ g.total_tokens.count }}</td>
                <td class="mono">{{ g.total_tokens.value ?? 0 }}</td>
                <td class="mono">{{ g.total_tokens.mean ?? 0 }}</td>
                <td class="mono">{{ g.total_tokens.max ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionTimeline" class="section-panel">
        <h3>Evolução temporal</h3>
        <div class="table-panel">
          <table class="data-table">
            <thead>
              <tr><th>Período</th><th>Inferências</th><th>Total tokens</th><th>Média/inf.</th><th>Entrada</th><th>Saída</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in state.contextConsumptionTimeline.series" :key="s.period">
                <td>{{ s.period }}</td>
                <td>{{ s.inferences }}</td>
                <td class="mono">{{ s.total_tokens.value ?? 0 }}</td>
                <td class="mono">{{ s.avg_tokens_per_inference ?? 0 }}</td>
                <td class="mono">{{ s.input_tokens ?? 0 }}</td>
                <td class="mono">{{ s.output_tokens ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="!loading && state.contextConsumptionOpportunities" class="section-panel">
        <h3>Oportunidades de otimização</h3>
        <div v-if="state.contextConsumptionOpportunities.opportunities.length" class="table-panel">
          <table class="data-table">
            <thead>
              <tr>
                <th>Problema</th><th>Evidência</th><th>Componente</th><th>Frequência</th><th>Impacto (tokens)</th><th>Estratégia</th><th>Risco</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in state.contextConsumptionOpportunities.opportunities" :key="o.problem">
                <td>{{ o.problem }}</td>
                <td>{{ o.evidence }}</td>
                <td>{{ o.component }}</td>
                <td>{{ o.frequency }}</td>
                <td class="mono">{{ o.estimated_impact_tokens ?? 0 }}</td>
                <td>{{ o.recommended_strategy }}</td>
                <td>{{ o.information_loss_risk }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted small">Nenhuma oportunidade de otimização identificada.</p>
      </div>
    </div>
  `,
};
