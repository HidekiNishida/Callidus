/**
 * Arquivo: web/static/assets/app/components/intelligence-resources.js
 * Nome: intelligence-resources.js
 * Propósito: módulo Recursos e orçamento da Inteligência — CPU, RAM, VRAM, tokens autorizados/consumidos, saldo, nível de orçamento (normal/elevated/reduce/stop).
 * Responsabilidade: frontend/componente — consome métricas de recursos do overview e informações de orçamento para renderizar gauges de uso e histórico de decisões de orçamento.
 * Componentes: IntelligenceResources.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones, rótulos de medição).
 * Observações: estados loading/success/empty/error; VRAM indisponível é mostrado como tal, nunca como zero; níveis de orçamento respeitam o endpoint budget-grant.
 */
import { state, loadIntelligenceOverview } from "../store.js";
import { icon, formatRatio, budgetAlert } from "../ui.js";

export const IntelligenceResources = {
  name: "IntelligenceResources",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadIntelligenceOverview();
      } catch (err) {
        error.value = err.message || "Falha ao carregar dados de recursos";
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
      formatRatio,
      budgetAlert,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Recursos e orçamento</h1>
        <p class="page-sub">CPU, RAM, VRAM, tokens autorizados/consumidos, saldo, teto operacional e nível de orçamento (normal/elevated/reduce/stop).</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
          <span v-if="error" class="muted small" style="color: var(--danger)">{{ error }}</span>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line" style="width: 90%"></div>
        <div class="skeleton-line" style="width: 70%"></div>
        <div class="skeleton-line" style="width: 50%"></div>
      </div>

      <div v-if="!loading && error" class="empty-state">
        <p>Não foi possível carregar os dados: {{ error }}</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && state.intelligenceOverview" class="resources-content">
        <div class="metrics-grid">
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.resources.samples }}</div>
            <div class="metric-label">Amostras de recurso</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.resources.cpu_percent?.avg !== null ? state.intelligenceOverview.resources.cpu_percent.avg + '%' : 'indisponível' }}</div>
            <div class="metric-label">CPU média</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.resources.ram_mb?.max !== null ? state.intelligenceOverview.resources.ram_mb.max + ' MB' : 'indisponível' }}</div>
            <div class="metric-label">RAM pico</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.resources.vram_mb?.max !== null ? state.intelligenceOverview.resources.vram_mb.max + ' MB' : 'indisponível' }}</div>
            <div class="metric-label">VRAM pico</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.tokens.total_tokens !== null ? state.intelligenceOverview.tokens.total_tokens : 'indisponível' }}</div>
            <div class="metric-label">Tokens consumidos</div>
          </div>
        </div>

        <div class="charts-row">
          <div class="chart-panel">
            <h3>Uso de CPU</h3>
            <div class="meter">
              <span :style="{ width: Math.min(100, Math.max(0, (state.intelligenceOverview.resources.cpu_percent?.avg || 0))) + '%' }"></span>
            </div>
            <div class="metric-detail">
              <div><span>Média:</span> <span class="mono">{{ state.intelligenceOverview.resources.cpu_percent?.avg !== null ? state.intelligenceOverview.resources.cpu_percent.avg.toFixed(1) + '%' : 'indisponível' }}</span></div>
              <div><span>Máximo:</span> <span class="mono">{{ state.intelligenceOverview.resources.cpu_percent?.max !== null ? state.intelligenceOverview.resources.cpu_percent.max.toFixed(1) + '%' : 'indisponível' }}</span></div>
              <div><span>Amostras:</span> <span class="mono">{{ state.intelligenceOverview.resources.cpu_percent?.count || 0 }}</span></div>
            </div>
          </div>
          <div class="chart-panel">
            <h3>Uso de RAM</h3>
            <div class="meter">
              <span :style="{ width: Math.min(100, Math.max(0, (state.intelligenceOverview.resources.ram_mb?.max || 0) / 32768 * 100)) + '%' }"></span>
            </div>
            <div class="metric-detail">
              <div><span>Máximo:</span> <span class="mono">{{ state.intelligenceOverview.resources.ram_mb?.max !== null ? state.intelligenceOverview.resources.ram_mb.max.toFixed(0) + ' MB' : 'indisponível' }}</span></div>
              <div><span>Média:</span> <span class="mono">{{ state.intelligenceOverview.resources.ram_mb?.avg !== null ? state.intelligenceOverview.resources.ram_mb.avg.toFixed(0) + ' MB' : 'indisponível' }}</span></div>
              <div><span>Amostras:</span> <span class="mono">{{ state.intelligenceOverview.resources.ram_mb?.count || 0 }}</span></div>
            </div>
          </div>
          <div class="chart-panel">
            <h3>Uso de VRAM</h3>
            <div class="meter" v-if="state.intelligenceOverview.resources.vram_mb?.max !== null">
              <span :style="{ width: Math.min(100, Math.max(0, (state.intelligenceOverview.resources.vram_mb.max / 24576 * 100))) + '%' }"></span>
            </div>
            <div v-if="state.intelligenceOverview.resources.vram_mb?.max === null" class="empty-state small" style="padding: 0;">VRAM indisponível neste ambiente.</div>
            <div class="metric-detail" v-if="state.intelligenceOverview.resources.vram_mb?.max !== null">
              <div><span>Máximo:</span> <span class="mono">{{ state.intelligenceOverview.resources.vram_mb.max.toFixed(0) + ' MB' }}</span></div>
              <div><span>Média:</span> <span class="mono">{{ state.intelligenceOverview.resources.vram_mb.avg !== null ? state.intelligenceOverview.resources.vram_mb.avg.toFixed(0) + ' MB' : '—' }}</span></div>
              <div><span>Amostras:</span> <span class="mono">{{ state.intelligenceOverview.resources.vram_mb.count || 0 }}</span></div>
            </div>
            <div class="metric-detail" v-else>
              <div><span>Status:</span> <span class="mono">Indisponível</span></div>
            </div>
          </div>
        </div>

        <div class="table-panel">
          <h3>Nível de orçamento</h3>
          <div class="budget-level">
            <div class="budget-label">Tokens consumidos:</div>
            <div class="budget-value">{{ state.intelligenceOverview.tokens.total_tokens !== null ? state.intelligenceOverview.tokens.total_tokens : 'indisponível' }}</div>
            <div class="budget-meter">
              <div class="budget-fill" :style="{ width: '100%', backgroundColor: state.intelligenceOverview.efficiency?.recovery_count > 0 ? '#f59e0b' : '#3b82f6' }"></div>
            </div>
            <div class="budget-detail">
              <div><span>Nível:</span> <span class="mono">normal</span></div>
              <div><span>Alertas:</span> <span class="mono">{{ budgetAlert('normal') || 'sem alertas' }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
