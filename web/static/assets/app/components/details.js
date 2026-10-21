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
import { budgetAlert, formatRatio, formatTokenCount, icon, stamp, statusLabel } from "../ui.js";

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
    const usage = Vue.computed(() => state.inspector?.usage || null);
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
      if (id === "context" && state.selectedTaskId) await loadInspector(state.selectedTaskId);
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
      usage,
      contract,
      formatTokenCount,
      formatRatio,
      budgetAlert,
      feed,
      selectTab,
      selectTask,
      loadInspector,
      loadDiff,
      loadMetrics,
      loadGraph,
      loadTools,
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
        <p class="context-alert" v-if="budgetAlert(usage?.budget?.level)">{{ budgetAlert(usage.budget.level) }}</p>

        <section class="context-block">
          <h3>Chamada atual</h3>
          <p class="muted small" v-if="!usage?.call?.available">Ainda não há snapshot nem inferência registrada.</p>
          <dl class="kv" v-else>
            <div><dt>Modelo</dt><dd>{{ usage.call.model || "indisponível" }}</dd></div>
            <div><dt>Provedor</dt><dd>{{ usage.call.provider || "indisponível" }}</dd></div>
            <div><dt>Janela</dt><dd>{{ usage.call.context_limit ?? "indisponível" }} <span class="muted" v-if="usage.call.context_limit_source">({{ usage.call.context_limit_source }})</span></dd></div>
            <div><dt>Ocupação da janela</dt><dd>{{ formatRatio(usage.call.window_occupancy) }}</dd></div>
            <div><dt>Entrada prevista</dt><dd>{{ formatTokenCount(usage.call.estimated_input_tokens) }}</dd></div>
            <div><dt>Entrada informada</dt><dd>{{ formatTokenCount(usage.call.reported_input_tokens) }}</dd></div>
            <div><dt>Saída informada</dt><dd>{{ formatTokenCount(usage.call.reported_output_tokens) }}</dd></div>
            <div><dt>Reserva de saída</dt><dd>{{ usage.call.output_reserve_tokens ?? "indisponível" }}</dd></div>
            <div><dt>Previsão − real</dt><dd>{{ usage.call.delta_input_tokens ?? "indisponível" }}</dd></div>
            <div><dt>Medição</dt><dd>{{ usage.call.measurement || "indisponível" }}</dd></div>
          </dl>
          <p class="muted small" v-if="usage?.call?.method">{{ usage.call.method }}</p>
          <details v-for="category in (usage?.call?.categories || [])" :key="category.category">
            <summary>{{ category.label }} — {{ category.tokens }} (estimativa)</summary>
            <div class="row-item" v-for="item in category.components" :key="item.name">
              <span>{{ item.name }}</span>
              <span class="muted">{{ item.tokens }} estimados</span>
            </div>
          </details>
          <p class="muted small" v-if="usage?.call?.available && !(usage.call.categories || []).length">A composição por categoria não foi gravada neste snapshot.</p>
        </section>

        <section class="context-block">
          <h3>Consumo acumulado</h3>
          <p class="muted small" v-if="!usage">Sem registros de inferência.</p>
          <template v-else>
            <div class="meter" v-if="usage.budget?.occupancy != null" :title="'Ocupação do teto autorizado'">
              <span :style="{ width: Math.min(100, Math.round(usage.budget.occupancy * 100)) + '%' }"></span>
            </div>
            <dl class="kv">
              <div><dt>Entrada</dt><dd>{{ formatTokenCount(usage.accumulated.prompt_tokens) }}</dd></div>
              <div><dt>Saída</dt><dd>{{ formatTokenCount(usage.accumulated.completion_tokens) }}</dd></div>
              <div><dt>Chamadas</dt><dd>{{ usage.accumulated.calls }}</dd></div>
              <div><dt>Falhas</dt><dd>{{ usage.accumulated.failed }}</dd></div>
              <div><dt>Raciocínio</dt><dd>{{ formatTokenCount(usage.accumulated.reasoning_tokens) }}</dd></div>
              <div><dt>Cache</dt><dd>{{ formatTokenCount(usage.accumulated.cache_read_tokens) }}</dd></div>
              <div><dt>Custo</dt><dd>{{ formatTokenCount(usage.accumulated.cost_usd) }}</dd></div>
              <div><dt>Teto autorizado</dt><dd>{{ usage.budget.authorized_tokens ?? "sem teto" }}</dd></div>
              <div><dt>Reserva</dt><dd>{{ usage.budget.reserve_tokens ?? "indisponível" }}</dd></div>
              <div><dt>Saldo</dt><dd>{{ usage.budget.balance_tokens ?? "indisponível" }}</dd></div>
              <div><dt>Ocupação do teto</dt><dd>{{ formatRatio(usage.budget.occupancy) }}</dd></div>
            </dl>
            <p class="muted small">A ocupação acima é o consumo acumulado sobre o teto da execução. A entrada prevista da chamada é a janela, não o teto.</p>
            <h4>Por finalidade</h4>
            <div class="row-item" v-for="item in usage.accumulated.by_purpose" :key="item.key">
              <span>{{ item.key }}</span>
              <span class="muted">{{ item.calls }} · {{ formatTokenCount(item.spend) }}</span>
            </div>
          </template>
        </section>

        <section class="context-block">
          <h3>Snapshots</h3>
          <p class="muted small" v-if="!snapshots.length">Sem snapshots de contexto.</p>
          <div class="row-item" v-for="snapshot in snapshots" :key="snapshot.id">
            <span class="muted">{{ snapshot.estimated_tokens || 0 }} estimados</span>
            <span class="muted">{{ stamp(snapshot.created_at) }}</span>
          </div>
        </section>
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
          <span class="feed-note" v-if="event.type === 'work.explained' && event.data && event.data.text">{{ event.data.text }}</span>
          <span class="muted">{{ stamp(event.created_at) }}</span>
        </li>
      </ul>
      <p class="muted small" v-if="!feed.length">Sem eventos ainda.</p>
    </aside>
  `,
};
