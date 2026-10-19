// web/static/assets/app/components/topbar.js
import { state, setTheme, cancelRun, pauseRun, stepRun, autoRun, refreshTasks, toast, openView } from "../store.js";
import { icon } from "../ui.js";
import { api } from "../api.js";

export const TopBar = {
  name: "TopBar",
  emits: ["toggle-details", "new-project", "rename", "folder", "toggle-rail", "open-palette"],
  setup() {
    const busy = Vue.computed(() => Boolean(state.currentRun));
    const branches = Vue.computed(() => state.conversation?.branches || []);

    async function activateBranch(branchId) {
      if (!state.conversation || !branchId) return;
      try {
        await api(`/conversations/${state.conversation.id}/branches/${branchId}/activate`, {
          method: "POST",
        });
        await refreshTasks();
        toast("Ramo ativado", "ok");
      } catch (err) {
        toast(err.message || "Falha ao trocar de ramo", "error");
      }
    }

    return {
      state,
      busy,
      branches,
      activateBranch,
      setTheme,
      cancelRun,
      pauseRun,
      stepRun,
      autoRun,
      refreshTasks,
      openView,
      icon,
    };
  },
  template: `
    <header class="topbar">
      <button
        type="button"
        class="icon-btn ghost rail-toggle"
        title="Projetos e conversas (⌘B)"
        aria-label="Abrir barra lateral"
        @click="$emit('toggle-rail')"
        v-html="icon('panel', 15)"
      ></button>

      <div class="topbar-left">
        <div class="title-row">
          <h1>{{ state.conversation?.title || state.selectedProject?.name || 'Callidus' }}</h1>
          <button type="button" class="icon-btn ghost" title="Renomear" aria-label="Renomear" @click="$emit('rename')" v-html="icon('pencil', 15)"></button>
          <button type="button" class="icon-btn ghost" title="Pasta do projeto" aria-label="Pasta do projeto" @click="$emit('folder')" v-html="icon('folder', 15)"></button>
        </div>
        <div class="branch-switch" v-if="branches.length > 1">
          <span class="muted small">Ramo</span>
          <select aria-label="Ramo da conversa" @change="activateBranch($event.target.value)">
            <option v-for="branch in branches" :key="branch.id" :value="branch.id" :selected="branch.id === state.conversation.active_branch_id">
              {{ branch.id === state.conversation.active_branch_id ? 'atual' : branch.id.slice(0, 8) }}
            </option>
          </select>
        </div>
        <p class="muted topbar-sub" v-else>
          <span v-if="state.selectedProject?.root_path">{{ state.selectedProject.root_path }}</span>
          <span v-else>Sem pasta escolhida — vale a pasta do usuário.</span>
        </p>
      </div>

      <div class="topbar-right">
        <div class="segmented" role="tablist" aria-label="Seção">
          <button
            type="button"
            :class="{ active: state.view === 'chat' }"
            title="Conversa"
            aria-label="Conversa"
            @click="openView('chat')"
          >
            <span v-html="icon('chat', 15)"></span><span class="seg-label">Conversa</span>
          </button>
          <button
            type="button"
            :class="{ active: state.view === 'live' }"
            :disabled="!state.currentRun"
            title="Acompanhamento"
            aria-label="Acompanhamento"
            @click="openView('live')"
          >
            <span v-html="icon('chart', 15)"></span><span class="seg-label">Acompanhamento</span>
          </button>
          <button
            type="button"
            :class="{ active: state.view === 'providers' }"
            title="Provedores"
            aria-label="Provedores"
            @click="openView('providers')"
          >
            <span v-html="icon('server', 15)"></span><span class="seg-label">Provedores</span>
          </button>
        </div>

        <div class="run-controls topbar-run" v-if="state.view === 'chat'">
          <button type="button" class="icon-btn" title="Um passo" aria-label="Um passo" :disabled="!busy" @click="stepRun()" v-html="icon('play', 15)"></button>
          <button type="button" class="icon-btn" title="Pausar" aria-label="Pausar" :disabled="!busy" @click="pauseRun()" v-html="icon('pause', 15)"></button>
          <button type="button" class="icon-btn danger" title="Parar" aria-label="Parar" :disabled="!busy" @click="cancelRun()" v-html="icon('stop', 15)"></button>
          <button type="button" class="btn-ghost small" :disabled="!busy" @click="autoRun()">Auto</button>
        </div>

        <button
          type="button"
          class="icon-btn ghost"
          title="Comandos (⌘K)"
          aria-label="Abrir paleta de comandos"
          @click="$emit('open-palette')"
          v-html="icon('search', 15)"
        ></button>
        <button
          type="button"
          class="icon-btn ghost"
          :title="state.theme === 'dark' ? 'Tema claro' : 'Tema escuro'"
          aria-label="Alternar tema"
          @click="setTheme(state.theme === 'dark' ? 'light' : 'dark')"
          v-html="icon(state.theme === 'dark' ? 'sun' : 'moon', 15)"
        ></button>
        <button
          type="button"
          class="icon-btn ghost"
          :class="{ active: state.detailsOpen }"
          title="Painel de detalhes"
          aria-label="Painel de detalhes"
          @click="$emit('toggle-details')"
          v-html="icon('panel', 15)"
        ></button>
      </div>
    </header>
  `,
};
