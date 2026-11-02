/**
 * Arquivo: web/static/assets/app/components/intelligence-performance.js
 * Nome: intelligence-performance.js
 * Propósito: módulo Performance da Inteligência — métricas de desempenho por run: tokens, contexto, inferência, recursos e eficiência com percentis.
 * Responsabilidade: frontend/componente — consome `/api/intelligence/metrics/runs/{id}` e renderiza tokens, latência p50/p95/p99, consumo por provedor e indicadores de eficiência derivados.
 * Componentes: IntelligencePerformance.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones, rótulos de medição).
 * Observações: separa valores estimados de valores reportados; estados loading/success/empty/error.
 */
import { state, loadRunMetrics } from "../store.js";
import { icon, measurementLabel, formatTokenCount, formatRatio } from "../ui.js";

export const IntelligencePerformance = {
  name: "IntelligencePerformance",
  props: {
    runId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        if (props.runId) {
          await loadRunMetrics(props.runId);
        } else {
          // Sem run selecionada: mostra métricas globais via overview
          const { loadIntelligenceOverview } = await import("../store.js");
          await loadIntelligenceOverview();
        }
      } catch (err) {
        error.value = err.message || "Falha ao carregar métricas de performance";
      } finally {
        loading.value = false;
      }
    }

    Vue.onMounted(load);
    Vue.watch(() => props.runId, load);

    return {
      state,
      loading,
      error,
      load,
      icon,
      measurementLabel,
      formatTokenCount,
      formatRatio,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Performance</h1>
        <p class="page-sub">Métricas de desempenho por run: tokens, contexto, inferência, recursos e eficiência.</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
          <span v-if="error" class="muted small" style="color: var(--danger)">{{ error }}</span>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line" style="width: 90%"></div>
        <div class="skeleton-line" style="width: 70%"></div>
        <div class="skeleton-line" style="width: 50%"></div>
        <div class="skeleton-line" style="width: 80%"></div>
      </div>

      <div v-if="!loading && error" class="empty-state">
        <p>Não foi possível carregar as métricas: {{ error }}</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && !state.runMetrics && !state.intelligenceOverview" class="empty-state">
        <p>Selecione uma execução no acompanhamento ou execute uma tarefa para ver métricas de desempenho.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && (state.runMetrics || state.intelligenceOverview)" class="performance-content">
        <div v-if="state.runMetrics" class="run-section">
          <div class="page-header" style="margin-bottom: 16px;">
            <h2>Run {{ state.runMetrics.run_id ? state.runMetrics.run_id.slice(0, 8) : 'atual' }}</h2>
          </div>

          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-value">{{ formatTokenCount(state.runMetrics.tokens) }}</div>
              <div class="metric-label">Tokens totais ({{ state.runMetrics.tokens.total_measurement }})</div>
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

          <div class="charts-row">
            <div class="chart-panel">
              <h3>Tokens por medição</h3>
              <div class="metric-detail">
                <div><span>Entrada:</span> <span class="mono">{{ formatTokenCount(state.runMetrics.tokens) }} ({{ measurementLabel(state.runMetrics.tokens.total_measurement) }})</span></div>
                <div><span>Saída:</span> <span class="mono">{{ state.runMetrics.tokens.completion_tokens !== null ? state.runMetrics.tokens.completion_tokens : 'indisponível' }} ({{ measurementLabel(state.runMetrics.tokens.completion_measurement) }})</span></div>
                <div><span>Raciocínio:</span> <span class="mono">{{ state.runMetrics.tokens.reasoning_tokens !== null ? state.runMetrics.tokens.reasoning_tokens : 'indisponível' }}</span></div>
                <div><span>Cache leitura:</span> <span class="mono">{{ state.runMetrics.tokens.cache_read_tokens !== null ? state.runMetrics.tokens.cache_read_tokens : 'indisponível' }}</span></div>
                <div><span>Cache escrita:</span> <span class="mono">{{ state.runMetrics.tokens.cache_write_tokens !== null ? state.runMetrics.tokens.cache_write_tokens : 'indisponível' }}</span></div>
              </div>
            </div>
            <div class="chart-panel">
              <h3>Latência de inferência</h3>
              <div class="metric-detail">
                <div><span>P50:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p50 !== null ? state.runMetrics.inference.duration_ms.p50 + 'ms' : 'indisponível' }}</span></div>
                <div><span>P95:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p95 !== null ? state.runMetrics.inference.duration_ms.p95 + 'ms' : 'indisponível' }}</span></div>
                <div><span>P99:</span> <span class="mono">{{ state.runMetrics.inference.duration_ms?.p99 !== null ? state.runMetrics.inference.duration_ms.p99 + 'ms' : 'indisponível' }}</span></div>
                <div><span>Erros:</span> <span class="mono">{{ (state.runMetrics.inference.error_rate * 100).toFixed(1) }}%</span></div>
                <div><span>Timeouts:</span> <span class="mono">{{ (state.runMetrics.inference.timeout_rate * 100).toFixed(1) }}%</span></div>
              </div>
            </div>
          </div>

          <div class="table-panel">
            <h3>Consumo por provedor</h3>
            <div class="table-scroll" v-if="state.runMetrics.inference.by_provider && Object.keys(state.runMetrics.inference.by_provider).length">
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
            <p v-else class="muted small">Nenhum dado de provedor disponível.</p>
          </div>
        </div>

        <div v-else-if="state.intelligenceOverview" class="global-section">
          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-value">{{ state.intelligenceOverview.inference.calls }}</div>
              <div class="metric-label">Chamadas ao modelo (global)</div>
            </div>
            <div class="metric-card">
              <div class="metric-value">{{ state.intelligenceOverview.tokens.total_tokens !== null ? state.intelligenceOverview.tokens.total_tokens : 'indisponível' }}</div>
              <div class="metric-label">Tokens totais (global)</div>
            </div>
            <div class="metric-card">
              <div class="metric-value">{{ (state.intelligenceOverview.completion_rate * 100).toFixed(1) }}%</div>
              <div class="metric-label">Taxa de conclusão (global)</div>
            </div>
            <div class="metric-card">
              <div class="metric-value">{{ state.intelligenceOverview.resources.samples }}</div>
              <div class="metric-label">Amostras de recurso</div>
            </div>
          </div>

          <div class="charts-row">
            <div class="chart-panel">
              <h3>Distribuição de inferências por provedor</h3>
              <div class="bar-chart" v-if="state.intelligenceOverview.inference.by_provider && Object.keys(state.intelligenceOverview.inference.by_provider).length">
                <div v-for="(data, provider) in state.intelligenceOverview.inference.by_provider" :key="provider" class="bar-item">
                  <span class="bar-label">{{ provider }}</span>
                  <div class="bar-track">
                    <div class="bar-fill" :style="{ width: (data.calls / Math.max(1, ...Object.values(state.intelligenceOverview.inference.by_provider).map(d => d.calls))) * 100 + '%' }"></div>
                  </div>
                  <span class="bar-value">{{ data.calls }}</span>
                </div>
              </div>
              <p v-else class="muted small">Nenhum dado de provedor disponível.</p>
            </div>
            <div class="chart-panel">
              <h3>Eficiência</h3>
              <div class="metric-detail">
                <div><span>Tokens por tarefa concluída:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.tokens_per_completed_task }}</span></div>
                <div><span>Chamadas por tarefa concluída:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.calls_per_completed_task }}</span></div>
                <div><span>Chamadas sem progresso:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.calls_without_progress }}</span></div>
                <div><span>Taxa de progresso:</span> <span class="mono">{{ formatRatio(state.intelligenceOverview.efficiency.progress_rate) }}</span></div>
                <div><span>Recuperações automáticas:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.recovery_count }}</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
