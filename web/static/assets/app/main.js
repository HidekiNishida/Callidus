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
  moveProject,
  saveRemote,
  clearRemote,
  testRemote,
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
import { AutomationsView } from "./components/automations.js";

const { createApp, reactive, ref, computed, onMounted, onBeforeUnmount } = Vue;

const NAV_ITEMS = [
  { id: "chat", label: "Conversa", icon: "chat" },
  { id: "live", label: "Execução", icon: "chart" },
  { id: "providers", label: "Provedores", icon: "server" },
  { id: "automations", label: "Automações", icon: "clock" },
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
    AutomationsView,
  },
  setup() {
    const modal = reactive({
      kind: null,
      purpose: null,
      name: "",
      rootPath: "",
      path: "",
      entries: [],
      newFolder: "",
      remote: {
        host: "",
        port: 22,
        user: "",
        key_path: "",
        root: ".",
        shell: "posix",
        timeout: 120,
      },
      remoteProject: null,
      remoteResult: null,
      remoteBusy: false,
    });
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
      modal.purpose = "project-folder";
      modal.path = state.selectedProject?.root_path || "";
      await browse(modal.path);
    }

    async function pickFolderForProject() {
      modal.kind = "folder";
      modal.purpose = "new-project";
      modal.path = modal.rootPath || state.selectedProject?.root_path || "";
      await browse(modal.path);
    }

    async function openRemote(payload) {
      modal.kind = "remote";
      modal.remoteProject = payload.project;
      modal.remote = { ...payload.config };
      modal.remoteResult = null;
    }

    async function saveRemoteConfig() {
      const project = modal.remoteProject;
      if (!project) return;
      const config = {
        host: String(modal.remote.host || "").trim(),
        port: Number(modal.remote.port || 22),
        user: String(modal.remote.user || "").trim() || null,
        key_path: String(modal.remote.key_path || "").trim() || null,
        root: String(modal.remote.root || ".").trim() || ".",
        shell: modal.remote.shell || "posix",
        timeout: Number(modal.remote.timeout || 120),
      };
      if (!config.host) {
        toast("Informe o host do computador remoto", "error");
        return;
      }
      modal.remoteBusy = true;
      try {
        await saveRemote(project, config);
        modal.kind = null;
      } catch (err) {
        toast(err.message || "Falha ao salvar o computador remoto", "error");
      } finally {
        modal.remoteBusy = false;
      }
    }

    async function checkRemote() {
      const project = modal.remoteProject;
      if (!project) return;
      modal.remoteBusy = true;
      modal.remoteResult = null;
      try {
        const result = await testRemote(project);
        modal.remoteResult = result;
      } finally {
        modal.remoteBusy = false;
      }
    }

    async function removeRemote() {
      const project = modal.remoteProject;
      if (!project) return;
      try {
        await clearRemote(project);
        modal.kind = null;
      } catch (err) {
        toast(err.message || "Falha ao remover o computador remoto", "error");
      }
    }

    async function createFolder() {
      const name = (modal.newFolder || "").trim();
      if (!name) return;
      try {
        const data = await api("/fs/mkdir", {
          method: "POST",
          body: JSON.stringify({ path: modal.path, name }),
        });
        modal.path = data.path || modal.path;
        modal.entries = data.entries || [];
        modal.newFolder = "";
        toast(`Pasta “${name}” criada`, "ok");
      } catch (err) {
        toast(err.message || "Falha ao criar a pasta", "error");
      }
    }

    async function browse(path) {
      try {
        const data = await api(`/fs/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
        modal.path = data.path || "";
        modal.entries = data.entries || [];
      } catch (err) {
        // Pasta fora do alcance da navegação (ex.: /tmp): mostra a pasta do usuário.
        if (path) {
          await browse("");
          toast("Pasta fora do alcance da navegação — mostrando a pasta do usuário", "info");
          return;
        }
        toast(err.message || "Falha ao listar a pasta", "error");
      }
    }

    async function useFolder() {
      if (modal.kind === "move-folder" && modal.project) {
        const project = modal.project;
        modal.kind = null;
        await moveProject(project, modal.path);
        return;
      }
      if (modal.purpose === "new-project") {
        modal.rootPath = modal.path;
        modal.kind = "project";
        modal.purpose = null;
        return;
      }
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

    async function moveFolderTo(project) {
      modal.kind = "move-folder";
      modal.purpose = "move-folder";
      modal.project = project;
      modal.path = project.root_path || "";
      await browse(modal.path);
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
      openRemote,
      saveRemoteConfig,
      checkRemote,
      removeRemote,
      pickFolderForProject,
      createFolder,
      browse,
      useFolder,
      renameConversation,
      moveFolderTo,
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
            <AutomationsView v-else-if="state.view === 'automations'" key="automations" />
            <SettingsView
              v-else
              key="settings"
              @new-project="newProject()"
              @move-folder="moveFolderTo($event)"
              @remote="openRemote($event)"
            />
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
          :disabled="item.id === 'live' && !state.currentRun"
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
              <span>Pasta do projeto</span>
              <div class="path-row">
                <input v-model="modal.rootPath" type="text" placeholder="sem pasta (usa a pasta do usuário)" />
                <button type="button" class="btn-ghost small" @click="pickFolderForProject()">Escolher…</button>
              </div>
              <small class="muted">Use o seletor para navegar e criar pastas.</small>
            </label>
            <div class="form-actions">
              <button type="button" class="btn-primary" @click="createProject()">Criar</button>
              <button type="button" class="btn-ghost" @click="modal.kind = null">Cancelar</button>
            </div>
          </div>
        </div>
      </Transition>

      <Transition name="fade">
        <div class="modal" v-if="modal.kind === 'remote'" @click.self="modal.kind = null">
          <div class="modal-card">
            <header class="modal-head">
              <h3>Computador remoto — {{ modal.remoteProject?.name }}</h3>
              <button type="button" class="icon-btn ghost" @click="modal.kind = null" aria-label="Fechar">×</button>
            </header>
            <p class="muted small">
              As ações do projeto (comandos, leitura, escrita e listagem) passam a rodar neste
              computador por SSH. Serve para servidores Linux/macOS e Windows (PowerShell).
            </p>
            <div class="grid-2">
              <label class="field">
                <span>Host</span>
                <input v-model="modal.remote.host" type="text" placeholder="servidor.exemplo" />
              </label>
              <label class="field">
                <span>Porta</span>
                <input v-model="modal.remote.port" type="number" min="1" max="65535" />
              </label>
              <label class="field">
                <span>Usuário</span>
                <input v-model="modal.remote.user" type="text" placeholder="deploy" />
              </label>
              <label class="field">
                <span>Chave SSH</span>
                <input v-model="modal.remote.key_path" type="text" placeholder="~/.ssh/id_ed25519" />
              </label>
              <label class="field">
                <span>Pasta do projeto no servidor</span>
                <input v-model="modal.remote.root" type="text" placeholder="/srv/app" />
              </label>
              <label class="field">
                <span>Sistema</span>
                <select v-model="modal.remote.shell">
                  <option value="posix">Linux / macOS</option>
                  <option value="powershell">Windows (PowerShell)</option>
                </select>
              </label>
            </div>
            <p class="muted small" v-if="modal.remoteResult">
              <span class="dot" :class="modal.remoteResult.ok ? 'dot-ok' : 'dot-err'"></span>
              {{ modal.remoteResult.ok ? 'conexão ok' : 'falhou' }} — {{ modal.remoteResult.detail || '' }}
            </p>
            <div class="form-actions">
              <button type="button" class="btn-primary" :disabled="modal.remoteBusy" @click="saveRemoteConfig()">Salvar</button>
              <button type="button" class="btn-ghost" :disabled="modal.remoteBusy" @click="checkRemote()">Testar conexão</button>
              <button type="button" class="btn-danger" @click="removeRemote()">Usar máquina local</button>
            </div>
          </div>
        </div>
      </Transition>

      <Transition name="fade">
        <div class="modal" v-if="modal.kind === 'folder' || modal.kind === 'move-folder'" @click.self="modal.kind = null">
          <div class="modal-card">
            <header class="modal-head">
              <h3>
                {{ modal.purpose === 'move-folder' ? 'Mover projeto' : (modal.purpose === 'new-project' ? 'Escolher a pasta do projeto' : 'Escolher pasta') }}
              </h3>
              <button type="button" class="icon-btn ghost" @click="modal.kind = null" aria-label="Fechar">×</button>
            </header>
            <p class="muted small path">{{ modal.path || '—' }}</p>
            <div class="mkdir-row">
              <input
                v-model="modal.newFolder"
                type="text"
                placeholder="nome da nova pasta"
                @keyup.enter="createFolder()"
                aria-label="Nome da nova pasta"
              />
              <button type="button" class="btn-ghost small" @click="createFolder()">Criar pasta</button>
            </div>
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

const app = createApp(App);
app.mount("#app");

// Alça de depuração: permite inspecionar o estado da interface pelo console do navegador
// (e automatizar verificações visuais sem depender do modelo).
window.__callidus = { state };
