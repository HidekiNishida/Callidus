/**
 * Arquivo: web/static/assets/app/components/intelligence-overview.js
 * Nome: intelligence-overview.js
 * Propósito: módulo Overview da Inteligência — visão consolidada do estado do Callidus com indicadores principais, gráficos e saúde do sistema.
 * Responsabilidade: frontend/componente — consome `/api/intelligence/metrics/overview` e renderiza cards de métricas, gráficos de barras, tabela de runs recentes e painel de saúde.
 * Componentes: IntelligenceOverview.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones, rótulos de status).
 * Observações: estados loading/success/empty/error; dados vêm sempre da API; nada é inventado.
 */
import { state, loadIntelligenceOverview } from "../store.js";
import { icon, statusLabel, STATUS_LABEL } from "../ui.js";

export const IntelligenceOverview = {
  name: "IntelligenceOverview",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadIntelligenceOverview();
      } catch (err) {
        error.value = err.message || "Falha ao carregar métricas de overview";
      } finally {
        loading.value = false;
      }
    }

    Vue.onMounted(load);

    return {
      state,
      loading,
      error,
      load,
      icon,
      statusLabel,
      STATUS_LABEL,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Overview</h1>
        <p class="page-sub">Métricas agregadas de execução, consumo e desempenho do Callidus.</p>
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

      <div v-if="!loading && !error && !state.intelligenceOverview" class="empty-state">
        <p>Nenhuma métrica disponível. Execute alguma tarefa para gerar dados.</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && state.intelligenceOverview" class="overview-content">
        <div class="metrics-grid">
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.runs_total }}</div>
            <div class="metric-label">Runs totais</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ (state.intelligenceOverview.completion_rate * 100).toFixed(1) }}%</div>
            <div class="metric-label">Taxa de conclusão</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.tokens.total_tokens !== null ? state.intelligenceOverview.tokens.total_tokens : 'indisponível' }}</div>
            <div class="metric-label">Tokens totais</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.inference.calls }}</div>
            <div class="metric-label">Chamadas ao modelo</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.runs_active }}</div>
            <div class="metric-label">Runs ativas</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.recovery_count }}</div>
            <div class="metric-label">Recuperações automáticas</div>
          </div>
        </div>

        <div class="charts-row">
          <div class="chart-panel">
            <h3>Saúde do Callidus</h3>
            <div class="health-grid">
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.runs_active > 0 ? 'ativa' : 'ociosa' }}</div>
                <div class="health-label">Execução</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.inference.calls > 0 ? 'ativa' : 'sem dados' }}</div>
                <div class="health-label">Inferência</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.tokens.total_tokens !== null ? 'disponível' : 'sem dados' }}</div>
                <div class="health-label">Orçamento</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.resources.samples > 0 ? 'ativo' : 'sem amostras' }}</div>
                <div class="health-label">Ferramentas</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ (state.intelligenceOverview.completion_rate * 100).toFixed(0) }}%</div>
                <div class="health-label">Verificação</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.efficiency.tasks_total > 0 ? 'ativa' : 'sem dados' }}</div>
                <div class="health-label">Conhecimento</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.resources.samples > 0 ? 'ativo' : 'sem dados' }}</div>
                <div class="health-label">Persistência</div>
              </div>
              <div class="health-item">
                <div class="health-value">{{ state.intelligenceOverview.efficiency.recovery_count > 0 ? 'ativa' : 'sem dados' }}</div>
                <div class="health-label">Automações</div>
              </div>
            </div>
          </div>

          <div class="chart-panel">
            <h3>Modelos utilizados</h3>
            <div class="bar-chart" v-if="state.intelligenceOverview.models_used && Object.keys(state.intelligenceOverview.models_used).length">
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
            <div class="bar-chart" v-if="state.intelligenceOverview.providers_used && Object.keys(state.intelligenceOverview.providers_used).length">
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

        <div class="table-panel">
          <h3>Runs recentes</h3>
          <table class="data-table" v-if="state.intelligenceOverview.recent_runs?.length">
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
                <td><span class="status-badge" :class="'status-' + run.status.toLowerCase()">{{ run.status }}</span></td>
                <td>{{ run.provider || '—' }}</td>
                <td>{{ run.model || '—' }}</td>
                <td>{{ run.created_at || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted small">Nenhuma run recente.</p>
        </div>
      </div>
    </div>
  `,
};
