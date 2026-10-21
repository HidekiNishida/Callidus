/**
 * Arquivo: web/static/assets/app/components/details.js
 * Nome: details.js
 * Propósito: painel lateral de detalhes da tarefa selecionada (plano, tentativas, diff, contexto, métricas).
 * Responsabilidade: frontend/componente — mostra a árvore do plano e as abas de inspeção.
 * Componentes: DetailsPanel (componente Vue), TABS.
 * Dependências: `../store.js` (estado, árvore e carregadores), `../ui.js` (ícones e rótulos).
 * Observações: as abas que precisam de dados do servidor carregam sob demanda, ao serem abertas.
 */
import {
  state,
  roots,
  childrenOf,
  selectTask,
  loadDiff,
  loadMetrics,
  loadGraph,
  loadTools,
  discoverMcp,
  loadInspector,
} from "../store.js";
import { icon, stamp, statusLabel } from "../ui.js";

/** Abas do painel de detalhes. */
const TABS = [
  { id: "detail", label: "Detalhe", icon: "file" },
  { id: "attempts", label: "Tentativas", icon: "refresh" },
  { id: "evidence", label: "Testes", icon: "check" },
  { id: "diff", label: "Diff", icon: "diff" },
  { id: "context", label: "Contexto", icon: "layers" },
  { id: "metrics", label: "Métricas", icon: "chart" },
  { id: "graph", label: "Grafo", icon: "share" },
  { id: "tools", label: "Ferramentas", icon: "wrench" },
];

/**
 * Painel de detalhes: árvore do plano e abas de inspeção da tarefa selecionada.
 *
 * @returns {object} Objeto de opções do Vue com `setup()` e `template`.
 */
export const DetailsPanel = {
  name: "DetailsPanel",
  setup() {
    const tree = Vue.computed(() => {
      const filter = state.taskFilter;
      return roots()
        .map((root) => ({
          id: root.id,
          title: root.display_title || root.title,
          status: root.status,
          statusText: statusLabel(root.status),
          selected: state.selectedTaskId === root.id,
          children: childrenOf(root.id)
            .filter((task) => !filter || task.status === filter)
            .map((task) => ({
              id: task.id,
              title: task.display_title || task.title,
              status: task.status,
              statusText: statusLabel(task.status),
              selected: state.selectedTaskId === task.id,
            })),
        }))
        .filter((root) => !filter || root.status === filter || root.children.length);
    });

    const detail = Vue.computed(() => state.inspector?.task || null);
    const attempts = Vue.computed(() => state.inspector?.attempts || []);
    const evidences = Vue.computed(() => state.inspector?.evidences || []);
    const snapshots = Vue.computed(() => state.inspector?.snapshots || []);
    const contract = Vue.computed(() => state.inspector?.contract || null);
    const feed = Vue.computed(() => state.streamEvents.slice(-60).reverse());

    /**
     * Troca de aba e carrega os dados que a aba precisa.
     *
     * @param {string} id Id da aba ("detail", "attempts", "evidence", "diff", "context", "metrics",
     *   "graph" ou "tools").
     * @returns {Promise<void>}
     */
    async function selectTab(id) {
      state.detailsTab = id;
      if (id === "diff") await loadDiff();
      if (id === "metrics") await loadMetrics();
      if (id === "graph") await loadGraph();
      if (id === "tools") await loadTools();
    }

    return {
      state,
      TABS,
      tree,
      detail,
      attempts,
      evidences,
      snapshots,
      contract,
      feed,
      selectTab,
      selectTask,
      loadInspector,
      loadDiff,
      loadMetrics,
      discoverMcp,
      icon,
      stamp,
    };
  },
  template: `
    <aside class="details" :class="{ open: state.detailsOpen }">
      <div class="sheet-handle" v-if="state.compact" aria-hidden="true"></div>
      <div class="panel-head">
        <h2>Plano</h2>
        <div class="panel-head-actions">
          <select v-model="state.taskFilter" aria-label="Filtrar status">
            <option value="">Todos</option>
            <option value="RUNNING">Executando</option>
            <option value="BLOCKED">Bloqueados</option>
            <option value="COMPLETED">Concluídos</option>
          </select>
          <button
            type="button"
            class="icon-btn ghost sheet-close"
            title="Fechar painel"
            aria-label="Fechar painel"
            @click="state.detailsOpen = false"
            v-html="icon('stop', 14)"
          ></button>
        </div>
      </div>

      <div class="task-tree" role="tree">
        <div v-for="root in tree" :key="root.id" class="tree-node">
          <button type="button" class="tree-row root" :class="{ selected: root.selected }" @click="selectTask(root.id)">
            <span class="status-dot" :class="'status-' + root.status"></span>
            <span class="tree-title">{{ root.title }}</span>
          </button>
          <button
            type="button"
            v-for="child in root.children"
            :key="child.id"
            class="tree-row child"
            :class="{ selected: child.selected }"
            @click="selectTask(child.id)"
          >
            <span class="status-dot" :class="'status-' + child.status"></span>
            <span class="tree-title">{{ child.title }}</span>
          </button>
        </div>
        <p class="muted small" v-if="!tree.length">Sem tarefas ainda.</p>
      </div>

      <div class="tabs" role="tablist">
        <button
          type="button"
          v-for="tab in TABS"
          :key="tab.id"
          class="tab"
          :class="{ active: state.detailsTab === tab.id }"
          role="tab"
          :aria-selected="state.detailsTab === tab.id"
          :title="tab.label"
          @click="selectTab(tab.id)"
        >
          <span v-html="icon(tab.icon, 15)"></span>
        </button>
      </div>

      <div class="tab-panel" v-if="state.detailsTab === 'detail'">
        <div v-if="detail">
          <h3>{{ detail.display_title || detail.title }}</h3>
          <p class="muted">{{ detail.objective }}</p>
          <dl class="kv">
            <div><dt>Status</dt><dd>{{ detail.status }}</dd></div>
            <div><dt>Criado</dt><dd>{{ stamp(detail.created_at) }}</dd></div>
            <div v-if="detail.metadata_json?.tool"><dt>Ferramenta</dt><dd>{{ detail.metadata_json.tool }}</dd></div>
            <div v-if="detail.metadata_json?.model_id"><dt>Modelo</dt><dd>{{ detail.metadata_json.model_id }}</dd></div>
            <div v-if="contract && (contract.inputs || contract.outputs || contract.invariants || contract.acceptance)">
              <dt>Contrato</dt><dd>definido</dd>
            </div>
          </dl>
          <pre class="code" v-if="detail.consolidated_result_json">{{ JSON.stringify(detail.consolidated_result_json, null, 2) }}</pre>
        </div>
        <p class="muted small" v-else>Selecione uma tarefa.</p>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'attempts'">
        <p class="muted small" v-if="!attempts.length">Sem tentativas registradas.</p>
        <div class="row-item" v-for="attempt in attempts" :key="attempt.id">
          <span class="status-dot" :class="'status-' + (attempt.outcome || 'PENDING')"></span>
          <span>{{ attempt.attempt_kind || attempt.kind || 'passo' }}</span>
          <span class="muted">{{ stamp(attempt.created_at) }}</span>
        </div>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'evidence'">
        <p class="muted small" v-if="!evidences.length">Sem evidências.</p>
        <div class="row-item" v-for="evidence in evidences" :key="evidence.id">
          <span class="status-dot" :class="evidence.passed === false ? 'status-FAILED' : 'status-COMPLETED'"></span>
          <span>{{ evidence.spec_type || evidence.kind || 'verificação' }}</span>
          <span class="muted">{{ stamp(evidence.created_at) }}</span>
        </div>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'diff'">
        <button type="button" class="btn-ghost small" @click="loadDiff()">Atualizar diff</button>
        <pre class="code" v-if="state.diffText">{{ state.diffText }}</pre>
        <p class="muted small" v-else>Nenhuma mudança para mostrar.</p>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'context'">
        <p class="muted small" v-if="!snapshots.length">Sem snapshots de contexto.</p>
        <div class="row-item" v-for="snapshot in snapshots" :key="snapshot.id">
          <span class="muted">{{ snapshot.estimated_tokens || 0 }} tokens</span>
          <span class="muted">{{ stamp(snapshot.created_at) }}</span>
        </div>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'metrics'">
        <button type="button" class="btn-ghost small" @click="loadMetrics()">Atualizar</button>
        <pre class="code">{{ state.metricsText }}</pre>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'graph'">
        <button type="button" class="btn-ghost small" @click="loadGraph('')">Reindexar/pesquisar</button>
        <pre class="code">{{ state.graphText }}</pre>
      </div>

      <div class="tab-panel" v-else-if="state.detailsTab === 'tools'">
        <button type="button" class="btn-ghost small" @click="loadTools()">Atualizar</button>
        <p class="muted small">Disponibilidade, dependências ausentes, diagnóstico do ambiente e skills instaladas.</p>
        <pre class="code">{{ state.toolsText }}</pre>
      </div>

      <div class="panel-head">
        <h2>Linha do tempo</h2>
        <button type="button" class="icon-btn ghost" title="MCP" aria-label="MCP" @click="discoverMcp()" v-html="icon('plug', 15)"></button>
      </div>
      <ul class="feed">
        <li v-for="(event, index) in feed" :key="index" class="feed-item">
          <span class="feed-type">{{ event.type }}</span>
          <span class="muted">{{ stamp(event.created_at) }}</span>
        </li>
      </ul>
      <p class="muted small" v-if="!feed.length">Sem eventos ainda.</p>
    </aside>
  `,
};
