// web/static/assets/app/components/settings.js — Ajustes: aparência, execução, projetos e atalhos
import {
  state,
  setTheme,
  setDensity,
  loadProviders,
  renameProject,
  moveProject,
  deleteProject,
  loadRemote,
  toast,
} from "../store.js";
import { api } from "../api.js";
import { icon } from "../ui.js";

const TABS = [
  { id: "geral", label: "Geral", icon: "cog" },
  { id: "execucao", label: "Execução", icon: "play" },
  { id: "projetos", label: "Projetos", icon: "folder" },
  { id: "atalhos", label: "Atalhos", icon: "keyboard" },
  { id: "sobre", label: "Sobre", icon: "info" },
];

const SHORTCUTS = [
  ["⌘K / Ctrl+K", "Abrir a paleta de comandos"],
  ["⌘⇧P / Ctrl+Shift+P", "Paleta de comandos (alternativo)"],
  ["⌘B / Ctrl+B", "Mostrar ou esconder a barra lateral"],
  ["⌘J / Ctrl+J", "Focar o campo de objetivo"],
  ["Esc", "Fechar painéis e diálogos"],
  ["Enter", "Enviar o pedido"],
  ["Shift+Enter", "Quebra de linha no campo de objetivo"],
];

export const SettingsView = {
  name: "SettingsView",
  emits: ["new-project", "move-folder"],
  setup(props, { emit }) {
    const renaming = Vue.ref(null);
    const renameValue = Vue.ref("");
    const moving = Vue.ref(null);
    const remotes = Vue.reactive({});

    const models = Vue.computed(() => state.providerModels[state.provider] || []);

    async function ensureModels() {
      if (!state.providerModels[state.provider]) {
        await loadProviders();
        const { loadModels } = await import("../store.js");
        await loadModels(state.provider);
      }
    }

    Vue.onMounted(ensureModels);

    function startRename(project) {
      renaming.value = project.id;
      renameValue.value = project.name || "";
    }

    async function confirmRename(project) {
      const name = renameValue.value.trim();
      renaming.value = null;
      if (name && name !== project.name) await renameProject(project, name);
    }

    async function showRemote(project) {
      const saved = await loadRemote(project);
      remotes[project.id] = saved || {
        host: "",
        port: 22,
        user: "",
        key_path: "",
        root: ".",
        shell: "posix",
        timeout: 120,
      };
      emit("remote", { project, config: remotes[project.id] });
    }

    function pickFolder(project) {
      moving.value = project.id;
      emit("move-folder", project);
    }

    return {
      state,
      TABS,
      SHORTCUTS,
      renaming,
      renameValue,
      moving,
      models,
      setTheme,
      setDensity,
      renameProject,
      moveProject,
      deleteProject,
      startRename,
      confirmRename,
      pickFolder,
      showRemote,
      remotes,
      toast,
      icon,
      emit,
    };
  },
  template: `
    <section class="providers">
      <header class="page-head">
        <div>
          <h2>Ajustes</h2>
          <p class="muted">Tudo o que muda o comportamento do Callidus: aparência, execução, projetos e atalhos.</p>
        </div>
      </header>

      <div class="tabs settings-tabs" role="tablist">
        <button
          type="button"
          v-for="tab in TABS"
          :key="tab.id"
          class="tab tab-labeled"
          :class="{ active: state.settingsTab === tab.id }"
          role="tab"
          :aria-selected="state.settingsTab === tab.id"
          @click="state.settingsTab = tab.id"
        >
          <span v-html="icon(tab.icon, 15)"></span>
          <span class="tab-text">{{ tab.label }}</span>
        </button>
      </div>

      <div class="settings-body" v-if="state.settingsTab === 'geral'">
        <div class="card settings-card">
          <h3>Aparência</h3>
          <label class="field">
            <span>Tema</span>
            <div class="segmented" role="group">
              <button type="button" :class="{ active: state.theme === 'dark' }" @click="setTheme('dark')">Escuro</button>
              <button type="button" :class="{ active: state.theme === 'light' }" @click="setTheme('light')">Claro</button>
            </div>
          </label>
          <label class="field">
            <span>Densidade</span>
            <div class="segmented" role="group">
              <button type="button" :class="{ active: state.density === 'confortavel' }" @click="setDensity('confortavel')">Confortável</button>
              <button type="button" :class="{ active: state.density === 'compacta' }" @click="setDensity('compacta')">Compacta</button>
            </div>
          </label>
          <p class="muted small">O tema e a densidade ficam guardados neste navegador.</p>
        </div>
      </div>

      <div class="settings-body" v-else-if="state.settingsTab === 'execucao'">
        <div class="card settings-card">
          <h3>Padrões de execução</h3>
          <label class="field">
            <span>Provedor padrão</span>
            <select v-model="state.provider">
              <option v-for="item in state.providers" :key="item.name" :value="item.name">{{ item.name }}</option>
            </select>
          </label>
          <label class="field">
            <span>Modelo padrão</span>
            <select v-model="state.modelId">
              <option v-if="!models.length" :value="state.modelId">{{ state.modelId || 'do provedor' }}</option>
              <option v-for="item in models" :key="item" :value="item">{{ item }}</option>
            </select>
            <small class="muted">Os modelos vêm do servidor do provedor selecionado.</small>
          </label>
          <label class="field">
            <span>Navegador</span>
            <select v-model="state.browserMode">
              <option value="off">Desligado</option>
              <option value="headless">Invisível</option>
              <option value="visible">Janela visível</option>
            </select>
          </label>
          <label class="field check">
            <input type="checkbox" v-model="state.approveTools" />
            <span>Permitir ferramentas”（comandos, scripts e escrita de arquivos)</span>
          </label>
        </div>
      </div>

      <div class="settings-body" v-else-if="state.settingsTab === 'projetos'">
        <div class="page-head compact-head">
          <div>
            <h3>Projetos</h3>
            <p class="muted small">Remover um projeto apaga conversas, tarefas e memórias dele. Os arquivos da pasta ficam intactos.</p>
          </div>
          <button type="button" class="btn-primary" @click="$emit('new-project')">
            <span v-html="icon('plus', 15)"></span> Novo projeto
          </button>
        </div>
        <div
          class="project-row"
          v-for="project in state.projects"
          :key="project.id"
        >
          <span class="side-ico" v-html="icon('folder', 15)"></span>
          <div class="grow">
            <template v-if="renaming === project.id">
              <input
                class="inline-input"
                v-model="renameValue"
                type="text"
                @keyup.enter="confirmRename(project)"
                @keyup.esc="renaming = null"
                @blur="confirmRename(project)"
              />
            </template>
            <template v-else>
              <span class="name">{{ project.name }}</span>
              <span class="path">{{ project.root_path }}</span>
            </template>
          </div>
          <button type="button" class="icon-btn ghost" title="Renomear" aria-label="Renomear" @click="startRename(project)" v-html="icon('pencil', 15)"></button>
          <button type="button" class="icon-btn ghost" title="Trocar pasta" aria-label="Trocar pasta" :disabled="moving === project.id" @click="pickFolder(project)" v-html="icon('folder', 15)"></button>
          <button type="button" class="icon-btn ghost" title="Computador remoto" aria-label="Computador remoto" @click="showRemote(project)" v-html="icon('server', 15)"></button>
          <button type="button" class="icon-btn ghost danger" title="Remover projeto" aria-label="Remover projeto" @click="deleteProject(project)" v-html="icon('trash', 15)"></button>
        </div>
        <p class="muted" v-if="!state.projects.length">Nenhum projeto ainda.</p>
      </div>

      <div class="settings-body" v-else-if="state.settingsTab === 'atalhos'">
        <div class="card settings-card">
          <h3>Atalhos</h3>
          <dl class="kv shortcuts">
            <div v-for="row in SHORTCUTS" :key="row[0]">
              <dt><span class="kbd">{{ row[0] }}</span></dt>
              <dd>{{ row[1] }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <div class="settings-body" v-else>
        <div class="card settings-card">
          <h3>Callidus</h3>
          <p class="muted">
            Agente de desenvolvimento otimizado para modelos locais pequenos.
            Versão {{ state.uiDefaults?.version || '0.5' }} · API local em {{ state.apiHost || '127.0.0.1:8765' }}.
          </p>
          <p class="muted small">
            A interface é uma SPA Vue 3 servida pela própria API. Nenhum dado sai da máquina além
            das chamadas ao provedor de modelo configurado.
          </p>
        </div>
      </div>
    </section>
  `,
};
