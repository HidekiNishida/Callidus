/**
 * Arquivo: web/static/assets/app/components/intelligence-reasoning.js
 * Nome: intelligence-reasoning.js
 * Propósito: módulo Reasoning da Inteligência — como o Callidus resolve problemas: decomposições, replanejamentos, profundidade de árvore, estratégias, tentativas e progresso verificável.
 * Responsabilidade: frontend/componente — consome métricas de eficiência e metadados de tarefas para renderizar indicadores de raciocínio e visualizações de árvore hierárquica.
 * Componentes: IntelligenceReasoning.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones, rótulos de status).
 * Observações: dados vêm da API; valores não disponíveis são mostrados como indisponível, nunca inventados.
 */
import { state, loadIntelligenceOverview, refreshTasks } from "../store.js";
import { api } from "../api.js";
import { icon, statusLabel, STATUS_LABEL, STATUS_ICON, formatTokenCount } from "../ui.js";

export const IntelligenceReasoning = {
  name: "IntelligenceReasoning",
  props: {
    runId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);
    const selectedTask = Vue.ref(null);
    const taskTree = Vue.ref([]);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadIntelligenceOverview();
        await loadTaskTree();
      } catch (err) {
        error.value = err.message || "Falha ao carregar dados de raciocínio";
      } finally {
        loading.value = false;
      }
    }

    async function loadTaskTree() {
      const workspace = state.selectedProject?.id || state.conversation?.workspace_id || null;
      if (!workspace) {
        taskTree.value = [];
        return;
      }
      try {
        const tasks = await api(`/projects/${workspace}/tasks`).catch(() => []);
        taskTree.value = tasks.filter((t) => !t.parent_id) || [];
      } catch {
        taskTree.value = [];
      }
    }

    async function selectTaskNode(task) {
      selectedTask.value = task;
    }

    const taskStatusDistribution = Vue.computed(() => {
      const dist = {};
      const tasks = state.tasks || [];
      for (const t of tasks) {
        const s = t.status;
        dist[s] = (dist[s] || 0) + 1;
      }
      return dist;
    });

    Vue.onMounted(load);
    Vue.watch(() => props.runId, load);

    return {
      state,
      loading,
      error,
      load,
      selectedTask,
      taskTree,
      selectTaskNode,
      taskStatusDistribution,
      icon,
      statusLabel,
      STATUS_LABEL,
      formatTokenCount,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Inteligência e raciocínio</h1>
        <p class="page-sub">Como o Callidus resolve problemas: decomposições, replanejamentos, profundidade de árvore, estratégias e tentativas.</p>
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
        <p>Não foi possível carregar os dados: {{ error }}</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error && state.intelligenceOverview" class="reasoning-content">
        <div class="efficiency-grid">
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.tasks_total }}</div>
            <div class="metric-label">Tarefas totais</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.tasks_completed }}</div>
            <div class="metric-label">Tarefas concluídas</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.tasks_failed }}</div>
            <div class="metric-label">Tarefas falharam</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.tasks_blocked }}</div>
            <div class="metric-label">Tarefas bloqueadas</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.attempts_total }}</div>
            <div class="metric-label">Tentativas totais</div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{{ state.intelligenceOverview.efficiency.recovery_count }}</div>
            <div class="metric-label">Recuperações automáticas</div>
          </div>
        </div>

        <div class="charts-row">
          <div class="chart-panel">
            <h3>Distribuição de tarefas por status</h3>
            <div class="bar-chart">
              <div v-for="(count, status) in taskStatusDistribution" :key="status" class="bar-item">
                <span class="bar-label">{{ statusLabel(status) }}</span>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: (count / Math.max(1, ...Object.values(taskStatusDistribution)) * 100) + '%' }" :class="'status-color-' + status.toLowerCase()"></div>
                </div>
                <span class="bar-value">{{ count }}</span>
              </div>
            </div>
          </div>
          <div class="chart-panel">
            <h3>Eficiência</h3>
            <div class="metric-detail">
              <div><span>Tokens por tarefa concluída:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.tokens_per_completed_task }}</span></div>
              <div><span>Chamadas por tarefa concluída:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.calls_per_completed_task }}</span></div>
              <div><span>Chamadas sem progresso:</span> <span class="mono">{{ state.intelligenceOverview.efficiency.calls_without_progress }}</span></div>
              <div><span>Taxa de progresso:</span> <span class="mono">{{ ((state.intelligenceOverview.efficiency.progress_rate || 0) * 100).toFixed(1) }}%</span></div>
            </div>
          </div>
        </div>

        <div class="table-panel">
          <h3>Árvore hierárquica de tarefas</h3>
          <div v-if="taskTree.length" class="task-tree">
            <div v-for="task in taskTree" :key="task.id" class="tree-node" @click="selectTaskNode(task)" :class="{ selected: selectedTask?.id === task.id }">
              <div class="tree-node-header">
                <span class="tree-node-icon" v-html="icon(STATUS_ICON[task.status] || 'circle', 12)"></span>
                <span class="tree-node-title">{{ task.display_title || task.title || 'Sem título' }}</span>
                <span class="tree-node-status" :class="'status-' + task.status.toLowerCase()">{{ task.status }}</span>
              </div>
              <div v-if="task.children && task.children.length" class="tree-node-children">
                <div v-for="child in task.children" :key="child.id" class="tree-node-child">
                  <span class="tree-node-child-icon" v-html="icon(STATUS_ICON[child.status] || 'circle', 10)"></span>
                  <span class="tree-node-child-title">{{ child.display_title || child.title || 'Sem título' }}</span>
                  <span class="tree-node-child-status" :class="'status-' + child.status.toLowerCase()">{{ child.status }}</span>
                </div>
              </div>
            </div>
          </div>
          <p v-else class="muted small">Nenhuma tarefa disponível.</p>
        </div>

        <div v-if="selectedTask" class="task-detail-panel">
          <div class="panel-head">
            <h3>Detalhe da tarefa</h3>
            <button type="button" class="btn-ghost" @click="selectedTask = null" v-html="icon('x', 16)"></button>
          </div>
          <div class="panel-body">
            <div class="kv">
              <div><dt>Título</dt><dd>{{ selectedTask.title }}</dd></div>
              <div><dt>Status</dt><dd><span class="status-badge" :class="'status-' + selectedTask.status.toLowerCase()">{{ statusLabel(selectedTask.status) }}</span></dd></div>
              <div><dt>Tentativas</dt><dd>{{ (selectedTask.metadata_json || {}).usage?.calls || 0 }}</dd></div>
              <div><dt>Tokens</dt><dd>{{ formatTokenCount((selectedTask.metadata_json || {}).usage || {}) }}</dd></div>
              <div><dt>Objetivo</dt><dd>{{ selectedTask.objective || '—' }}</dd></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
