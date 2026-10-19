// web/static/assets/app/main.js — bootstrap da interface (Vue 3)
import { api } from "./api.js";
import { state, bootstrap, selectProject, selectConversation, toast, refreshTasks, disconnectStream } from "./store.js";
import { icon } from "./ui.js";
import { Sidebar } from "./components/sidebar.js";
import { TopBar } from "./components/topbar.js";
import { ChatView } from "./components/chat.js";
import { DetailsPanel } from "./components/details.js";
import { ProvidersView } from "./components/providers.js";
import { LivePanel } from "./components/live.js";

const { createApp, reactive, ref, computed, onMounted } = Vue;

const App = {
  components: { Sidebar, TopBar, ChatView, DetailsPanel, ProvidersView, LivePanel },
  setup() {
    const modal = reactive({ kind: null, name: "", rootPath: "", path: "", entries: [] });
    const booting = ref(true);
    const bootError = ref("");

    onMounted(async () => {
      try {
        await bootstrap();
      } catch (err) {
        bootError.value = err.message || "falha ao iniciar";
      } finally {
        booting.value = false;
      }
    });

    async function newProject() {
      modal.kind = "project";
      modal.name = "";
      modal.rootPath = "";
    }

    async function createProject() {
      if (!modal.name.trim()) return;
      try {
        const project = await api("/projects", {
          method: "POST",
          body: JSON.stringify({ name: modal.name.trim(), root_path: modal.rootPath.trim() || null }),
        });
        await bootstrap();
        await selectProject(project);
        modal.kind = null;
        toast(`Projeto “${project.name}” criado`, "ok");
      } catch (err) {
        toast(err.message || "Falha ao criar o projeto", "error");
      }
    }

    async function openFolder() {
      modal.kind = "folder";
      modal.path = state.selectedProject?.root_path || "";
      await browse(modal.path);
    }

    async function browse(path) {
      try {
        const data = await api(`/fs/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
        modal.path = data.path || "";
        modal.entries = data.entries || [];
      } catch (err) {
        toast(err.message || "Falha ao listar a pasta", "error");
      }
    }

    async function useFolder() {
      if (!state.selectedProject) {
        toast("Crie ou selecione um projeto antes", "error");
        return;
      }
      try {
        await api(`/projects/${state.selectedProject.id}`, {
          method: "PATCH",
          body: JSON.stringify({ root_path: modal.path }),
        });
        await bootstrap();
        modal.kind = null;
        toast("Pasta atualizada", "ok");
      } catch (err) {
        toast(err.message || "Falha ao trocar a pasta", "error");
      }
    }

    async function renameConversation() {
      if (!state.conversation) return;
      const title = window.prompt("Novo nome", state.conversation.title || "");
      if (!title || !title.trim()) return;
      try {
        await api(`/conversations/${state.conversation.id}`, {
          method: "PATCH",
          body: JSON.stringify({ title: title.trim() }),
        });
        await refreshTasks();
        toast("Conversa renomeada", "ok");
      } catch (err) {
        toast(err.message || "Falha ao renomear", "error");
      }
    }

    const shell = computed(() => state.view);

    return {
      state,
      modal,
      booting,
      bootError,
      shell,
      newProject,
      createProject,
      openFolder,
      browse,
      useFolder,
      renameConversation,
      selectProject,
      selectConversation,
      disconnectStream,
      icon,
    };
  },
  template: `
    <div class="shell" :class="'view-' + state.view">
      <TopBar
        @new-project="newProject()"
        @rename="renameConversation()"
        @folder="openFolder()"
        @toggle-details="state.detailsOpen = !state.detailsOpen"
      />

      <div class="body">
        <Sidebar @new-project="newProject()" />

        <main class="main">
          <div v-if="booting" class="boot">
            <span class="spinner"></span> Carregando o Callidus…
          </div>
          <div v-else-if="bootError" class="boot error">
            {{ bootError }}
          </div>
          <ChatView v-else-if="state.view === 'chat'" />
          <LivePanel v-else-if="state.view === 'live'" />
          <ProvidersView v-else />
        </main>

        <DetailsPanel v-if="state.view === 'chat'" />
      </div>

      <footer class="statusbar">
        <span class="dot" :class="state.currentRun ? 'dot-live' : 'dot-idle'"></span>
        <span>{{ state.currentRun ? 'Run ' + state.currentRun.status : 'idle' }}</span>
        <span class="muted">{{ state.provider }}<template v-if="state.modelId"> · {{ state.modelId }}</template></span>
        <span class="muted right">{{ state.uiDefaults?.version || 'v0.5' }}</span>
      </footer>

      <div class="toast-stack">
        <div v-for="item in state.toasts" :key="item.id" class="toast" :class="item.type">{{ item.message }}</div>
      </div>

      <div class="modal" v-if="modal.kind === 'project'" @click.self="modal.kind = null">
        <div class="modal-card">
          <header class="modal-head">
            <h3>Novo projeto</h3>
            <button type="button" class="icon-btn ghost" @click="modal.kind = null" aria-label="Fechar">×</button>
          </header>
          <label class="field">
            <span>Nome</span>
            <input v-model="modal.name" type="text" placeholder="ex.: meu-site" @keyup.enter="createProject()" />
          </label>
          <label class="field">
            <span>Pasta (opcional)</span>
            <input v-model="modal.rootPath" type="text" placeholder="/Users/.../meu-site" />
            <small class="muted">Sem pasta, o Callidus trabalha na pasta do usuário.</small>
          </label>
          <div class="form-actions">
            <button type="button" class="btn-primary" @click="createProject()">Criar</button>
            <button type="button" class="btn-ghost" @click="modal.kind = null">Cancelar</button>
          </div>
        </div>
      </div>

      <div class="modal" v-if="modal.kind === 'folder'" @click.self="modal.kind = null">
        <div class="modal-card">
          <header class="modal-head">
            <h3>Escolher pasta</h3>
            <button type="button" class="icon-btn ghost" @click="modal.kind = null" aria-label="Fechar">×</button>
          </header>
          <p class="muted small path">{{ modal.path || '—' }}</p>
          <ul class="folder-list">
            <li v-for="entry in modal.entries" :key="entry.path">
              <button type="button" class="folder-item" @click="browse(entry.path)">
                <span v-html="icon(entry.is_dir ? 'folder' : 'file', 14)"></span>
                <span>{{ entry.name }}</span>
              </button>
            </li>
          </ul>
          <div class="form-actions">
            <button type="button" class="btn-primary" @click="useFolder()">Usar esta pasta</button>
            <button type="button" class="btn-ghost" @click="modal.kind = null">Cancelar</button>
          </div>
        </div>
      </div>
    </div>
  `,
};

createApp(App).mount("#app");
