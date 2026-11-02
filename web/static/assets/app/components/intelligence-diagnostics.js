/**
 * Arquivo: web/static/assets/app/components/intelligence-diagnostics.js
 * Nome: intelligence-diagnostics.js
 * Propósito: módulo Diagnóstico e confiabilidade da Inteligência — falhas por categoria, causa, provedor, ferramenta, estagnação, recuperações.
 * Responsabilidade: frontend/componente — consome `/api/intelligence/diagnostics*` e renderiza resumo, gráficos por categoria/severidade e tabela de diagnósticos com causa provável e recomendação.
 * Componentes: IntelligenceDiagnostics.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: estados loading/success/empty/error; hipóteses são mostradas como tais, nunca como fatos confirmados.
 */
import { state, loadDiagnostics, loadDiagnosticsSummary, analyzeRunDiagnostics } from "../store.js";
import { icon } from "../ui.js";

export const IntelligenceDiagnostics = {
  name: "IntelligenceDiagnostics",
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
        await loadDiagnostics(props.runId || null);
        await loadDiagnosticsSummary(props.runId || null);
      } catch (err) {
        error.value = err.message || "Falha ao carregar diagnósticos";
      } finally {
        loading.value = false;
      }
    }

    async function analyze() {
      if (!props.runId) return;
      loading.value = true;
      try {
        await analyzeRunDiagnostics(props.runId);
        await loadDiagnostics(props.runId);
        await loadDiagnosticsSummary(props.runId);
      } catch (err) {
        error.value = err.message || "Falha ao analisar run";
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
      analyze,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Diagnósticos</h1>
        <p class="page-sub">Problemas identificados, gargalos e recomendações a partir de evidências. Hipóteses são mostradas como tais, nunca como fatos confirmados.</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
          <button
            v-if="props.runId"
            type="button"
            class="btn-secondary"
            @click="analyze"
            :disabled="loading"
          >
            <span v-html="icon('bug', 16)"></span>
            Analisar run
          </button>
          <span v-if="error" class="muted small" style="color: var(--danger)">{{ error }}</span>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line" style="width: 90%"></div>
        <div class="skeleton-line" style="width: 70%"></div>
        <div class="skeleton-line" style="width: 50%"></div>
      </div>

      <div v-if="!loading && error" class="empty-state">
        <p>Não foi possível carregar os diagnósticos: {{ error }}</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && !state.diagnosticsSummary" class="empty-state">
        <p>Nenhum diagnóstico disponível. Execute uma tarefa e use "Analisar run" para gerar diagnósticos.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && state.diagnosticsSummary" class="diagnostics-content">
        <div class="summary-cards">
          <div class="metric-card">
            <div class="metric-value">{{ state.diagnosticsSummary.total }}</div>
            <div class="metric-label">Diagnósticos</div>
          </div>
          <div class="metric-card">
            <div class="metric-value" style="color: var(--danger)">{{ state.diagnosticsSummary.critical }}</div>
            <div class="metric-label">Críticos</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.diagnosticsSummary.open }}</div>
            <div class="metric-label">Abertos</div>
          </div>
        </div>

        <div class="charts-row">
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

        <div class="table-panel">
          <h3>Detalhes dos diagnósticos</h3>
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
    </div>
  `,
};
