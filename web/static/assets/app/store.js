// web/static/assets/app/store.js — estado reativo e ações da interface
import { api } from "./api.js";
import { describeActivity } from "./ui.js";
import { applyEvent, applyLive, createState, markConnection, markResync } from "./live-state.js";
import { createStream } from "./live-stream.js";

const { reactive } = Vue;

export const state = reactive({
  view: "chat",
  theme: localStorage.getItem("callidus-theme") || "dark",
  density: localStorage.getItem("callidus-density") || "confortavel",
  ready: false,
  railOpen: false,
  paletteOpen: false,
  compact: typeof window !== "undefined" ? window.matchMedia("(max-width: 1179px)").matches : false,
  settingsTab: "geral",

  projects: [],
  conversations: [],
  loose: [],
  selectedProject: null,
  conversation: null,
  tasks: [],
  selectedTaskId: null,
  currentRun: null,
  uiDefaults: null,
  search: "",

  providers: [],
  providerConfig: null,
  providerModels: {},
  providerHealth: {},
  providerBusy: {},

  sending: false,
  toasts: [],
  live: null,
  outputs: [],
  streamEvents: [],
  feed: [],

  provider: "ollama",
  modelId: "",
  browserMode: "off",
  approveTools: true,
  objective: "",
  attachments: [],

  detailsOpen: true,
  detailsTab: "detail",
  taskFilter: "",
  inspector: null,
  diffText: "",
  metricsText: "",
  graphText: "",
  toolsText: "",
  mcpText: "",
});

let stream = null;
let pollTimer = null;

/** Estado do redutor de acompanhamento (tarefas, saídas, arquivos, verificações). */
state.liveState = { data: null, version: 0 };

export function toast(message, type = "info") {
  const id = Date.now() + Math.random();
  state.toasts.push({ id, message, type });
  setTimeout(() => {
    const index = state.toasts.findIndex((item) => item.id === id);
    if (index >= 0) state.toasts.splice(index, 1);
  }, 4200);
}

export function workspaceId() {
  return state.selectedProject?.id || state.conversation?.workspace_id || null;
}

export function roots() {
  return state.tasks.filter(
    (task) => !task.parent_id && (!state.conversation || task.conversation_id === state.conversation.id),
  );
}

export function childrenOf(rootId) {
  return state.tasks.filter((task) => task.parent_id === rootId);
}

export function descendantIds(rootId) {
  const ids = new Set([rootId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const task of state.tasks) {
      if (task.parent_id && ids.has(task.parent_id) && !ids.has(task.id)) {
        ids.add(task.id);
        grew = true;
      }
    }
  }
  return ids;
}

export function setTheme(theme) {
  state.theme = theme;
  localStorage.setItem("callidus-theme", theme);
  document.documentElement.dataset.theme = theme;
}

export function setDensity(density) {
  state.density = density;
  localStorage.setItem("callidus-density", density);
  document.documentElement.dataset.density = density;
}

/** Ajusta o estado quando a janela muda de tamanho (desktop ⇄ tablet/mobile). */
export function watchViewport() {
  if (typeof window === "undefined") return;
  const query = window.matchMedia("(max-width: 1179px)");
  const apply = () => {
    state.compact = query.matches;
    if (query.matches) {
      state.railOpen = false;
      state.detailsOpen = false;
    }
  };
  query.addEventListener("change", apply);
  apply();
}

export function openView(view) {
  state.view = view;
  state.railOpen = false;
  state.paletteOpen = false;
}

export async function bootstrap() {
  setTheme(state.theme);
  const [projects, loose, defaults, health] = await Promise.all([
    api("/projects").catch(() => []),
    api("/conversations").catch(() => []),
    api("/config/ui-defaults").catch(() => null),
    api("/health").catch(() => null),
  ]);
  state.projects = projects;
  state.loose = loose;
  state.uiDefaults = defaults;
  state.provider = defaults?.provider || "ollama";
  state.modelId = defaults?.model_id || "";
  state.ready = true;
  await loadProviders();
  if (state.providers.length) {
    const current = state.providers.find((item) => item.name === state.provider);
    if (!current) state.provider = state.providers[0].name;
  }
  void health;
}

export async function loadRemote(project) {
  const data = await api(`/projects/${project.id}/remote`).catch(() => ({ remote: null }));
  return data.remote || null;
}

export async function saveRemote(project, config) {
  const data = await api(`/projects/${project.id}/remote`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
  toast("Computador remoto configurado", "ok");
  return data.remote;
}

export async function clearRemote(project) {
  await api(`/projects/${project.id}/remote`, { method: "DELETE" });
  toast("Projeto voltou para a máquina local", "ok");
}

export async function testRemote(project) {
  const data = await api(`/projects/${project.id}/remote/test`, { method: "POST" }).catch((err) => ({
    ok: false,
    detail: err.message,
  }));
  return data;
}

export async function renameProject(project, name) {
  const clean = (name || "").trim();
  if (!clean) return;
  try {
    await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ name: clean }) });
    state.projects = await api("/projects").catch(() => state.projects);
    if (state.selectedProject?.id === project.id) {
      state.selectedProject = state.projects.find((item) => item.id === project.id) || state.selectedProject;
    }
    toast(`Projeto renomeado para “${clean}”`, "ok");
  } catch (err) {
    toast(err.message || "Falha ao renomear o projeto", "error");
  }
}

export async function moveProject(project, rootPath) {
  try {
    await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ root_path: rootPath }) });
    state.projects = await api("/projects").catch(() => state.projects);
    if (state.selectedProject?.id === project.id) {
      state.selectedProject = state.projects.find((item) => item.id === project.id) || state.selectedProject;
    }
    toast("Pasta do projeto atualizada", "ok");
  } catch (err) {
    toast(err.message || "Falha ao trocar a pasta", "error");
  }
}

export async function deleteProject(project) {
  const label = project.name || "projeto";
  if (!window.confirm(`Remover o projeto “${label}”? Conversas, tarefas e memórias dele vão junto. Os arquivos da pasta NÃO são apagados.`)) {
    return false;
  }
  try {
    const result = await api(`/projects/${project.id}`, { method: "DELETE" });
    state.projects = await api("/projects").catch(() => []);
    if (state.selectedProject?.id === project.id) {
      state.selectedProject = null;
      state.conversation = null;
      state.tasks = [];
      state.currentRun = null;
    }
    toast(`Projeto “${label}” removido`, "ok");
    return result;
  } catch (err) {
    toast(err.message || "Falha ao remover o projeto", "error");
    return false;
  }
}

/** Estado por conversa: trabalhando, concluída ou parada — usado na cor da lista. */
export function conversationStatus(conversation) {
  if (!conversation) return "idle";
  const tasks = state.tasks.filter((task) => task.conversation_id === conversation.id);
  if (!tasks.length) return "idle";
  if (tasks.some((task) => ["RUNNING", "PLANNING", "VERIFYING", "RETRY_PENDING"].includes(task.status))) {
    return "working";
  }
  if (tasks.some((task) => ["BLOCKED", "FAILED"].includes(task.status))) return "attention";
  if (tasks.every((task) => task.status === "COMPLETED")) return "done";
  return "idle";
}

export async function loadProviders() {
  const [catalog, config] = await Promise.all([
    api("/providers").catch(() => ({ providers: [], default_provider: null })),
    api("/providers/config").catch(() => null),
  ]);
  state.providers = catalog.providers || [];
  state.providerConfig = config;
  if (config?.default_provider) state.provider = config.default_provider;
  state.providers.forEach((item) => {
    if (item.name === state.provider) state.modelId = item.model || state.modelId;
  });
}

export async function selectProject(project) {
  state.selectedProject = project;
  state.conversation = null;
  state.conversations = project ? await api(`/projects/${project.id}/conversations`).catch(() => []) : [];
  state.tasks = [];
  state.currentRun = null;
  await refreshTasks();
}

export async function selectConversation(conversation) {
  state.conversation = conversation;
  state.selectedProject = conversation.project_id
    ? state.projects.find((item) => item.id === conversation.project_id) || state.selectedProject
    : null;
  state.tasks = [];
  state.currentRun = null;
  await refreshTasks();
}

export async function deleteConversation(conversation) {
  if (!window.confirm(`Apagar a conversa “${conversation.title || "sem título"}”? O histórico dela vai junto.`)) {
    return false;
  }
  try {
    await api(`/conversations/${conversation.id}`, { method: "DELETE" });
    if (state.conversation?.id === conversation.id) {
      disconnectStream();
      state.conversation = null;
      state.tasks = [];
      state.currentRun = null;
    }
    state.loose = await api("/conversations").catch(() => []);
    if (state.selectedProject) {
      state.conversations = await api(`/projects/${state.selectedProject.id}/conversations`).catch(() => []);
    }
    toast("Conversa apagada", "ok");
    return true;
  } catch (err) {
    toast(err.message || "Falha ao apagar a conversa", "error");
    return false;
  }
}

export async function refreshTasks() {
  if (state.conversation) {
    state.tasks = await api(`/conversations/${state.conversation.id}/tasks`).catch(() => []);
  } else if (state.selectedProject) {
    state.tasks = await api(`/projects/${state.selectedProject.id}/tasks`).catch(() => []);
  } else {
    state.tasks = [];
  }
  if (state.selectedTaskId && !state.tasks.some((task) => task.id === state.selectedTaskId)) {
    state.selectedTaskId = state.tasks[0]?.id || null;
  }
}

export async function refreshRun() {
  const workspace = workspaceId();
  if (!workspace) return;
  const runs = await api(`/projects/${workspace}/runs`).catch(() => []);
  const active = runs.find((run) => ["ACTIVE", "PAUSED"].includes(run.status)) || runs[0] || null;
  state.currentRun = active;
}

export function runConfig() {
  return {
    provider: state.provider,
    model_id: state.modelId || state.uiDefaults?.model_id || "",
    approve_risky_tools: state.approveTools,
    use_generic_template: true,
    browser_mode: state.browserMode,
  };
}

export async function sendMessage() {
  const typed = state.objective.trim();
  if (!typed || state.sending) return;
  state.sending = true;
  const title = typed.slice(0, 80);
  const attachments = state.attachments.splice(0, state.attachments.length);
  const metadata = attachments.length
    ? {
        attachments: attachments.map((item) => ({
          kind: item.kind,
          name: item.name,
          mime: item.mime,
          content: item.content,
          content_base64: item.content_base64,
        })),
      }
    : undefined;
  try {
    if (!state.conversation) {
      if (state.selectedProject) {
        state.conversation = await api(`/projects/${state.selectedProject.id}/conversations`, {
          method: "POST",
          body: JSON.stringify({ title }),
        });
        state.conversations = [state.conversation, ...state.conversations];
      } else {
        state.conversation = await api("/conversations", {
          method: "POST",
          body: JSON.stringify({ title }),
        });
        state.loose = [state.conversation, ...state.loose];
      }
    }
    const workspace = workspaceId();
    const task = await api(`/projects/${workspace}/tasks`, {
      method: "POST",
      body: JSON.stringify({
        title,
        objective: typed,
        kind: "objective",
        conversation_id: state.conversation.id,
        metadata,
      }),
    });
    state.objective = "";
    state.selectedTaskId = task.id;
    await refreshTasks();
    await startRun();
  } catch (err) {
    toast(err.message || "Falha ao enviar", "error");
  } finally {
    state.sending = false;
  }
}

export async function startRun() {
  const workspace = workspaceId();
  const root = state.tasks.find((task) => task.id === state.selectedTaskId) || roots()[0];
  if (!workspace || !root) {
    toast("Não há mensagem para executar", "error");
    return;
  }
  state.currentRun = await api(`/projects/${workspace}/runs`, {
    method: "POST",
    body: JSON.stringify({ root_task_id: root.id, config: runConfig() }),
  });
  await api(`/runs/${state.currentRun.id}/autonomous/enable`, { method: "POST" }).catch(() => {});
  await connectStream(state.currentRun.id);
  await api(`/runs/${state.currentRun.id}/step`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
}

export async function stepRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/step`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
  await loadInspector(state.selectedTaskId);
}

export async function autoRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/execute?max_steps=80`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
}

export async function pauseRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/pause`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
}

export async function resumeRun() {
  if (!state.currentRun) return;
  try {
    await api(`/runs/${state.currentRun.id}/resume`, { method: "POST" });
    state.currentRun = { ...state.currentRun, status: "ACTIVE" };
    await connectStream(state.currentRun.id);
    await refreshTasks();
    toast("Execução retomada", "ok");
  } catch (err) {
    toast(err.message || "Falha ao retomar a execução", "error");
  }
}

export async function cancelRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/cancel`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  disconnectStream();
  state.currentRun = null;
  await refreshTasks();
}

export async function connectStream(runId) {
  disconnectStream();
  state.outputs = [];
  state.streamEvents = [];
  const snapshot = await api(`/runs/${runId}/observe`).catch(() => ({}));
  const reducer = createState(snapshot || {});
  state.liveState.data = reducer;
  state.liveState.version += 1;
  stream = createStream({
    runId,
    cursor: () => reducer.lastSeq,
    EventSourceImpl: EventSource,
    onEnvelope: (envelope) => {
      applyEvent(reducer, envelope);
      state.streamEvents.push(envelope);
      if (state.streamEvents.length > 400) state.streamEvents.splice(0, 100);
      pushActivity(envelope);
      state.liveState.version += 1;
    },
    onLive: (snapshot) => {
      applyLive(reducer, snapshot);
      state.live = snapshot;
      state.liveState.version += 1;
    },
    onResync: () => {
      markResync(reducer);
      state.liveState.version += 1;
    },
    onEnd: () => {
      markConnection(reducer, "ended");
      state.liveState.version += 1;
      refreshTasks();
    },
    onStatus: (status) => {
      reducer.connection = status;
      state.liveState.version += 1;
    },
  });
}

export function disconnectStream() {
  stream?.close();
  stream = null;
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  state.detailsOpen = true;
  await loadInspector(taskId);
}

export async function loadInspector(taskId) {
  if (!taskId) {
    state.inspector = null;
    return;
  }
  const [task, attempts, evidences, snapshots, contract] = await Promise.all([
    api(`/tasks/${taskId}`).catch(() => null),
    api(`/tasks/${taskId}/attempts`).catch(() => []),
    api(`/tasks/${taskId}/evidences`).catch(() => []),
    api(`/tasks/${taskId}/context-snapshots`).catch(() => []),
    api(`/tasks/${taskId}/contract`).catch(() => null),
  ]);
  state.inspector = { task, attempts, evidences, snapshots, contract };
}

export async function loadDiff() {
  const project = state.selectedProject;
  if (!project) return;
  const diff = await api(`/projects/${project.id}/git-diff`).catch(() => null);
  state.diffText = diff?.diff || diff?.text || "";
}

export async function loadMetrics() {
  const workspace = workspaceId();
  if (!workspace) return;
  const metrics = await api(`/projects/${workspace}/metrics`).catch(() => null);
  state.metricsText = JSON.stringify(metrics, null, 2);
}

export async function loadGraph(query = "") {
  const project = state.selectedProject;
  if (!project) return;
  const result = await api(`/projects/${project.id}/knowledge/search?q=${encodeURIComponent(query)}`).catch(() => null);
  state.graphText = JSON.stringify(result, null, 2);
}

export async function loadTools() {
  const tools = await api("/tools").catch(() => null);
  state.toolsText = JSON.stringify(tools, null, 2);
}

export async function discoverMcp() {
  const result = await api("/mcp/discover", { method: "POST" }).catch((err) => ({ error: err.message }));
  state.mcpText = JSON.stringify(result, null, 2);
}

/** Entradas de atividade do chat: pensamento, ferramentas, comandos, leituras e escritas. */
function pushActivity(envelope) {
  const entry = describeActivity(envelope);
  if (!entry) return;
  const feed = state.feed;
  if (entry.callId) {
    // Atualiza a entrada em andamento (mesma chamada de ferramenta/comando).
    const index = feed.findIndex((item) => item.callId === entry.callId && item.kind === entry.kind);
    if (index >= 0 && entry.kind !== "command-output") {
      feed.splice(index, 1, { ...feed[index], ...entry });
      return;
    }
    if (entry.kind === "command-output") {
      const target = feed.find((item) => item.callId === entry.callId && item.kind === "command");
      if (target) {
        target.output = `${target.output || ""}${entry.detail || ""}`;
        return;
      }
    }
  }
  feed.push(entry);
  if (feed.length > 120) feed.splice(0, feed.length - 120);
}

export async function loadModels(providerName) {
  const name = providerName || state.provider;
  if (!name) return [];
  const data = await api(`/providers/${encodeURIComponent(name)}/models`).catch(() => null);
  const models = data?.models || [];
  state.providerModels = { ...state.providerModels, [name]: models };
  return models;
}

export async function testProvider(name) {
  state.providerHealth = { ...state.providerHealth, [name]: { checking: true } };
  const data = await api(`/providers/${encodeURIComponent(name)}/test`, { method: "POST" }).catch((err) => ({
    ok: false,
    detail: err.message,
  }));
  state.providerHealth = { ...state.providerHealth, [name]: data };
  return data;
}

export async function saveProviderConfig(payload) {
  const saved = await api("/providers/config", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

export async function removeProvider(name) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}`, { method: "DELETE" });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

export async function setProviderSecret(name, secret) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}/secret`, {
    method: "PUT",
    body: JSON.stringify({ secret }),
  });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

export async function clearProviderSecret(name) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}/secret`, { method: "DELETE" });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}
