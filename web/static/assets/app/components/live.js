// web/static/assets/app/components/live.js — painel de acompanhamento (reduzir + stream)
import { state, refreshTasks } from "../store.js";
import {
  renderActivity,
  renderFiles,
  renderHeader,
  renderMetrics,
  renderOutputs,
  renderTools,
  renderTree,
  renderVerification,
} from "../live-view.js";
import { icon } from "../ui.js";

export const LivePanel = {
  name: "LivePanel",
  setup() {
    const filters = Vue.reactive({
      categories: new Set(),
      taskId: null,
      errorsOnly: false,
      text: "",
    });
    const expanded = Vue.reactive(new Set());
    const collapsed = Vue.reactive(new Set());

    const header = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderHeader(state.liveState.data) : "";
    });
    const tree = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data
        ? renderTree(state.liveState.data, { expanded, collapsed, selected: state.selectedTaskId })
        : "";
    });
    const outputs = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderOutputs(state.liveState.data, filters) : "";
    });
    const files = Vue.computed(() => {
      void state.liveState.version;
      return state.liveState.data ? renderFiles(state.liveState.data, filters, new Set()) : "";
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

    return {
      state,
      filters,
      expanded,
      collapsed,
      header,
      tree,
      outputs,
      files,
      verifications,
      tools,
      activity,
      metrics,
      refreshTasks,
      icon,
    };
  },
  template: `
    <section class="live-view">
      <div v-if="!state.liveState.data" class="boot">
        <span class="spinner"></span> Acompanhando a execução…
      </div>
      <template v-else>
        <header class="obs-head" v-html="header"></header>

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
