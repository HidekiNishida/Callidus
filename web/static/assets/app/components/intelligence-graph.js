/**
 * Arquivo: web/static/assets/app/components/intelligence-graph.js
 * Nome: intelligence-graph.js
 * Propósito: grafo cognitivo animado que representa a arquitetura percorrida pelo agente durante a execução.
 * Responsabilidade: frontend/componente — visualização SVG dos componentes, estados, arestas percorridas e interatividade.
 * Componentes: CognitiveGraphView (componente Vue), renderização SVG, painel lateral de detalhes do nó.
 * Dependências: `../store.js` (estado, carregamento de grafo), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: SVG leve, sem dependências externas; respeita `prefers-reduced-motion`; atualização incremental via eventos SSE.
 */
import { state, loadArchitectureGraph, loadRunGraph, loadRunGraphHistory } from "../store.js";
import { icon } from "../ui.js";

const NODE_COLORS = {
  idle: "#6b7280",
  pending: "#f59e0b",
  active: "#3b82f6",
  completed: "#10b981",
  failed: "#ef4444",
  retrying: "#8b5cf6",
  blocked: "#ef4444",
  skipped: "#9ca3af",
  paused: "#f59e0b",
};

const STATE_LABELS = {
  idle: "Ocioso",
  pending: "Pendente",
  active: "Ativo",
  completed: "Concluído",
  failed: "Falhou",
  retrying: "Tentando novamente",
  blocked: "Bloqueado",
  skipped: "Ignorado",
  paused: "Pausado",
};

const NODE_RADIUS = 28;

/**
 * Posiciona os nós em camadas por categoria para leitura clara do fluxo.
 *
 * @param {object} graph Dados do grafo (nodes, edges).
 * @returns {object} Nós indexados por id com coordenadas x, y, layer.
 */
function computeLayout(graph) {
  const nodes = {};
  (graph.nodes || []).forEach((n) => {
    nodes[n.id] = { ...n, x: 0, y: 0, layer: 0 };
  });

  const categoryLayer = {
    entrada: 0,
    transporte: 1,
    orquestração: 2,
    planejamento: 3,
    contexto: 3,
    memória: 3,
    conhecimento: 3,
    habilidades: 3,
    inferência: 4,
    ferramentas: 4,
    verificação: 4,
    recuperação: 4,
    consolidação: 5,
    persistência: 6,
  };

  const byLayer = {};
  Object.values(nodes).forEach((n) => {
    const layer = categoryLayer[n.category] || 3;
    n.layer = layer;
    if (!byLayer[layer]) byLayer[layer] = [];
    byLayer[layer].push(n);
  });

  let y = 60;
  for (const layer of Object.keys(byLayer).sort((a, b) => Number(a) - Number(b))) {
    const layerNodes = byLayer[layer];
    layerNodes.sort((a, b) => a.id.localeCompare(b.id));
    let x = 60;
    layerNodes.forEach((n) => {
      n.x = x;
      n.y = y;
      x += 220;
    });
    y += 140;
  }

  return nodes;
}

export const CognitiveGraphView = {
  name: "CognitiveGraphView",
  props: {
    runId: { type: String, default: null },
  },
  setup(props) {
    const loading = Vue.ref(false);
    const error = Vue.ref("");
    const selectedNodeId = Vue.ref(null);
    const hoveredNodeId = Vue.ref(null);
    const graphData = Vue.ref(null);
    const layout = Vue.ref({});
    const showHistory = Vue.ref(false);
    const historyEvents = Vue.ref([]);
    const playbackSpeed = Vue.ref(1);
    const isPlaying = Vue.ref(false);
    let playbackTimer = null;

    let prefersReducedMotion = false;
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      try {
        prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      } catch {
        prefersReducedMotion = false;
      }
    }

    const nodes = Vue.computed(() => graphData.value?.nodes || []);
    const edges = Vue.computed(() => graphData.value?.edges || []);
    const detailNode = Vue.computed(() => {
      if (!selectedNodeId.value) return null;
      return nodes.value.find((n) => n.id === selectedNodeId.value) || null;
    });
    const detailOutgoing = Vue.computed(() => {
      if (!selectedNodeId.value) return [];
      return edges.value.filter((e) => e.source === selectedNodeId.value);
    });
    const detailIncoming = Vue.computed(() => {
      if (!selectedNodeId.value) return [];
      return edges.value.filter((e) => e.target === selectedNodeId.value);
    });

    async function loadGraph() {
      loading.value = true;
      error.value = "";
      try {
        if (props.runId) {
          await loadRunGraph(props.runId);
          await loadRunGraphHistory(props.runId);
          historyEvents.value = (state.runGraphHistory?.event_history || []).slice(-100);
        } else {
          await loadArchitectureGraph();
        }
        graphData.value = props.runId ? state.runGraph : state.architectureGraph;
        layout.value = computeLayout(graphData.value || { nodes: [], edges: [] });
      } catch (err) {
        error.value = err.message || "Falha ao carregar o grafo";
      } finally {
        loading.value = false;
      }
    }

    function nodeColor(node) {
      if (hoveredNodeId.value === node.id) return "#60a5fa";
      return NODE_COLORS[node.state] || NODE_COLORS.idle;
    }

    function selectNode(nodeId) {
      selectedNodeId.value = selectedNodeId.value === nodeId ? null : nodeId;
    }

    function formatDuration(ms) {
      if (ms == null) return "—";
      const s = Math.floor(ms / 1000);
      if (s < 60) return `${s}s`;
      const m = Math.floor(s / 60);
      return `${m}m ${s % 60}s`;
    }

    function togglePlayback() {
      isPlaying.value = !isPlaying.value;
      if (isPlaying.value) startPlayback();
      else stopPlayback();
    }

    function startPlayback() {
      stopPlayback();
      const events = historyEvents.value;
      let idx = 0;
      playbackTimer = setInterval(() => {
        if (idx >= events.length) {
          stopPlayback();
          return;
        }
        idx += 1;
      }, Math.max(500, 2000 / playbackSpeed.value));
    }

    function stopPlayback() {
      if (playbackTimer) {
        clearInterval(playbackTimer);
        playbackTimer = null;
      }
      isPlaying.value = false;
    }

    Vue.onMounted(() => {
      loadGraph();
    });
    Vue.onBeforeUnmount(() => {
      stopPlayback();
    });
    Vue.watch(
      () => props.runId,
      () => {
        stopPlayback();
        loadGraph();
      },
    );

    return {
      state,
      loading,
      error,
      selectedNodeId,
      hoveredNodeId,
      graphData,
      layout,
      nodes,
      edges,
      showHistory,
      historyEvents,
      playbackSpeed,
      isPlaying,
      detailNode,
      detailOutgoing,
      detailIncoming,
      nodeColor,
      selectNode,
      formatDuration,
      togglePlayback,
      startPlayback,
      stopPlayback,
      icon,
      STATE_LABELS,
      prefersReducedMotion,
      NODE_RADIUS,
    };
  },
  template: `
    <div class="intelligence-graph" :class="{ 'reduced-motion': prefersReducedMotion }">
      <div class="graph-header">
        <h2>{{ runId ? 'Grafo Cognitivo — Run' : 'Arquitetura Cognitiva' }}</h2>
        <div class="graph-actions">
          <button
            type="button"
            class="btn-ghost"
            :disabled="loading"
            @click="loadGraph"
            title="Recarregar"
            aria-label="Recarregar grafo"
            v-html="icon('refresh', 16)"
          ></button>
          <button
            type="button"
            class="btn-ghost"
            :disabled="!runId || historyEvents.length === 0"
            @click="showHistory = !showHistory"
            title="Histórico de eventos"
            aria-label="Histórico de eventos"
            v-html="icon('history', 16)"
          ></button>
          <button
            type="button"
            class="btn-ghost"
            :disabled="!runId || historyEvents.length === 0"
            @click="togglePlayback"
            :title="isPlaying ? 'Pausar reprodução' : 'Reproduzir histórico'"
            aria-label={isPlaying ? 'Pausar reprodução' : 'Reproduzir histórico'}
          >
            <span v-html="{ isPlaying: icon('pause', 16), '': icon('play', 16) }[isPlaying ? 'isPlaying' : '']"></span>
          </button>
          <span class="muted small">{{ loading ? 'Carregando…' : (graphData ? nodes.length + ' componentes' : '—') }}</span>
        </div>
      </div>

      <div v-if="error" class="alert error">{{ error }}</div>

      <div class="graph-surface">
        <svg
          class="graph-svg"
          width="1200"
          height="800"
          viewBox="0 0 1200 800"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
              <path d="M0,0 L0,6 L9,3 z" fill="#9ca3af" />
            </marker>
            <marker id="arrow-traversed" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
              <path d="M0,0 L0,6 L9,3 z" fill="#10b981" />
            </marker>
          </defs>

          <g class="edges-layer">
            <line
              v-for="edge in edges"
              :key="edge.source + '-' + edge.target"
              :x1="layout[edge.source]?.x || 60"
              :y1="layout[edge.source]?.y || 60"
              :x2="layout[edge.target]?.x || 60"
              :y2="layout[edge.target]?.y || 60"
              :stroke="edge.traversed ? '#10b981' : '#cbd5e1'"
              :stroke-width="edge.traversed ? 3 : 1.5"
              :marker-end="edge.traversed ? 'url(#arrow-traversed)' : 'url(#arrow)'"
            ></line>
          </g>

          <g class="nodes-layer">
            <g
              v-for="node in nodes"
              :key="node.id"
              :transform="'translate(' + (layout[node.id]?.x || 0) + ',' + (layout[node.id]?.y || 0) + ')'"
              @mouseenter="hoveredNodeId = node.id"
              @mouseleave="hoveredNodeId = null"
              @click="selectNode(node.id)"
              :class="{ selected: selectedNodeId === node.id, active: node.state === 'active' }"
            >
              <circle
                :r="NODE_RADIUS"
                :fill="nodeColor(node)"
                :stroke="selectedNodeId === node.id ? '#1e40af' : '#374151'"
                :stroke-width="selectedNodeId === node.id ? 3 : 2"
              ></circle>
              <text
                :x="0"
                :y="4"
                text-anchor="middle"
                fill="#ffffff"
                font-size="12"
                font-weight="600"
                pointer-events="none"
              >{{ node.name }}</text>
              <text
                :x="0"
                :y="20"
                text-anchor="middle"
                fill="#e5e7eb"
                font-size="10"
                pointer-events="none"
              >{{ STATE_LABELS[node.state] || node.state }}</text>
              <circle
                v-if="node.error_count > 0"
                :cx="NODE_RADIUS - 8"
                :cy="-NODE_RADIUS + 8"
                :r="6"
                fill="#ef4444"
              ></circle>
              <text
                v-if="node.error_count > 0"
                :cx="NODE_RADIUS - 8"
                :cy="-NODE_RADIUS + 11"
                text-anchor="middle"
                fill="#ffffff"
                font-size="10"
                font-weight="bold"
                pointer-events="none"
              >{{ node.error_count }}</text>
            </g>
          </g>
        </svg>
      </div>

      <div class="graph-legend">
        <span class="legend-title">Estado:</span>
        <span v-for="(label, stateKey) in STATE_LABELS" :key="stateKey" class="legend-item">
          <span class="legend-dot" :style="{ backgroundColor: NODE_COLORS[stateKey] }"></span>
          {{ label }}
        </span>
      </div>

      <div v-if="selectedNodeId && detailNode" class="node-panel">
        <div class="node-panel-header">
          <h3>{{ detailNode.name }}</h3>
          <button type="button" class="btn-ghost" @click="selectedNodeId = null" aria-label="Fechar">×</button>
        </div>
        <div class="node-panel-body">
          <div class="node-detail-row">
            <span class="detail-label">Componente</span>
            <span class="detail-value">{{ detailNode.type }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Categoria</span>
            <span class="detail-value">{{ detailNode.category }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Estado</span>
            <span class="detail-value" :style="{ color: nodeColor(detailNode) }">{{ STATE_LABELS[detailNode.state] }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Ativações</span>
            <span class="detail-value">{{ detailNode.activations }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Tempo acumulado</span>
            <span class="detail-value">{{ formatDuration(detailNode.total_duration_ms) }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Erros</span>
            <span class="detail-value">{{ detailNode.error_count }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Saídas</span>
            <span class="detail-value">{{ detailOutgoing.length }}</span>
          </div>
          <div class="node-detail-row">
            <span class="detail-label">Entradas</span>
            <span class="detail-value">{{ detailIncoming.length }}</span>
          </div>
        </div>
      </div>

      <div v-if="showHistory && historyEvents.length" class="history-panel">
        <div class="history-panel-header">
          <h3>Histórico de eventos</h3>
          <button type="button" class="btn-ghost" @click="showHistory = false">Fechar</button>
        </div>
        <div class="history-panel-body">
          <div v-for="ev in historyEvents" :key="'ev-' + ev.seq" class="history-event">
            <span class="history-seq">{{ ev.seq }}</span>
            <span class="history-type">{{ ev.type }}</span>
            <span class="history-at">{{ ev.at }}</span>
          </div>
        </div>
      </div>
    </div>
  `,
};
