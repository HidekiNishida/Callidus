/**
 * Arquivo: web/static/assets/app/components/live.js
 * Nome: live.js
 * Propósito: painel de execução, com o estado do redutor em tempo real.
 * Responsabilidade: frontend/componente — desenha plano, chamadas ao modelo, arquivos e verificações.
 * Componentes: LivePanel (componente Vue), filtros reativos, delegated handlers (onClick, onSearch).
 * Dependências: `../store.js` (estado e seleção de tarefa), `../live-view.js` (renderizadores),
 *   `../ui.js` (ícones).
 * Observações: os blocos são redesenhados pelo contador `state.liveState.version`.
 */
import { state, refreshTasks, selectTask } from "../store.js";
import {
  renderActivity,
  renderFiles,
  renderFilters,
  renderHeader,
  renderMetrics,
  renderOutputs,
  renderTools,
  renderTree,
  renderVerification,
} from "../live-view.js";
import { icon } from "../ui.js";

/**
 * Painel de execução: acompanha a run em tempo real com filtros, árvore e diffs.
 *
 * @returns {object} Objeto de opções do Vue com `setup()` e `template`.
 */
export const LivePanel = {
  name: "LivePanel",
  setup() {
    const filters = Vue.reactive({
      categories: new Set(),
      taskId: null,
      errorsOnly: false,
      text: "",
    });
    // Conjuntos de ids: o Vue detecta mudanças em Set reativo (Vue 3).
    const expanded = Vue.reactive(new Set());
    const collapsed = Vue.reactive(new Set());
    const openSeqs = Vue.reactive(new Set());
    const selected = Vue.ref(null);

    const header = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderHeader(state.liveState.data) : "";
    });
    const filterBar = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderFilters(state.liveState.data, filters) : "";
    });
    const tree = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data
        ? renderTree(state.liveState.data, { expanded, collapsed, selected: selected.value })
        : "";
    });
    const outputs = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderOutputs(state.liveState.data, filters) : "";
    });
    const files = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderFiles(state.liveState.data, filters, openSeqs) : "";
    });
    const verifications = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderVerification(state.liveState.data, filters) : "";
    });
    const tools = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderTools(state.liveState.data, filters) : "";
    });
    const activity = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderActivity(state.liveState.data, filters, 120) : "";
    });
    const metrics = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderMetrics(state.liveState.data) : "";
    });

    /**
     * Um único handler para todas as interações do painel (delegação de eventos).
     *
     * @param {MouseEvent} event Evento de clique no painel.
     * @returns {void}
     * Observações: alterna categorias, "só falhas", a tarefa selecionada, o desdobramento da
     * árvore e a abertura do diff.
     */
    function onClick(event) {
      const target = event.target.closest("[data-obs-cat], [data-obs-errors], [data-obs-clear-task], [data-obs-toggle], [data-obs-task], [data-obs-file]");
      if (!target) return;

      if (target.dataset.obsCat) {
        const category = target.dataset.obsCat;
        if (filters.categories.has(category)) filters.categories.delete(category);
        else filters.categories.add(category);
        bump();
        return;
      }
      if (target.dataset.obsErrors !== undefined) {
        filters.errorsOnly = !filters.errorsOnly;
        bump();
        return;
      }
      if (target.dataset.obsClearTask !== undefined) {
        filters.taskId = null;
        bump();
        return;
      }
      if (target.dataset.obsToggle) {
        const id = target.dataset.obsToggle;
        if (expanded.has(id)) expanded.delete(id);
        else expanded.add(id);
        bump();
        return;
      }
      if (target.dataset.obsFile !== undefined) {
        const seq = Number(target.dataset.obsFile);
        if (openSeqs.has(seq)) openSeqs.delete(seq);
        else openSeqs.add(seq);
        bump();
        return;
      }
      if (target.dataset.obsTask) {
        const id = target.dataset.obsTask;
        if (!id) return;
        selected.value = id;
        filters.taskId = id;
        selectTask(id);
        bump();
      }
    }

    /**
     * Captura o texto digitado no campo de busca de filtros.
     *
     * @param {Event} event Evento de input do campo de busca.
     * @returns {void}
     */
    function onSearch(event) {
      const target = event.target.closest("[data-obs-text]");
      if (!target) return;
      filters.text = target.value;
      bump();
    }

    /**
     * Mudou algo no redutor: força o redesenho dos blocos.
     *
     * @returns {void}
     */
    function bump() {
      state.liveState.version += 1;
    }

    Vue.watch(
      () => filters.text,
      () => bump(),
    );

    return {
      state,
      filters,
      expanded,
      collapsed,
      openSeqs,
      header,
      filterBar,
      tree,
      outputs,
      files,
      verifications,
      tools,
      activity,
      metrics,
      onClick,
      onSearch,
      refreshTasks,
      icon,
    };
  },
  template: `
    <section class="live-view" @click="onClick" @input="onSearch">
      <div v-if="!state.liveState.data" class="chat-empty">
        <h2>Nenhuma execução ativa</h2>
        <p>Quando você enviar um pedido, o acompanhamento da execução aparece aqui: plano, chamadas ao modelo, arquivos alterados e verificações.</p>
      </div>
      <template v-else>
        <header class="obs-head" v-html="header"></header>

        <div class="obs-filters" v-html="filterBar"></div>

        <details class="obs-area" open>
          <summary>Plano da execução</summary>
          <div class="obs-tree" v-html="tree"></div>
        </details>

        <details class="obs-area" open>
          <summary>Chamadas ao modelo</summary>
          <div v-html="outputs"></div>
        </details>

        <details class="obs-area">
          <summary>Arquivos e ferramentas</summary>
          <div v-html="files"></div>
          <div v-html="tools"></div>
        </details>

        <details class="obs-area">
          <summary>Verificações</summary>
          <div v-html="verifications"></div>
        </details>

        <details class="obs-area" open>
          <summary>Atividade</summary>
          <ul class="obs-activity" v-html="activity"></ul>
        </details>

        <details class="obs-area">
          <summary>Métricas</summary>
          <div v-html="metrics"></div>
        </details>
      </template>
    </section>
  `,
};
