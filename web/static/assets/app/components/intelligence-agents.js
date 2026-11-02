/**
 * Arquivo: web/static/assets/app/components/intelligence-agents.js
 * Nome: intelligence-agents.js
 * Propósito: módulo Agentes e automações da Inteligência — hierarquia de agentes, execuções, automações habilitadas/suspensas, próximas execuções, taxa de sucesso.
 * Responsabilidade: frontend/componente — consome endpoints de automações (`/automations*`) e dados de agentes para renderizar hierarquia, status e registros.
 * Componentes: IntelligenceAgents.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: estados loading/success/empty/error; dados vêm da API.
 */
import { state, loadAutomations, loadSupervisorStatus } from "../store.js";
import { icon } from "../ui.js";

export const IntelligenceAgents = {
  name: "IntelligenceAgents",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadAutomations();
        await loadSupervisorStatus();
      } catch (err) {
        error.value = err.message || "Falha ao carregar agentes e automações";
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
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Agentes e automações</h1>
        <p class="page-sub">Hierarquia de agentes, execuções, automações habilitadas/suspensas, próximas execuções e taxa de sucesso.</p>
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

      <div v-if="!loading && !error" class="agents-content">
        <div class="charts-row">
          <div class="chart-panel">
            <h3>Agentes</h3>
            <div class="metric-detail">
              <div><span>Hierarquia:</span> <span class="mono">—</span></div>
              <div><span>Agentes ativos:</span> <span class="mono">—</span></div>
              <div><span>Agentes concluídos:</span> <span class="mono">—</span></div>
              <div><span>Profundidade:</span> <span class="mono">—</span></div>
            </div>
          </div>
          <div class="chart-panel">
            <h3>Automações</h3>
            <div class="metric-detail">
              <div><span>Habilitadas:</span> <span class="mono">{{ state.automations?.filter(a => a.state === 'enabled').length || 0 }}</span></div>
              <div><span>Suspensas:</span> <span class="mono">{{ state.automations?.filter(a => a.state === 'suspended').length || 0 }}</span></div>
              <div><span>Desabilitadas:</span> <span class="mono">{{ state.automations?.filter(a => a.state === 'disabled').length || 0 }}</span></div>
              <div><span>Total:</span> <span class="mono">{{ state.automations?.length || 0 }}</span></div>
            </div>
          </div>
        </div>

        <div class="table-panel">
          <h3>Automações registradas</h3>
          <div class="table-scroll" v-if="state.automations?.length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Estado</th>
                  <th>Próxima execução</th>
                  <th>Última execução</th>
                  <th>Tentativas</th>
                  <th>Sucesso</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in state.automations" :key="a.id">
                  <td>{{ a.name || a.id }}</td>
                  <td><span class="status-badge" :class="'status-' + a.state">{{ a.state }}</span></td>
                  <td class="mono">{{ a.next_run_at || '—' }}</td>
                  <td class="mono">{{ a.last_run_at || '—' }}</td>
                  <td>{{ a.max_attempts || '—' }}</td>
                  <td>{{ a.success_rate !== undefined ? (a.success_rate * 100).toFixed(1) + '%' : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted small">Nenhuma automação registrada.</p>
        </div>

        <div v-if="state.supervisor" class="table-panel">
          <h3>Supervisor de automações</h3>
          <div class="metric-detail">
            <div><span>Status:</span> <span class="mono">{{ state.supervisor.status || '—' }}</span></div>
            <div><span>Execuções pendentes:</span> <span class="mono">{{ state.supervisor.pending_executions || 0 }}</span></div>
            <div><span>Execuções em andamento:</span> <span class="mono">{{ state.supervisor.running_executions || 0 }}</span></div>
          </div>
        </div>
      </div>
    </div>
  `,
};
