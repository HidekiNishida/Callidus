// web/static/assets/app/main.js — bootstrap da interface (Vue 3)
import { api } from "./api.js";
import {
  state,
  bootstrap,
  selectProject,
  selectConversation,
  toast,
  refreshTasks,
  disconnectStream,
  stepRun,
  autoRun,
  pauseRun,
  cancelRun,
  openView,
  watchViewport,
} from "./store.js";
import { icon } from "./ui.js";
import { Sidebar } from "./components/sidebar.js";
import { TopBar } from "./components/topbar.js";
import { ChatView } from "./components/chat.js";
import { DetailsPanel } from "./components/details.js";
import { ProvidersView } from "./components/providers.js";
import { SettingsView } from "./components/settings.js";
import { LivePanel } from "./components/live.js";
import { CommandPalette } from "./components/palette.js";

const { createApp, reactive, ref, computed, onMounted, onBeforeUnmount } = Vue;

const NAV_ITEMS = [
  { id: "chat", label: "Conversa", icon: "chat" },
  { id: "live", label: "Execução", icon: "chart" },
  { id: "providers", label: "Provedores", icon: "server" },
  { id: "settings", label: "Ajustes", icon: "cog" },
];

const App = {
  components: {
    Sidebar,
    TopBar,
    ChatView,
    DetailsPanel,
    ProvidersView,
    SettingsView,
    LivePanel,
    CommandPalette,
  },
  setup() {
    const modal = reactive({ kind: null, name: "", rootPath: "", path: "", entries: [] });
    const booting = ref(true);
    const bootError = ref("");

    onMounted(async () => {
      watchViewport();
      try {
        await bootstrap();
      } catch (err) {
        bootError.value = err.message || "falha ao iniciar";
      } finally {
        booting.value = false;
      }
      window.addEventListener("keydown", onGlobalKey);
      window.addEventListener("callidus:new-project", newProject);
      window.addEventListener("callidus:rename-conversation", renameConversation);
      window.addEventListener("callidus:step", stepRun);
      window.addEventListener("callidus:auto", autoRun);
      window.addEventListener("callidus:pause", pauseRun);
      window.addEventListener("callidus:cancel", cancelRun);
    });

    onBeforeUnmount(() => {
      window.removeEventListener("keydown", onGlobalKey);
      disconnectStream();
    });

    function isTyping(event) {
      const tag = event.target?.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable;
    }

    function onGlobalKey(event) {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        state.paletteOpen = !state.paletteOpen;
        return;
      }
      if (meta && event.key.toLowerCase() === "b") {
        event.preventDefault();
        state.railOpen = !state.railOpen;
        return;
      }
      if (meta && event.key.toLowerCase() === "j") {
        event.preventDefault();
        openView("chat");
        document.querySelector(".composer textarea")?.focus();
        return;
      }
      if (event.key === "Escape") {
        if (state.paletteOpen) state.paletteOpen = false;
        else if (modal.kind) modal.kind = null;
        else if (state.railOpen) state.railOpen = false;
      }
      if (!isTyping(event) && !meta && event.key === "/") {
        event.preventDefault();
        document.querySelector(".composer textarea")?.focus();
      }
    }

    async function newProject() {
      modal.kind = "project";
      modal.name = "";
      modal.rootPath = "";
    }

    async function createProject() {
      if (!modal.name.trim()) {
        toast("Dê um nome ao projeto", "error");
        return;
      }
      try {
        const project = await api("/projects", {
          method: "POST",
          body: JSON.stringify({ name: modal.name.trim(), root_path: modal.rootPath.trim() }),
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

    const navItems = computed(() => NAV_ITEMS);

    return {
      state,
      modal,
      booting,
      bootError,
      navItems,
      newProject,
      createProject,
      openFolder,
      browse,
      useFolder,
      renameConversation,
      selectProject,
      selectConversation,
      disconnectStream,
      openView,
      icon,
    };
  },
  template: `
    <div class="shell" :class="['view-' + state.view, 'density-' + state.density]">
      <TopBar
        @new-project="newProject()"
        @rename="renameConversation()"
        @folder="openFolder()"
        @toggle-details="state.detailsOpen = !state.detailsOpen"
        @toggle-rail="state.railOpen = !state.railOpen"
        @open-palette="state.paletteOpen = true"
      />

      <div class="body">
        <Transition name="fade">
          <div class="scrim" v-if="state.railOpen" @click="state.railOpen = false"></div>
        </Transition>

        <Transition name="fade">
          <div
            class="scrim"
            v-if="state.compact && state.detailsOpen && state.view === 'chat'"
            @click="state.detailsOpen = false"
          ></div>
        </Transition>

        <Sidebar :class="{ open: state.railOpen }" @new-project="newProject()" />

        <main class="main">
          <div v-if="booting" class="boot">
            <span class="spinner"></span> Carregando o Callidus…
          </div>
          <div v-else-if="bootError" class="boot error">
            {{ bootError }}
          </div>
          <Transition v-else name="view" mode="out-in">
            <ChatView v-if="state.view === 'chat'" key="chat" />
            <LivePanel v-else-if="state.view === 'live'" key="live" />
            <ProvidersView v-else-if="state.view === 'providers'" key="providers" />
            <SettingsView v-else key="settings" @new-project="newProject()" />
          </Transition>
        </main>

        <DetailsPanel v-if="state.view === 'chat'" :class="{ open: state.detailsOpen }" />
      </div>

      <footer class="statusbar">
        <span class="dot" :class="state.currentRun ? 'dot-live' : 'dot-idle'"></span>
        <span>{{ state.currentRun ? 'Run ' + state.currentRun.status : 'idle' }}</span>
        <span class="muted">{{ state.provider }}<template v-if="state.modelId"> · {{ state.modelId }}</template></span>
        <span class="muted right">{{ state.uiDefaults?.version || 'v0.5' }}</span>
      </footer>

      <nav class="bottom-nav" aria-label="Navegação principal">
        <button
          type="button"
          v-for="item in navItems"
          :key="item.id"
          :class="{ active: state.view === item.id }"
          :aria-current="state.view === item.id ? 'page' : null"
          @click="openView(item.id)"
        >
          <span class="nav-ico" v-html="icon(item.icon, 19)"></span>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <CommandPalette />

      <TransitionGroup tag="div" class="toast-stack" name="toast">
        <div v-for="item in state.toasts" :key="item.id" class="toast" :class="item.type">{{ item.message }}</div>
      </TransitionGroup>

      <Transition name="fade">
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
      </Transition>

      <Transition name="fade">
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
      </Transition>
    </div>
  `,
};

createApp(App).mount("#app");
