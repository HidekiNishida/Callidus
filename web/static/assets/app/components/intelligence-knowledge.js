/**
 * Arquivo: web/static/assets/app/components/intelligence-knowledge.js
 * Nome: intelligence-knowledge.js
 * Propósito: módulo Conhecimento e memória da Inteligência — grafo de conhecimento, busca de símbolos, itens estruturados e tipos de memória.
 * Responsabilidade: frontend/componente — consome endpoints de conhecimento (`/projects/{id}/knowledge/*`) e renderiza busca de símbolos, inspeção de nós/arestas e tipos de memória (canonical, execution, contextual, evidence, procedure, operational, task_detail, artifact).
 * Componentes: IntelligenceKnowledge.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: estados loading/success/empty/error; busca textual e por símbolo; dados vêm da API.
 */
import { state } from "../store.js";
import { api } from "../api.js";
import { icon } from "../ui.js";

export const IntelligenceKnowledge = {
  name: "IntelligenceKnowledge",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);
    const searchQuery = Vue.ref("");
    const searchResults = Vue.ref([]);
    const graphData = Vue.ref(null);
    const graphError = Vue.ref(null);
    const selectedNode = Vue.ref(null);
    const memoryStats = Vue.ref({});

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadGraph();
        await loadMemoryStats();
      } catch (err) {
        error.value = err.message || "Falha ao carregar dados de conhecimento";
      } finally {
        loading.value = false;
      }
    }

    async function loadGraph() {
      const project = state.selectedProject;
      if (!project) {
        graphData.value = null;
        return;
      }
      try {
        const data = await api(`/projects/${project.id}/knowledge/search?q=`).catch(() => null);
        graphData.value = data || null;
      } catch (err) {
        graphError.value = err.message || "Falha ao carregar grafo de conhecimento";
      }
    }

    async function loadMemoryStats() {
      const project = state.selectedProject;
      if (!project) {
        memoryStats.value = {};
        return;
      }
      try {
        const data = await api(`/projects/${project.id}/knowledge/search?q=`).catch(() => null);
        memoryStats.value = data || {};
      } catch {
        memoryStats.value = {};
      }
    }

    async function search() {
      const q = searchQuery.value.trim();
      if (!q) {
        searchResults.value = [];
        return;
      }
      const project = state.selectedProject;
      if (!project) return;
      try {
        const data = await api(`/projects/${project.id}/knowledge/search?q=${encodeURIComponent(q)}`).catch(() => null);
        searchResults.value = (data && data.results) ? data.results : (data || []);
      } catch {
        searchResults.value = [];
      }
    }

    async function viewNeighbors(nodeRef) {
      const project = state.selectedProject;
      if (!project || !nodeRef) return;
      try {
        const data = await api(`/projects/${project.id}/knowledge/neighbors?ref=${encodeURIComponent(nodeRef)}&depth=2`).catch(() => null);
        selectedNode.value = { ref: nodeRef, neighbors: data || null };
      } catch {
        selectedNode.value = { ref: nodeRef, neighbors: null, error: "Falha ao carregar vizinhos" };
      }
    }

    Vue.onMounted(load);

    return {
      state,
      loading,
      error,
      load,
      searchQuery,
      searchResults,
      graphData,
      graphError,
      selectedNode,
      memoryStats,
      search,
      viewNeighbors,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Conhecimento e memória</h1>
        <p class="page-sub">O que o Callidus sabe: grafo de conhecimento, busca de símbolos, itens estruturados e tipos de memória.</p>
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

      <div v-if="!loading && !error" class="knowledge-content">
        <div class="search-section">
          <div class="field" style="margin-bottom: 0;">
            <span>Buscar símbolos ou texto</span>
            <input v-model="searchQuery" type="text" placeholder="ex.: classe, função, símbolo…" @keyup.enter="search" />
            <button type="button" class="btn-primary small" @click="search" :disabled="loading">Buscar</button>
          </div>
        </div>

        <div class="charts-row">
          <div class="chart-panel">
            <h3>Grafo de conhecimento</h3>
            <div v-if="graphError" class="alert error">{{ graphError }}</div>
            <div v-if="graphData && graphData.nodes" class="graph-summary">
              <div class="metric-detail">
                <div><span>Nós:</span> <span class="mono">{{ graphData.nodes.length }}</span></div>
                <div><span>Arestas:</span> <span class="mono">{{ graphData.edges?.length || 0 }}</span></div>
              </div>
            </div>
            <p v-if="!graphData || !graphData.nodes" class="muted small">Nenhum nó de conhecimento indexado ainda.</p>
          </div>

          <div class="chart-panel">
            <h3>Tipos de memória</h3>
            <div class="metric-detail">
              <div><span>canonical:</span> <span class="mono">{{ memoryStats.canonical_count || 0 }}</span></div>
              <div><span>execution:</span> <span class="mono">{{ memoryStats.execution_count || 0 }}</span></div>
              <div><span>contextual:</span> <span class="mono">{{ memoryStats.contextual_count || 0 }}</span></div>
              <div><span>evidence:</span> <span class="mono">{{ memoryStats.evidence_count || 0 }}</span></div>
              <div><span>procedure:</span> <span class="mono">{{ memoryStats.procedure_count || 0 }}</span></div>
              <div><span>operational:</span> <span class="mono">{{ memoryStats.operational_count || 0 }}</span></div>
              <div><span>task_detail:</span> <span class="mono">{{ memoryStats.task_detail_count || 0 }}</span></div>
              <div><span>artifact:</span> <span class="mono">{{ memoryStats.artifact_count || 0 }}</span></div>
            </div>
          </div>
        </div>

        <div v-if="searchResults.length" class="table-panel">
          <h3>Resultados da busca ({{ searchResults.length }})</h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Símbolo</th>
                  <th>Tipo</th>
                  <th>Arquivo</th>
                  <th>Linha</th>
                  <th>Confiança</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in searchResults" :key="r.symbol + r.file">
                  <td class="mono">{{ r.symbol || r.name || '—' }}</td>
                  <td>{{ r.kind || r.type || '—' }}</td>
                  <td class="mono">{{ r.file || '—' }}</td>
                  <td class="mono">{{ r.line !== undefined ? r.line : '—' }}</td>
                  <td>{{ r.confidence !== undefined ? (r.confidence * 100).toFixed(0) + '%' : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="selectedNode" class="node-detail-panel">
          <div class="panel-head">
            <h3>Nó: {{ selectedNode.ref }}</h3>
            <button type="button" class="btn-ghost" @click="selectedNode = null" v-html="icon('x', 16)"></button>
          </div>
          <div class="panel-body">
            <div v-if="selectedNode.error" class="alert error">{{ selectedNode.error }}</div>
            <div v-else-if="selectedNode.neighbors" class="neighbors-list">
              <h4>Vizinhos (profundidade 2)</h4>
              <div v-for="(edge, idx) in selectedNode.neighbors.edges || []" :key="idx" class="neighbor-item">
                <span class="neighbor-source">{{ edge.source || '—' }}</span>
                <span class="neighbor-arrow">→</span>
                <span class="neighbor-target">{{ edge.target || '—' }}</span>
                <span class="neighbor-kind">{{ edge.kind || '—' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
