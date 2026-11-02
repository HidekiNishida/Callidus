/**
 * Arquivo: web/static/assets/app/main.js
 * Nome: main.js
 * Propósito: bootstrap da interface (Vue 3) — monta o componente raiz e dispara o carregamento dos serviços de forma assíncrona, sem bloquear a apresentação.
 * Responsabilidade: frontend/bootstrap — liga os componentes, os modais e os atalhos globais; separa a montagem da interface da inicialização dos serviços.
 * Componentes: App (componente raiz), NAV_ITEMS, handlers de modais (projeto, pasta, remoto), atalhos.
 * Dependências: `./store.js`, `./api.js`, `./ui.js` e os componentes em `./components/`.
 * Observações: expõe `window.__callidus` para inspeção e automação de verificações visuais.
 */
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
  getBootEvents,
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
import { CognitiveGraphView } from "./components/intelligence-graph.js";
import { IntelligenceOverview } from "./components/intelligence-overview.js";
import { IntelligencePerformance } from "./components/intelligence-performance.js";
import { IntelligenceReasoning } from "./components/intelligence-reasoning.js";
import { IntelligenceKnowledge } from "./components/intelligence-knowledge.js";
import { IntelligenceDiagnostics } from "./components/intelligence-diagnostics.js";
import { IntelligenceEngineering } from "./components/intelligence-engineering.js";
import { IntelligenceOptimization } from "./components/intelligence-optimization.js";
import { IntelligenceResources } from "./components/intelligence-resources.js";
import { IntelligenceAgents } from "./components/intelligence-agents.js";

const {
  createApp,
  reactive,
  ref,
  computed,
  onMounted,
  onBeforeUnmount,
  defineAsyncComponent,
} = Vue;

/**
 * Módulos secundários da área de Inteligência, carregados sob demanda.
 * Esses módulos só são necessários quando o usuário abre a aba Inteligência.
 * Se a carga falhar (rede, erro de sintaxe, etc.), o restante da aplicação
 * continua montado e a página afetada exibe uma mensagem localizada, em vez
 * de derrubar toda a interface.
 */
const IntelligenceBenchmarks = defineAsyncComponent({
  loader: () =>
    import("./components/intelligence-pages.js").then((m) => m.IntelligenceBenchmarks),
  errorComponent: {
    template:
      '<div class="boot warn"><span>Módulo de benchmarks indisponível no momento.</span></div>',
  },
});

const IntelligenceContextConsumption = defineAsyncComponent({
  loader: () =>
    import("./components/intelligence-pages.js").then((m) => m.IntelligenceContextConsumption),
  errorComponent: {
    template:
      '<div class="boot warn"><span>Módulo de consumo de contexto indisponível no momento.</span></div>',
  },
});

/** Telas da navegação inferior. */
const NAV_ITEMS = [
  { id: "chat", label: "Conversa", icon: "chat" },
  { id: "live", label: "Execução", icon: "chart" },
  { id: "intelligence", label: "Inteligência", icon: "layout" },
  { id: "providers", label: "Provedores", icon: "server" },
  { id: "automations", label: "Automações", icon: "clock" },
  { id: "settings", label: "Ajustes", icon: "cog" },
];

/**
 * Componente raiz da interface: layout, navegação, modais e atalhos globais.
 *
 * @returns {object} Objeto de opções do Vue com `setup()` e `template`.
 * Observações: os modais (novo projeto, seletor de pasta, computador remoto) compartilham o
 * mesmo estado `modal`, aberto por `modal.kind`.
 */
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
    CognitiveGraphView,
    IntelligenceOverview,
    IntelligencePerformance,
    IntelligenceReasoning,
    IntelligenceKnowledge,
    IntelligenceDiagnostics,
    IntelligenceBenchmarks,
    IntelligenceContextConsumption,
    IntelligenceEngineering,
    IntelligenceResources,
    IntelligenceAgents,
    IntelligenceOptimization,
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

    const intelligenceSubView = ref("overview"); // overview, performance, reasoning, knowledge, diagnostics, benchmarks, engineering, resources, agents, optimization

    /**
     * Emite um evento de diagnóstico de boot para o guarda externo
     * (index.html) sem falhar se o guarda não estiver disponível.
     *
     * @param {string} stage Etapa do ciclo de inicialização.
     * @param {object} detail Detalhes adicionais do evento.
     * @returns {void}
     */
    function bootEvent(stage, detail = {}) {
      try {
        if (window.__callidusBoot) {
          window.__callidusBoot({ stage, at: Date.now(), ...detail });
        }
      } catch {
        /* guarda de boot indisponível; não falha por causa do diagnóstico */
      }
      console.error(`[callidus:boot:${stage}]`, detail);
    }

    onMounted(() => {
      watchViewport();

      // Emite evento de montagem para diagnóstico externo (bootstrap guard).
      try {
        if (window.__callidusBoot) {
          window.__callidusBoot({ stage: "VUE_MOUNTED", at: Date.now() });
        }
      } catch {}

      // A interface está montada: dispara o carregamento dos serviços sem bloquear a apresentação.
      void bootstrap();

      window.addEventListener("keydown", onGlobalKey);
      window.addEventListener("callidus:new-project", newProject);
      window.addEventListener("callidus:rename-conversation", renameConversation);
      window.addEventListener("callidus:step", stepRun);
      window.addEventListener("callidus:auto", autoRun);
      window.addEventListener("callidus:pause", pauseRun);
      window.addEventListener("callidus:cancel", cancelRun);

      // Handlers globais de erro: capturam exceções não tratadas e promessas rejeitadas
      // sem engolir silenciosamente, preservando o console do navegador.
      window.addEventListener("error", onGlobalError);
      window.addEventListener("unhandledrejection", onGlobalUnhandledRejection);
    });

    onBeforeUnmount(() => {
      window.removeEventListener("keydown", onGlobalKey);
      window.removeEventListener("error", onGlobalError);
      window.removeEventListener("unhandledrejection", onGlobalUnhandledRejection);
      disconnectStream();
    });

    /**
     * Captura exceções não tratadas (window.onerror) e as registra como evento de boot.
     *
     * @param {Event} event Evento de erro.
     * @returns {void}
     */
    function onGlobalError(event) {
      try {
        const msg = event.message || event.error?.message || String(event);
        const filename = event.filename || "";
        const lineno = event.lineno ?? "";
        bootEvent("BOOT_MODULE_ERROR", { message: msg, filename, lineno });
        // Não impede o comportamento padrão do console do navegador.
      } catch {
        /* evita erro no próprio handler */
      }
    }

    /**
     * Captura promessas rejeitadas sem handler (unhandledrejection).
     *
     * @param {event} event Evento de rejeição.
     * @returns {void}
     */
    function onGlobalUnhandledRejection(event) {
      try {
        const reason = event.reason;
        const msg = reason?.message || reason?.toString?.() || String(reason);
        bootEvent("BOOT_API_ERROR", { message: msg });
        // Não impede o comportamento padrão do console do navegador.
      } catch {
        /* evita erro no próprio handler */
      }
    }

    /**
     * Descobre se o foco está em um campo de digitação.
     *
     * @param {KeyboardEvent} event Evento de teclado.
     * @returns {boolean} `true` quando o usuário está digitando em um campo.
     */
    function isTyping(event) {
      const tag = event.target?.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable;
    }

    /**
     * Trata os atalhos globais de teclado.
     *
     * @param {KeyboardEvent} event Evento de teclado.
     * @returns {void}
     * Observações: ⌘K abre a paleta, ⌘B a barra lateral, ⌘J o campo de objetivo, "/" foca o
     * campo de objetivo e Esc fecha painéis e diálogos.
     */
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

    /**
     * Abre o modal de novo projeto, limpando os campos anteriores.
     *
     * @returns {Promise<void>}
     */
    async function newProject() {
      modal.kind = "project";
      modal.name = "";
      modal.rootPath = "";
    }

    /**
     * Cria o projeto pedido no modal e o deixa selecionado.
     *
     * @returns {Promise<void>}
     * Observações: avisa o usuário por `toast` quando o nome falta ou a criação falha.
     */
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

    /**
     * Abre o seletor de pasta para o projeto atual.
     *
     * @returns {Promise<void>}
     */
    async function openFolder() {
      modal.kind = "folder";
      modal.purpose = "project-folder";
      modal.path = state.selectedProject?.root_path || "";
      await browse(modal.path);
    }

    /**
     * Abre o seletor de pasta para escolher a pasta de um projeto novo.
     *
     * @returns {Promise<void>}
     */
    async function pickFolderForProject() {
      modal.kind = "folder";
      modal.purpose = "new-project";
      modal.path = modal.rootPath || state.selectedProject?.root_path || "";
      await browse(modal.path);
    }

    /**
     * Abre o modal de computador remoto com a configuração do projeto.
     *
     * @param {object} payload Objeto com `project` e `config`.
     * @returns {Promise<void>}
     */
    async function openRemote(payload) {
      modal.kind = "remote";
      modal.remoteProject = payload.project;
      modal.remote = { ...payload.config };
      modal.remoteResult = null;
    }

    /**
     * Grava a configuração do computador remoto mostrada no modal.
     *
     * @returns {Promise<void>}
     * Observações: exige o host; o estado `remoteBusy` desabilita os botões durante a gravação.
     */
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

    /**
     * Testa a conexão com o computador remoto e guarda o resultado no modal.
     *
     * @returns {Promise<void>}
     */
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

    /**
     * Remove a configuração do computador remoto, voltando para a máquina local.
     *
     * @returns {Promise<void>}
     */
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

    /**
     * Cria uma pasta dentro do diretório aberto no seletor.
     *
     * @returns {Promise<void>}
     * Observações: o nome vem do campo "nova pasta"; um nome vazio não faz nada.
     */
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

    /**
     * Lista o conteúdo de uma pasta no seletor.
     *
     * @param {string} path Caminho da pasta a listar ("" = pasta do usuário).
     * @returns {Promise<void>}
     * Observações: uma pasta fora do alcance da navegação volta para a pasta do usuário,
     * com aviso ao usuário.
     */
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

    /**
     * Aplica a pasta escolhida no seletor, conforme o propósito do modal.
     *
     * @returns {Promise<void>}
     * Observações: move o projeto, escolhe a pasta de um projeto novo ou troca a pasta do
     * projeto atual.
     */
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

    /**
     * Abre o seletor de pasta para mover um projeto existente.
     *
     * @param {object} project Projeto a mover.
     * @returns {Promise<void>}
     */
    async function moveFolderTo(project) {
      modal.kind = "move-folder";
      modal.purpose = "move-folder";
      modal.project = project;
      modal.path = project.root_path || "";
      await browse(modal.path);
    }

    /**
     * Renomeia a conversa atual, perguntando o novo nome ao usuário.
     *
     * @returns {Promise<void>}
     */
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

    /**
     * Traduz o estado agregado da API para um rótulo legível.
     *
     * @param {string} api Estado da API ("unknown", "online", "offline" ou "partial").
     * @returns {string} Rótulo exibido na barra de status.
     */
    function apiLabel(api) {
      const labels = {
        unknown: "API desconhecida",
        online: "API online",
        offline: "API off-line",
        partial: "API parcial",
      };
      return labels[api] || api;
    }

    function apiClass(api) {
      return `api-${api}`;
    }

    const navItems = computed(() => NAV_ITEMS);

    /**
     * Troca a sub-visão de inteligência.
     *
     * @param {string} subView Uma das: "overview", "performance", "benchmarks", "diagnostics"
     */
    function setIntelligenceSubView(subView) {
      intelligenceSubView.value = subView;
      openView("intelligence");
    }

    return {
      state,
      modal,
      navItems,
      apiLabel,
      apiClass,
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
      getBootEvents,
      intelligenceSubView,
      setIntelligenceSubView,
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
          <div v-if="state.initialization.bootstrap === 'loading'" class="boot">
            <span class="spinner"></span> Carregando o Callidus…
          </div>
          <!-- Falha ou modo parcial é um aviso acima das telas, não no lugar delas:
               com a API fora ou parcial, o chat e os ajustes continuam acessíveis. -->
          <div
            v-if="state.initialization.bootstrap !== 'loading' && (state.initialization.bootstrap === 'error' || state.initialization.degraded)"
            class="boot-banner"
            :class="state.initialization.bootstrap === 'error' ? 'error' : 'warn'"
            role="status"
          >
            <span v-if="state.initialization.bootstrap === 'error'">
              {{ state.initialization.errors.length }} falha(s) ao inicializar — a API não respondeu
            </span>
            <span v-else>
              Modo parcial — {{ state.initialization.errors.length }} recurso(s) indisponível(eis)
            </span>
            <button type="button" class="btn-ghost small" @click="bootstrap()">Tentar novamente</button>
          </div>
          <div v-if="state.initialization.bootstrap !== 'loading'" class="view-switch">
            <div v-if="state.view === 'chat'" key="chat">
              <ChatView key="chat" />
            </div>
            <div v-else-if="state.view === 'live'" key="live">
              <LivePanel key="live" />
            </div>
            <div v-else-if="state.view === 'intelligence'" key="intelligence">
              <div class="intelligence-container">
                <nav class="intelligence-tabs" role="tablist" aria-label="Seções de inteligência">
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'overview' }"
                    @click="setIntelligenceSubView('overview')"
                    aria-selected="intelligenceSubView === 'overview'"
                  >
                    <span v-html="icon('layout', 15)"></span><span>Overview</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'performance' }"
                    @click="setIntelligenceSubView('performance')"
                    aria-selected="intelligenceSubView === 'performance'"
                  >
                    <span v-html="icon('activity', 15)"></span><span>Desempenho</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'benchmarks' }"
                    @click="setIntelligenceSubView('benchmarks')"
                    aria-selected="intelligenceSubView === 'benchmarks'"
                  >
                    <span v-html="icon('bar-chart', 15)"></span><span>Benchmarks</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'diagnostics' }"
                    @click="setIntelligenceSubView('diagnostics')"
                    aria-selected="intelligenceSubView === 'diagnostics'"
                  >
                    <span v-html="icon('alert-circle', 15)"></span><span>Diagnósticos</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'reasoning' }"
                    @click="setIntelligenceSubView('reasoning')"
                    aria-selected="intelligenceSubView === 'reasoning'"
                  >
                    <span v-html="icon('spark', 15)"></span><span>Raciocínio</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'knowledge' }"
                    @click="setIntelligenceSubView('knowledge')"
                    aria-selected="intelligenceSubView === 'knowledge'"
                  >
                    <span v-html="icon('layers', 15)"></span><span>Conhecimento</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'engineering' }"
                    @click="setIntelligenceSubView('engineering')"
                    aria-selected="intelligenceSubView === 'engineering'"
                  >
                    <span v-html="icon('wrench', 15)"></span><span>Engenharia</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'resources' }"
                    @click="setIntelligenceSubView('resources')"
                    aria-selected="intelligenceSubView === 'resources'"
                  >
                    <span v-html="icon('server', 15)"></span><span>Recursos</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'agents' }"
                    @click="setIntelligenceSubView('agents')"
                    aria-selected="intelligenceSubView === 'agents'"
                  >
                    <span v-html="icon('clock', 15)"></span><span>Agentes</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'optimization' }"
                    @click="setIntelligenceSubView('optimization')"
                    aria-selected="intelligenceSubView === 'optimization'"
                  >
                    <span v-html="icon('refresh', 15)"></span><span>Otimização</span>
                  </button>
                  <button
                    role="tab"
                    :class="{ active: intelligenceSubView === 'consumo' }"
                    @click="setIntelligenceSubView('consumo')"
                    aria-selected="intelligenceSubView === 'consumo'"
                  >
                    <span v-html="icon('layers', 15)"></span><span>Consumo de Contexto</span>
                  </button>
                </nav>
                <div class="intelligence-sub-views">
                  <div v-if="intelligenceSubView === 'overview'" key="intelligence-overview">
                    <IntelligenceOverview />
                  </div>
                  <div v-else-if="intelligenceSubView === 'performance'" key="intelligence-performance">
                    <IntelligencePerformance :run-id="state.currentRun?.id" />
                  </div>
                  <div v-else-if="intelligenceSubView === 'reasoning'" key="intelligence-reasoning">
                    <IntelligenceReasoning :run-id="state.currentRun?.id" />
                  </div>
                  <div v-else-if="intelligenceSubView === 'knowledge'" key="intelligence-knowledge">
                    <IntelligenceKnowledge />
                  </div>
                  <div v-else-if="intelligenceSubView === 'diagnostics'" key="intelligence-diagnostics">
                    <IntelligenceDiagnostics :run-id="state.currentRun?.id" />
                  </div>
                  <div v-else-if="intelligenceSubView === 'benchmarks'" key="intelligence-benchmarks">
                    <IntelligenceBenchmarks />
                  </div>
                  <div v-else-if="intelligenceSubView === 'engineering'" key="intelligence-engineering">
                    <IntelligenceEngineering />
                  </div>
                  <div v-else-if="intelligenceSubView === 'resources'" key="intelligence-resources">
                    <IntelligenceResources />
                  </div>
                  <div v-else-if="intelligenceSubView === 'agents'" key="intelligence-agents">
                    <IntelligenceAgents />
                  </div>
                  <div v-else-if="intelligenceSubView === 'optimization'" key="intelligence-optimization">
                    <IntelligenceOptimization />
                  </div>
                  <div v-else-if="intelligenceSubView === 'consumo'" key="intelligence-consumo">
                    <IntelligenceContextConsumption />
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="state.view === 'providers'" key="providers">
              <ProvidersView key="providers" />
            </div>
            <div v-else-if="state.view === 'automations'" key="automations">
              <AutomationsView key="automations" />
            </div>
            <div v-else-if="state.view === 'settings'" key="settings">
              <SettingsView
                key="settings"
                @new-project="newProject()"
                @move-folder="moveFolderTo($event)"
                @remote="openRemote($event)"
              />
            </div>
          </div>
        </main>

        <DetailsPanel v-if="state.view === 'chat'" :class="{ open: state.detailsOpen }" />
      </div>

      <footer class="statusbar">
        <span class="dot" :class="state.currentRun ? 'dot-live' : 'dot-idle'"></span>
        <span>{{ state.currentRun ? 'Run ' + state.currentRun.status : 'idle' }}</span>
        <span class="muted">{{ state.provider }}<template v-if="state.modelId"> · {{ state.modelId }}</template></span>
        <span class="muted" :class="apiClass(state.initialization.api)">{{ apiLabel(state.initialization.api) }}</span>
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
window.__callidus = { state, getBootEvents };
