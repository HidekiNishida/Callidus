/**
 * Arquivo: web/static/assets/app/store.js
 * Nome: store.js
 * Propósito: estado reativo da interface e as ações que o alteram.
 * Responsabilidade: frontend/estado — concentra o estado compartilhado e fala com a API em nome dos componentes.
 * Componentes: state (reativo), ações de projeto/conversa/tarefa/run, provedores, automações e conexões de stream.
 * Dependências: `./api.js` (HTTP), `./live-state.js` (redutor), `./live-stream.js` (SSE), `./ui.js` (atividade).
 * Observações: o estado é a fonte da verdade do navegador; o servidor continua sendo a fonte da verdade
 * da execução. As ações do store avisam o usuário por `toast` em vez de lançar erros.
 */
import { api } from "./api.js";
import { formatToolsReport } from "./tools-report.js";
import { describeActivity, mergeActivity } from "./ui.js";
import { applyEvent, applyLive, createState, markConnection, markResync } from "./live-state.js";
import { createStream } from "./live-stream.js";

const { reactive } = Vue;

/** Estado reativo compartilhado por todos os componentes. */
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
  running: false,
  // Mensagem enviada enquanto havia execução em andamento: entra assim que a run terminar.
  queued: null,
  toasts: [],
  live: null,
  outputs: [],
  streamEvents: [],
  feed: [],
  // Feed por mensagem: cada turno (tarefa raiz) tem a sua própria atividade.
  feeds: {},
  // Raiz (mensagem) da execução em curso: os eventos pertencem a ela.
  currentRootId: null,

  provider: "ollama",
  modelId: "",
  browserMode: "off",
  approveTools: true,
  autoMode: localStorage.getItem("callidus-auto") !== "off",
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
  toolsReport: null,
  mcpText: "",

  automations: [],
  automationDetail: null,
  supervisor: null,
});

let stream = null;
let pollTimer = null;
let taskTimer = null;

/** Estado do redutor de acompanhamento (tarefas, saídas, arquivos, verificações). */
state.liveState = { data: null, version: 0 };

/**
 * Mostra uma mensagem temporária para o usuário.
 *
 * @param {string} message Texto da mensagem.
 * @param {string} [type] Tipo do aviso ("info", "ok" ou "error").
 * @returns {void}
 * Observações: a mensagem se remove sozinha depois de alguns segundos.
 */
export function toast(message, type = "info") {
  const id = Date.now() + Math.random();
  state.toasts.push({ id, message, type });
  setTimeout(() => {
    const index = state.toasts.findIndex((item) => item.id === id);
    if (index >= 0) state.toasts.splice(index, 1);
  }, 4200);
}

/**
 * Descobre o espaço de trabalho (projeto) em que a interface está trabalhando.
 *
 * @returns {string|null} O id do projeto, o da conversa, ou `null` quando não há contexto.
 */
export function workspaceId() {
  return state.selectedProject?.id || state.conversation?.workspace_id || null;
}

/**
 * Lista as tarefas raiz (mensagens) do contexto atual.
 *
 * @returns {Array} As tarefas sem pai, da conversa selecionada.
 */
export function roots() {
  return state.tasks.filter(
    (task) => !task.parent_id && (!state.conversation || task.conversation_id === state.conversation.id),
  );
}

/**
 * Lista as subtarefas de uma tarefa raiz.
 *
 * @param {string} rootId Id da tarefa raiz.
 * @returns {Array} As tarefas cujo pai é a raiz informada.
 */
export function childrenOf(rootId) {
  return state.tasks.filter((task) => task.parent_id === rootId);
}

/**
 * Coleta os ids de uma tarefa e de todos os seus descendentes.
 *
 * @param {string} rootId Id da tarefa raiz.
 * @returns {Set<string>} Os ids da subárvore, incluindo a própria raiz.
 */
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

/**
 * Troca o tema da interface e o guarda no navegador.
 *
 * @param {string} theme Nome do tema ("dark" ou "light").
 * @returns {void}
 */
export function setTheme(theme) {
  state.theme = theme;
  localStorage.setItem("callidus-theme", theme);
  document.documentElement.dataset.theme = theme;
}

/**
 * Troca a densidade da interface e a guarda no navegador.
 *
 * @param {string} density Nome da densidade ("confortavel" ou "compacta").
 * @returns {void}
 */
export function setDensity(density) {
  state.density = density;
  localStorage.setItem("callidus-density", density);
  document.documentElement.dataset.density = density;
}

/**
 * Ajusta o estado quando a janela muda de tamanho (desktop ⇄ tablet/mobile).
 *
 * @returns {void}
 * Observações: em telas estreitas a barra lateral e o painel de detalhes começam fechados.
 */
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

/**
 * Troca a tela visível e fecha os painéis abertos.
 *
 * @param {string} view Id da tela ("chat", "live", "providers", "automations" ou "settings").
 * @returns {void}
 */
export function openView(view) {
  state.view = view;
  state.railOpen = false;
  state.paletteOpen = false;
}

/**
 * Carrega o estado inicial da interface (projetos, conversas, padrões e provedores).
 *
 * @returns {Promise<void>}
 * Observações: falhas de leitura são absorvidas — a interface abre mesmo sem algum recurso.
 */
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

/**
 * Lê a configuração do computador remoto de um projeto.
 *
 * @param {object} project Projeto consultado.
 * @returns {Promise<object|null>} A configuração salva, ou `null` quando o projeto usa a máquina local.
 */
export async function loadRemote(project) {
  const data = await api(`/projects/${project.id}/remote`).catch(() => ({ remote: null }));
  return data.remote || null;
}

/**
 * Grava a configuração do computador remoto de um projeto.
 *
 * @param {object} project Projeto configurado.
 * @param {object} config Configuração (host, port, user, key_path, root, shell, timeout).
 * @returns {Promise<object>} A configuração salva.
 */
export async function saveRemote(project, config) {
  const data = await api(`/projects/${project.id}/remote`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
  toast("Computador remoto configurado", "ok");
  return data.remote;
}

/**
 * Remove a configuração do computador remoto, voltando para a máquina local.
 *
 * @param {object} project Projeto alterado.
 * @returns {Promise<void>}
 */
export async function clearRemote(project) {
  await api(`/projects/${project.id}/remote`, { method: "DELETE" });
  toast("Projeto voltou para a máquina local", "ok");
}

/**
 * Testa a conexão com o computador remoto de um projeto.
 *
 * @param {object} project Projeto testado.
 * @returns {Promise<{ok: boolean, detail?: string}>} O resultado do teste; nunca lança.
 */
export async function testRemote(project) {
  const data = await api(`/projects/${project.id}/remote/test`, { method: "POST" }).catch((err) => ({
    ok: false,
    detail: err.message,
  }));
  return data;
}

/**
 * Renomeia um projeto e recarrega a lista.
 *
 * @param {object} project Projeto renomeado.
 * @param {string} name Novo nome.
 * @returns {Promise<void>}
 * Observações: nomes vazios são ignorados; falhas aparecem como aviso.
 */
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

/**
 * Troca a pasta de um projeto e recarrega a lista.
 *
 * @param {object} project Projeto alterado.
 * @param {string} rootPath Novo caminho da pasta.
 * @returns {Promise<void>}
 */
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

/**
 * Remove um projeto, com as conversas e tarefas que ele guarda.
 *
 * @param {object} project Projeto removido.
 * @returns {Promise<any|false>} A resposta da API, ou `false` quando a remoção foi cancelada ou falhou.
 * Observações: os arquivos da pasta NÃO são apagados.
 */
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

/**
 * Estado por conversa: trabalhando, concluída ou parada — usado na cor da lista.
 *
 * @param {object} conversation Conversa avaliada.
 * @returns {string} "working", "attention", "done" ou "idle".
 */
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

/**
 * Carrega o catálogo de provedores e a configuração gravada.
 *
 * @returns {Promise<void>}
 * Observações: falhas de leitura são absorvidas e deixam a lista vazia.
 */
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

/**
 * Seleciona um projeto e recarrega suas conversas e tarefas.
 *
 * @param {object} project Projeto selecionado.
 * @returns {Promise<void>}
 */
export async function selectProject(project) {
  state.selectedProject = project;
  state.conversation = null;
  state.selectedTaskId = null;
  state.inspector = null;
  state.feeds = {};
  state.currentRootId = null;
  state.conversations = project ? await api(`/projects/${project.id}/conversations`).catch(() => []) : [];
  state.tasks = [];
  state.currentRun = null;
  await refreshTasks();
}

/**
 * Seleciona uma conversa e recarrega suas tarefas.
 *
 * @param {object} conversation Conversa selecionada.
 * @returns {Promise<void>}
 */
export async function selectConversation(conversation) {
  state.conversation = conversation;
  state.selectedTaskId = null;
  state.inspector = null;
  state.feeds = {};
  state.currentRootId = null;
  state.selectedProject = conversation.project_id
    ? state.projects.find((item) => item.id === conversation.project_id) || state.selectedProject
    : null;
  state.tasks = [];
  state.currentRun = null;
  await refreshTasks();
}

/**
 * Apaga uma conversa, com o histórico dela.
 *
 * @param {object} conversation Conversa apagada.
 * @returns {Promise<boolean>} `true` quando apagou, `false` quando foi cancelada ou falhou.
 */
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

/**
 * Recarrega a lista de tarefas do contexto atual.
 *
 * @returns {Promise<void>}
 * Observações: quando a tarefa selecionada some, a primeira da lista passa a ser a selecionada.
 */
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
  await hydrateFeedsFromHistory();
}

/**
 * Reaplica eventos persistidos de `/observe` no feed do chat para mensagens já executadas.
 *
 * @param {string} runId Id da execução.
 * @param {string} rootId Tarefa raiz (mensagem) que recebe o feed.
 * @returns {Promise<void>}
 * Observações: deduplicação fica a cargo de `pushActivity` (`eventId`); não altera o stream ao vivo.
 */
async function replayFeedFromRun(runId, rootId) {
  const snapshot = await api(`/runs/${runId}/observe`).catch(() => ({}));
  const events = snapshot?.events || [];
  if (!events.length) return;
  const previousRoot = state.currentRootId;
  state.currentRootId = rootId;
  for (const envelope of events) pushActivity(envelope);
  state.currentRootId = previousRoot;
}

/**
 * Preenche feeds vazios a partir da última run conhecida de cada mensagem raiz.
 *
 * @returns {Promise<void>}
 */
export async function hydrateFeedsFromHistory() {
  const workspace = workspaceId();
  if (!workspace) return;
  const runs = await api(`/projects/${workspace}/runs`).catch(() => []);
  const latestByRoot = new Map();
  for (const run of runs) {
    const rootId = run.root_task_id;
    if (!rootId) continue;
    const prev = latestByRoot.get(rootId);
    if (!prev || String(run.created_at || "") > String(prev.created_at || "")) {
      latestByRoot.set(rootId, run);
    }
  }
  for (const root of roots()) {
    if ((state.feeds[root.id] || []).length) continue;
    const run = latestByRoot.get(root.id);
    if (!run) continue;
    await replayFeedFromRun(run.id, root.id);
  }
}

/**
 * Atualiza a execução em andamento a partir da lista de runs do workspace.
 *
 * @param {string} [runId] Id da run desejada; sem ele, escolhe a run ativa (ou a última).
 * @returns {Promise<void>}
 */
export async function refreshRun(runId) {
  const workspace = workspaceId();
  if (!workspace) return;
  const runs = await api(`/projects/${workspace}/runs`).catch(() => []);
  const target = runId ? runs.find((run) => run.id === runId) : null;
  const active = target || runs.find((run) => ["ACTIVE", "PAUSED"].includes(run.status)) || runs[0] || null;
  state.currentRun = active;
}

/**
 * Monta a configuração enviada ao servidor ao criar uma run.
 *
 * @returns {object} Provedor, modelo e opções de execução escolhidas na interface.
 */
export function runConfig() {
  return {
    provider: state.provider,
    model_id: state.modelId || state.uiDefaults?.model_id || "",
    approve_risky_tools: state.approveTools,
    use_generic_template: true,
    browser_mode: state.browserMode,
  };
}

/**
 * Envia o objetivo digitado: cria a conversa e a tarefa e inicia a execução.
 *
 * @returns {Promise<void>}
 * Observações: com uma execução em andamento, a mensagem é agendada em `state.queued` e entra
 * assim que a run terminar.
 */
export async function sendMessage() {
  const typed = state.objective.trim();
  if (!typed || state.sending) return;
  if (state.running || state.currentRun?.status === "ACTIVE") {
    // Mensagem agendada: o agente termina a execução atual e a seguir pega esta.
    // (Antes o botão ficava bloqueado e a mensagem simplesmente se perdia.)
    state.queued = { objective: typed, attachments: [...state.attachments] };
    state.objective = "";
    state.attachments = [];
    toast("Mensagem agendada — entra assim que a execução atual terminar", "ok");
    return;
  }
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
    await refreshTasks();
    // Selecionar a tarefa nova (com carregar os detalhes) evita que o painel continue
    // mostrando os detalhes da mensagem anterior.
    await selectTask(task.id);
    await startRun();
  } catch (err) {
    toast(err.message || "Falha ao enviar", "error");
  } finally {
    state.sending = false;
  }
}

/**
 * Cria a run da tarefa selecionada e começa a acompanhá-la.
 *
 * @returns {Promise<void>}
 * Observações: habilita o modo autônomo no servidor e dispara o primeiro passo.
 */
export async function startRun() {
  if (state.running || state.currentRun?.status === "ACTIVE") {
    toast("Já existe uma execução em andamento", "error");
    return;
  }
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
  state.currentRootId = root.id;
  startTaskPolling();
  await api(`/runs/${state.currentRun.id}/autonomous/enable`, { method: "POST" }).catch(() => {});
  try {
    await connectStream(state.currentRun.id);
  } catch (err) {
    toast("Não foi possível acompanhar a execução em tempo real", "error");
  }
  await api(`/runs/${state.currentRun.id}/step`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
  if (state.autoMode) {
    // Sem isto a execução parava no primeiro passo e parecia travada.
    void autoRun();
  }
}

/**
 * Avança a execução em um único passo e atualiza a lista de tarefas.
 *
 * @returns {Promise<void>}
 */
export async function stepRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/step`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
  await loadInspector(state.selectedTaskId);
}

/**
 * Deixa o servidor conduzir os passos até o fim da execução.
 *
 * @returns {Promise<void>}
 * Observações: ao terminar, atualiza a run e envia a mensagem que ficou na fila.
 */
export async function autoRun() {
  if (!state.currentRun) return;
  const runId = state.currentRun.id;
  state.running = true;
  try {
    // O servidor conduz os passos até o fim; a interface acompanha pelo stream.
    await api(`/runs/${runId}/execute?max_steps=80`, { method: "POST" });
  } catch (err) {
    toast(err.message || "Falha na execução automática", "error");
  } finally {
    state.running = false;
    await refreshTasks();
    await refreshRun(runId);
    stopTaskPolling();
    await flushQueue();
  }
}

/**
 * Envia a mensagem que ficou na fila (a execução anterior acabou).
 *
 * @returns {Promise<void>}
 */
export async function flushQueue() {
  if (!state.queued) return;
  const pending = state.queued;
  state.queued = null;
  state.objective = pending.objective || "";
  state.attachments = pending.attachments || [];
  await sendMessage();
}

/**
 * Cancela a mensagem agendada.
 *
 * @returns {void}
 */
export function cancelQueued() {
  state.queued = null;
  toast("Mensagem agendada cancelada", "info");
}

/**
 * Liga ou desliga o modo de execução automática e guarda a preferência no navegador.
 *
 * @param {boolean} value `true` para deixar o agente seguir sozinho.
 * @returns {void}
 */
export function setAutoMode(value) {
  state.autoMode = Boolean(value);
  localStorage.setItem("callidus-auto", state.autoMode ? "on" : "off");
}

/**
 * Pausa a execução em andamento.
 *
 * @returns {Promise<void>}
 */
export async function pauseRun() {
  if (!state.currentRun) return;
  await api(`/runs/${state.currentRun.id}/pause`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  await refreshTasks();
}

/**
 * Retoma a execução pausada da mensagem (tarefa raiz) informada.
 *
 * @param {string} rootTaskId Id da tarefa raiz da mensagem.
 * @returns {Promise<void>}
 * Observações: usa `retry_blocked=true` para devolver as etapas bloqueadas ao planejamento.
 */
export async function resumeRun(rootTaskId) {
  // A execução pausada é a da mensagem (tarefa raiz) — não a última da lista.
  const workspace = workspaceId();
  const runs = await api(`/projects/${workspace}/runs`).catch(() => []);
  const run =
    runs.find((item) => item.root_task_id === rootTaskId) ||
    (state.currentRun?.status === "PAUSED" ? state.currentRun : null);
  if (!run) {
    toast("Não encontrei a execução pausada desta mensagem", "error");
    return;
  }
  try {
    // `retry_blocked` devolve as etapas bloqueadas para planejamento (a causa já foi diagnosticada).
    await api(`/runs/${run.id}/resume?retry_blocked=true`, { method: "POST" });
    state.currentRun = { ...run, status: "ACTIVE" };
    state.currentRootId = rootTaskId;
    await connectStream(run.id);
    startTaskPolling();
    await refreshTasks();
    toast("Execução retomada", "ok");
    if (state.autoMode) {
      // Sem isto a execução ficaria "ativa" sem avançar.
      void autoRun();
    }
  } catch (err) {
    toast(err.message || "Falha ao retomar a execução", "error");
  }
}

/**
 * Cancela a execução em andamento e desconecta o stream.
 *
 * @returns {Promise<void>}
 */
export async function cancelRun() {
  if (!state.currentRun) return;
  stopTaskPolling();
  await api(`/runs/${state.currentRun.id}/cancel`, { method: "POST" }).catch((err) => toast(err.message, "error"));
  disconnectStream();
  state.currentRun = null;
  await refreshTasks();
}

/**
 * Conecta o stream SSE de uma run ao redutor local.
 *
 * @param {string} runId Id da run.
 * @returns {Promise<void>}
 * Observações: carrega a foto inicial (`/runs/{id}/observe`) e substitui o stream anterior.
 */
export async function connectStream(runId) {
  disconnectStream();
  state.outputs = [];
  state.streamEvents = [];
  const snapshot = await api(`/runs/${runId}/observe`).catch(() => ({}));
  const reducer = createState(snapshot || {});
  const replayRoot = snapshot?.run?.root_task_id;
  if (replayRoot) {
    await replayFeedFromRun(runId, replayRoot);
    state.currentRootId = state.currentRootId || replayRoot;
  }
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
      refreshRun(runId);
      flushQueue();
    },
    onStatus: (status) => {
      reducer.connection = status;
      state.liveState.version += 1;
    },
  });
}

/**
 * Enquanto a run está ativa, a lista de tarefas é atualizada para acompanhar o plano.
 *
 * @returns {void}
 */
function startTaskPolling() {
  stopTaskPolling();
  taskTimer = setInterval(() => {
    if (state.running || state.currentRun?.status === "ACTIVE") {
      refreshTasks();
    } else {
      stopTaskPolling();
    }
  }, 2500);
}

/**
 * Interrompe a atualização periódica da lista de tarefas.
 *
 * @returns {void}
 */
function stopTaskPolling() {
  if (taskTimer) {
    clearInterval(taskTimer);
    taskTimer = null;
  }
}

/**
 * Desconecta o stream da run e cancela as tarefas periódicas.
 *
 * @returns {void}
 */
export function disconnectStream() {
  if (stream) {
    if (typeof stream.stop === "function") stream.stop();
    else if (typeof stream.close === "function") stream.close();
  }
  stream = null;
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * Seleciona a tarefa inspecionada e abre o painel de detalhes.
 *
 * @param {string} taskId Id da tarefa.
 * @returns {Promise<void>}
 */
export async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  state.detailsOpen = true;
  await loadInspector(taskId);
}

// Token do inspetor: uma resposta lenta de uma tarefa antiga não pode sobrescrever a atual.
let inspectorToken = 0;

/**
 * Carrega os detalhes de uma tarefa (tentativas, evidências, snapshots e contrato).
 *
 * @param {string} taskId Id da tarefa.
 * @returns {Promise<void>}
 * Observações: uma resposta obsoleta (de uma tarefa já trocada) é descartada pelo token.
 */
export async function loadInspector(taskId) {
  const token = ++inspectorToken;
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
  if (token !== inspectorToken) return; // resposta obsoleta
  state.inspector = { task, attempts, evidences, snapshots, contract };
}

/**
 * Carrega o diff do projeto selecionado.
 *
 * @returns {Promise<void>}
 */
export async function loadDiff() {
  const project = state.selectedProject;
  if (!project) return;
  const diff = await api(`/projects/${project.id}/git-diff`).catch(() => null);
  state.diffText = diff?.diff || diff?.text || "";
}

/**
 * Carrega as métricas do workspace em andamento.
 *
 * @returns {Promise<void>}
 */
export async function loadMetrics() {
  const workspace = workspaceId();
  if (!workspace) return;
  const metrics = await api(`/projects/${workspace}/metrics`).catch(() => null);
  state.metricsText = JSON.stringify(metrics, null, 2);
}

/**
 * Pesquisa no grafo de conhecimento do projeto selecionado.
 *
 * @param {string} [query] Termo pesquisado.
 * @returns {Promise<void>}
 */
export async function loadGraph(query = "") {
  const project = state.selectedProject;
  if (!project) return;
  const result = await api(`/projects/${project.id}/knowledge/search?q=${encodeURIComponent(query)}`).catch(() => null);
  state.graphText = JSON.stringify(result, null, 2);
}

/**
 * Carrega ferramentas, disponibilidade, diagnóstico e skills instaladas.
 *
 * @returns {Promise<void>}
 */
export async function loadTools() {
  const [tools, availability, diagnosis, skills] = await Promise.all([
    api("/tools").catch(() => null),
    api("/tools/availability").catch(() => null),
    api("/system/diagnose").catch(() => null),
    api("/skills").catch(() => null),
  ]);
  state.toolsReport = { tools, availability, diagnosis, skills };
  state.toolsText = formatToolsReport(state.toolsReport);
}

/**
 * Pede ao servidor a descoberta de servidores MCP.
 *
 * @returns {Promise<void>}
 * Observações: o resultado fica em `state.mcpText`; a falha vira conteúdo, não exceção.
 */
export async function discoverMcp() {
  const result = await api("/mcp/discover", { method: "POST" }).catch((err) => ({ error: err.message }));
  state.mcpText = JSON.stringify(result, null, 2);
}

/**
 * Raiz (tarefa de topo) de uma tarefa: a atividade pertence à mensagem, não à folha.
 *
 * @param {string} taskId Id da tarefa.
 * @returns {string|null} O id da tarefa raiz, ou `null` quando não há id informado.
 */
export function rootIdOf(taskId) {
  if (!taskId) return null;
  const byId = new Map(state.tasks.map((task) => [task.id, task]));
  let current = byId.get(taskId);
  const seen = new Set();
  while (current && current.parent_id && !seen.has(current.id)) {
    seen.add(current.id);
    current = byId.get(current.parent_id);
  }
  return current?.id || taskId;
}

/**
 * Entradas de atividade do chat: pensamento, ferramentas, comandos, leituras e escritas.
 *
 * @param {object} envelope Envelope do stream.
 * @returns {void}
 * Observações: o mesmo evento atualiza a entrada existente. A saída de comando acumula
 * no comando em andamento.
 */
function pushActivity(envelope) {
  const entry = describeActivity(envelope);
  if (!entry) return;
  if (envelope?.id) entry.eventId = envelope.id;
  // A atividade vai para a mensagem (tarefa raiz) a que pertence. A raiz da execução em
  // curso é a fonte confiável: o evento chega antes de a lista de tarefas ser atualizada.
  const rootId = state.currentRootId || rootIdOf(envelope.task_id) || envelope.task_id || "live";
  if (!state.feeds[rootId]) state.feeds[rootId] = [];
  const feed = state.feeds[rootId];
  state.feed = feed;
  mergeActivity(feed, entry);
  if (feed.length > 120) feed.splice(0, feed.length - 120);
}

/**
 * Lista os modelos de um provedor e guarda o resultado em cache.
 *
 * @param {string} [providerName] Provedor consultado; sem ele, usa o provedor atual.
 * @returns {Promise<Array<string>>} Os modelos, ou lista vazia quando o provedor não responde.
 */
export async function loadModels(providerName) {
  const name = providerName || state.provider;
  if (!name) return [];
  const data = await api(`/providers/${encodeURIComponent(name)}/models`).catch(() => null);
  const models = data?.models || [];
  state.providerModels = { ...state.providerModels, [name]: models };
  return models;
}

/**
 * Testa a conexão com um provedor e guarda o resultado da saúde.
 *
 * @param {string} name Nome do provedor.
 * @returns {Promise<{ok: boolean, detail?: string}>} O resultado do teste; nunca lança.
 */
export async function testProvider(name) {
  state.providerHealth = { ...state.providerHealth, [name]: { checking: true } };
  const data = await api(`/providers/${encodeURIComponent(name)}/test`, { method: "POST" }).catch((err) => ({
    ok: false,
    detail: err.message,
  }));
  state.providerHealth = { ...state.providerHealth, [name]: data };
  return data;
}

/**
 * Grava a configuração de provedores.
 *
 * @param {object} payload Objeto com `default_provider` e `providers`.
 * @returns {Promise<object>} A configuração salva.
 */
export async function saveProviderConfig(payload) {
  const saved = await api("/providers/config", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

/**
 * Remove um provedor da configuração.
 *
 * @param {string} name Nome do provedor.
 * @returns {Promise<object>} A configuração salva.
 */
export async function removeProvider(name) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}`, { method: "DELETE" });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

/**
 * Grava a credencial de um provedor.
 *
 * @param {string} name Nome do provedor.
 * @param {string} secret Chave informada pelo usuário.
 * @returns {Promise<object>} A configuração salva.
 */
export async function setProviderSecret(name, secret) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}/secret`, {
    method: "PUT",
    body: JSON.stringify({ secret }),
  });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

/**
 * Apaga a credencial gravada de um provedor.
 *
 * @param {string} name Nome do provedor.
 * @returns {Promise<object>} A configuração salva.
 */
export async function clearProviderSecret(name) {
  const saved = await api(`/providers/config/${encodeURIComponent(name)}/secret`, { method: "DELETE" });
  state.providerConfig = saved;
  await loadProviders();
  return saved;
}

// ─────────────────────────────────────────────────────── automações

/**
 * Carrega a lista de automações, opcionalmente de um projeto só.
 *
 * @param {string} [projectId] Projeto filtro.
 * @returns {Promise<Array<object>>} As automações visíveis.
 */
export async function loadAutomations(projectId) {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const data = await api(`/automations${query}`).catch(() => []);
  state.automations = data || [];
  return state.automations;
}

/**
 * Carrega o detalhe de uma automação.
 *
 * @param {string} id Id da automação.
 * @returns {Promise<object|null>} A automação detalhada, ou `null` quando não existe.
 */
export async function loadAutomationDetail(id) {
  const data = await api(`/automations/${encodeURIComponent(id)}`).catch(() => null);
  if (data) state.automationDetail = data;
  return data;
}

/**
 * Cria uma automação a partir de uma definição.
 *
 * @param {object} definition Definição completa (gatilho, ação, permissões).
 * @param {boolean} [activate] `true` para já ativar a automação criada.
 * @returns {Promise<object>} A automação criada.
 */
export async function createAutomation(definition, activate = false) {
  const saved = await api("/automations", {
    method: "POST",
    body: JSON.stringify({ definition, activate }),
  });
  await loadAutomations();
  return saved;
}

/**
 * Executa uma ação sobre uma automação (ativar, suspender, rodar, testar, cancelar).
 *
 * @param {string} id Id da automação.
 * @param {string} action Nome da ação.
 * @param {object} [body] Corpo extra da requisição.
 * @returns {Promise<object>} A resposta do servidor.
 */
export async function automationAction(id, action, body = {}) {
  const saved = await api(`/automations/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  await loadAutomations();
  return saved;
}

/**
 * Remove uma automação.
 *
 * @param {string} id Id da automação.
 * @returns {Promise<void>}
 */
export async function deleteAutomation(id) {
  await api(`/automations/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadAutomations();
}

/**
 * Carrega a situação do supervisor de automações.
 *
 * @returns {Promise<object|null>} O estado do supervisor, ou `null` quando indisponível.
 */
export async function loadSupervisorStatus() {
  const data = await api("/automations/supervisor/status").catch(() => null);
  if (data) state.supervisor = data;
  return data;
}
