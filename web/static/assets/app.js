/** Agente de IA Local — UI principal (módulo ES) */

const STORAGE_KEY = "agente-local-ui-v1";

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function savePrefs(partial) {
  const next = { ...loadPrefs(), ...partial };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

function toast(message, type = "info") {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast${type === "error" ? " error" : ""}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text.slice(0, 280));
  }
  return res.json();
}

const state = {
  projects: [],
  conversations: [],
  loose: [],
  conversation: null,
  pendingSend: null,
  folderTarget: null,
  viewBranchId: null,
  editingTaskId: null,
  selectedProject: null,
  tasks: [],
  selectedTaskId: null,
  currentRun: null,
  uiDefaults: null,
  pollTimer: null,
  browsePath: "",
  openStageIds: new Set(),
  openChangePaths: new Set(),
  followLatest: false,
  resumeBrief: null,
  browserMode: "off",
};

const CHAT = {
  pt: { you: "Você", agent: "Agente", thought: "Pensou", thinking: "Pensando", pending: "Pensando…", planning: "Vou planejar e dividir isso em passos.", emptyTitle: "O que vamos construir?", emptyBody: "Escreva embaixo. Cada projeto guarda as conversas separadas." },
  en: { you: "You", agent: "Agent", thought: "Thought", thinking: "Thinking", pending: "Thinking…", planning: "I'll plan this and break it into steps.", emptyTitle: "What should we build?", emptyBody: "Write below. Each project keeps its own chats." },
  es: { you: "Tú", agent: "Agente", thought: "Pensó", thinking: "Pensando", pending: "Pensando…", planning: "Voy a planear y dividir esto en pasos.", emptyTitle: "¿Qué vamos a construir?", emptyBody: "Escribe abajo. Cada proyecto guarda sus conversaciones." },
};

function uiLocale() {
  const code = state.conversation?.locale;
  if (code && CHAT[code]) return code;
  const nav = (navigator.language || "pt").toLowerCase();
  if (nav.startsWith("en")) return "en";
  if (nav.startsWith("es")) return "es";
  return "pt";
}

function chatCopy() {
  return CHAT[uiLocale()] || CHAT.pt;
}

const E2E_FIXTURE_HINT = "tests/fixtures/sample_project";

const templates = {
  e2e: {
    title: "Demo E2E calc",
    objective: "e2e corrigir calc.py e validar testes",
    rootHint: true,
  },
};

const ICONS = {
  plus: '<path d="M8 3v10M3 8h10"/>',
  play: '<path d="M5 3.5v9l8-4.5-8-4.5z"/>',
  pause: '<path d="M5 3.5h2.2v9H5zM8.8 3.5H11v9H8.8z"/>',
  stop: '<rect x="4" y="4" width="8" height="8" rx="1"/>',
  panel: '<rect x="2.5" y="3" width="11" height="10" rx="1"/><path d="M8 3v10"/>',
  paperclip: '<path d="M6 8.5l4.2-4.2a2 2 0 0 1 2.8 2.8L7.2 13a3 3 0 0 1-4.2-4.2l5.6-5.6"/>',
  wrench: '<path d="M10.5 3.2a2.4 2.4 0 0 0-3.2 3.2L3.2 10.5 5.5 12.8l4.1-4.1a2.4 2.4 0 0 0 3.2-3.2L11 7.3 8.7 5l1.8-1.8z"/>',
  send: '<path d="M8 13V3M4 7l4-4 4 4"/>',
  file: '<path d="M4 2.5h5l3 3V13.5H4z"/><path d="M9 2.5V6h3"/>',
  refresh: '<path d="M13 8a5 5 0 1 1-1.4-3.4"/><path d="M13 2.5V5.5H10"/>',
  check: '<path d="M3 8.5l3.2 3.2L13 4.5"/>',
  diff: '<path d="M4 3h8M4 8h8M4 13h5"/>',
  layers: '<path d="M8 2.5l6 3-6 3-6-3 6-3zM2 8l6 3 6-3M2 11.5l6 3 6-3"/>',
  chart: '<path d="M3 13V8M8 13V3M13 13V6"/>',
  share: '<circle cx="4" cy="8" r="1.4"/><circle cx="12" cy="4" r="1.4"/><circle cx="12" cy="12" r="1.4"/><path d="M5.3 7.2l5.4-2.4M5.3 8.8l5.4 2.4"/>',
  plug: '<path d="M6 2.5v3M10 2.5v3M4.5 6h7v2.2a3.5 3.5 0 0 1-7 0zM8 11.7V14"/>',
  spark: '<path d="M8 1.8l1.2 3.6L13 6.6 9.2 8l-1.2 3.6L6.8 8 3 6.6l3.8-1.2z"/>',
  terminal: '<path d="M3 4l4 4-4 4M8 12h5"/>',
  search: '<circle cx="7" cy="7" r="3.2"/><path d="M9.5 9.5L13 13"/>',
  pencil: '<path d="M10 3.5l2.5 2.5L6 12.5H3.5V10z"/>',
  folder: '<path d="M2.5 4.5h4l1.2 1.5H13.5v7H2.5z"/>',
  alert: '<path d="M8 2.5l6 11H2zM8 7v3M8 12h.01"/>',
  circle: '<circle cx="8" cy="8" r="3"/>',
  git: '<circle cx="4" cy="4" r="1.3"/><circle cx="4" cy="12" r="1.3"/><circle cx="12" cy="8" r="1.3"/><path d="M4 5.3v5.4M5.2 4h3.2a3.6 3.6 0 0 1 0 4H4"/>',
  chat: '<path d="M3 3.5h10v7H6.2L3 13z"/>',
  more: '<circle cx="4" cy="8" r="0.9"/><circle cx="8" cy="8" r="0.9"/><circle cx="12" cy="8" r="0.9"/>',
  trash: '<path d="M3.5 4.5h9M6 4.5V3.2h4v1.3M5 6.5l.4 7h5.2l.4-7"/>',
  up: '<path d="M8 12V4M4.5 7.5L8 4l3.5 3.5"/>',
  chevron: '<path d="M6 4l4 4-4 4"/>',
  globe: '<circle cx="8" cy="8" r="5.2"/><path d="M3 8h10M8 2.8c1.5 1.7 1.5 8.7 0 10.4M8 2.8c-1.5 1.7-1.5 8.7 0 10.4"/>',
  clock: '<circle cx="8" cy="8" r="5.2"/><path d="M8 4.8V8l2.2 1.4"/>',
  timer: '<circle cx="8" cy="9.2" r="4.3"/><path d="M8 4.9V3.1M6.3 3.1h3.4M8 7.2v2.2"/>',
  token: '<rect x="3" y="3" width="10" height="10" rx="2.2"/><circle cx="8" cy="8" r="1.7"/>',
};

function icon(name) {
  const body = ICONS[name] || ICONS.circle;
  return `<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

function paintIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.querySelector("svg")) return;
    el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon));
  });
}

const STATUS_ICON = {
  PENDING: "circle",
  READY: "circle",
  PLANNING: "spark",
  RUNNING: "refresh",
  VERIFYING: "check",
  COMPLETED: "check",
  FAILED: "alert",
  BLOCKED: "alert",
  CANCELLED: "stop",
  RETRY_PENDING: "refresh",
};

function statusBadge(status) {
  return `<span class="status-ico status-${status}" title="${escapeHtml(status)}">${icon(STATUS_ICON[status] || "circle")}</span>`;
}

const TOOL_ICON = {
  read_file: "file",
  write_file: "pencil",
  edit_file: "pencil",
  search_grep: "search",
  list_dir: "folder",
  glob_files: "search",
  run_command: "terminal",
  run_script: "terminal",
  run_pytest: "check",
  git_diff: "git",
  git_status: "git",
  delete_file: "alert",
  verificação: "check",
  modelo: "spark",
  browser: "globe",
};

function parseStamp(iso) {
  if (!iso) return null;
  const text = String(iso).trim().replace(" ", "T");
  const hasZone = /[zZ]$|[+-]\d\d:?\d\d$/.test(text);
  const date = new Date(hasZone ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatWhen(iso) {
  const date = parseStamp(iso);
  if (!date) return "";
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === new Date().toDateString()) return time;
  const day = date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return `${day} ${time}`;
}

function formatTime(iso) {
  return formatWhen(iso);
}

function formatSpan(ms) {
  const sec = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(sec / 3600);
  const minutes = Math.floor((sec % 3600) / 60);
  const seconds = sec % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatTokens(value) {
  const count = Number(value) || 0;
  if (count <= 0) return "";
  if (count < 1000) return String(count);
  const scaled = count / 1000;
  const text = scaled >= 10 ? String(Math.round(scaled)) : scaled.toFixed(1).replace(".", ",");
  return `${text}k`;
}

function meterParts(startIso, endIso, tokens, live) {
  const start = parseStamp(startIso);
  if (!start) return null;
  const end = live ? new Date() : parseStamp(endIso) || new Date();
  return { span: formatSpan(end - start), spent: formatTokens(tokens) };
}

function stampTag(iso) {
  const when = formatWhen(iso);
  if (!when) return "";
  return `<time class="stamp" title="Horário">${icon("clock")}<span>${escapeHtml(when)}</span></time>`;
}

function meterTag(startIso, endIso, tokens, live) {
  const parts = meterParts(startIso, endIso, tokens, live);
  if (!parts) return "";
  const spent = parts.spent
    ? `${icon("token")}<span class="spent" title="Tokens">${escapeHtml(parts.spent)}</span>`
    : "";
  return `<time class="meter" title="Tempo" data-meter-start="${escapeHtml(startIso || "")}" data-meter-end="${escapeHtml(endIso || "")}" data-meter-tokens="${Number(tokens) || 0}" data-meter-live="${live ? "1" : "0"}">${icon("timer")}<span class="span">${escapeHtml(parts.span)}</span>${spent}</time>`;
}

function taskTokens(task) {
  return Number(task?.usage_tokens) || Number(task?.metadata_json?.usage?.total) || 0;
}

function stageMeter(task) {
  const live = ["PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"].includes(task.status);
  const start = task.started_at || (live ? task.created_at : null);
  if (!start) return "";
  return meterTag(start, task.completed_at || task.updated_at, taskTokens(task), live);
}

function runMeter(root) {
  const ids = descendantIds(root.id);
  const tasks = state.tasks.filter((task) => ids.has(task.id));
  const live = tasks.some((task) => ["PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"].includes(task.status));
  const tokens = tasks.reduce((sum, task) => sum + taskTokens(task), 0);
  const end = tasks.reduce((latest, task) => {
    const stamp = task.completed_at || task.updated_at;
    return !latest || (stamp && stamp > latest) ? stamp : latest;
  }, root.completed_at || root.updated_at);
  return meterTag(root.created_at, end, tokens, live);
}

function runConfigFromUI(objective) {
  const provider = document.getElementById("sel-provider").value;
  const model_id = document.getElementById("sel-model").value || state.uiDefaults?.model_id || "llama3.2";
  const approve = document.getElementById("chk-approve-tools").checked;
  const demoE2e = objective.toLowerCase().includes("e2e");
  if (demoE2e && provider !== "mock") {
    return { provider: "mock", approve_risky_tools: approve };
  }
  return {
    provider,
    model_id,
    approve_risky_tools: approve,
    use_generic_template: true,
    browser_mode: state.browserMode || "off",
  };
}

function chatMenu(conversation) {
  const menu = document.createElement("details");
  menu.className = "chat-menu";
  const targets = [`<button type="button" data-move="">Sem projeto</button>`]
    .concat(
      state.projects
        .filter((project) => project.id !== conversation.project_id)
        .map((project) => `<button type="button" data-move="${project.id}">${escapeHtml(project.name)}</button>`)
    )
    .concat([
      `<button type="button" data-rename="${conversation.id}">Renomear</button>`,
      `<button type="button" data-folder="${conversation.id}">Alterar pasta</button>`,
      `<button type="button" data-remove="${conversation.id}">Remover</button>`,
    ]);
  if (!conversation.project_id) targets.shift();
  menu.innerHTML = `<summary title="Mover ou remover" aria-label="Mover ou remover">${icon("more")}</summary><div class="more-panel">${targets.join("")}</div>`;
  menu.onclick = (event) => event.stopPropagation();
  menu.addEventListener("toggle", () => {
    if (!menu.open) return;
    const panel = menu.querySelector(".more-panel");
    const rect = menu.getBoundingClientRect();
    panel.style.position = "fixed";
    panel.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 180)}px`;
    panel.style.left = `${Math.max(8, rect.right - 180)}px`;
    panel.style.right = "auto";
    panel.style.bottom = "auto";
    panel.style.zIndex = "40";
  });
  menu.addEventListener("click", async (event) => {
    const move = event.target.closest("[data-move]");
    const remove = event.target.closest("[data-remove]");
    const rename = event.target.closest("[data-rename]");
    const folder = event.target.closest("[data-folder]");
    if (!move && !remove && !rename && !folder) return;
    event.preventDefault();
    try {
      if (remove) await removeConversation(conversation);
      else if (rename) beginRename();
      else if (folder) {
        state.folderTarget = { type: "conversation", id: conversation.id };
        await openFolderPicker(conversation.root_path || "");
      } else await moveConversation(conversation, move.dataset.move || null);
    } catch (err) {
      toast(err.message, "error");
    }
  });
  return menu;
}

function appendChat(list, conversation, onOpen) {
  const item = document.createElement("li");
  item.className = "chat-row";
  const chatBtn = document.createElement("button");
  chatBtn.type = "button";
  if (state.conversation?.id === conversation.id) chatBtn.classList.add("active");
  chatBtn.innerHTML = `${icon("chat")}<span class="chat-title">${escapeHtml(conversation.title)}</span>${stampTag(conversation.updated_at)}`;
  chatBtn.onclick = () => onOpen(conversation);
  item.appendChild(chatBtn);
  item.appendChild(chatMenu(conversation));
  list.appendChild(item);
}

function renderLoose() {
  const list = document.getElementById("loose-list");
  if (!list) return;
  list.innerHTML = "";
  state.loose.forEach((conversation) => appendChat(list, conversation, selectLoose));
}

function renderProjects(filter = "") {
  renderLoose();
  const ul = document.getElementById("project-list");
  ul.innerHTML = "";
  const q = filter.trim().toLowerCase();
  state.projects
    .filter((p) => !q || p.name.toLowerCase().includes(q) || p.root_path.toLowerCase().includes(q))
    .forEach((p) => {
      const li = document.createElement("li");
      const row = document.createElement("div");
      row.className = "project-row";
      const open = state.selectedProject?.id === p.id;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "project-name";
      btn.title = p.root_path;
      if (open) btn.classList.add("active");
      btn.innerHTML = `<span class="chevron${open ? " open" : ""}">${icon("chevron")}</span>${icon("folder")}<span>${escapeHtml(p.name)}</span>`;
      btn.onclick = () => selectProject(p);
      row.appendChild(btn);
      if (state.selectedProject?.id === p.id) {
        const folder = document.createElement("button");
        folder.type = "button";
        folder.className = "icon-btn";
        folder.title = "Alterar pasta";
        folder.setAttribute("aria-label", "Alterar pasta do projeto");
        folder.innerHTML = icon("folder");
        folder.onclick = (event) => {
          event.stopPropagation();
          state.folderTarget = { type: "project", id: p.id };
          openFolderPicker(p.root_path).catch((err) => toast(err.message, "error"));
        };
        row.appendChild(folder);
        const rename = document.createElement("button");
        rename.type = "button";
        rename.className = "icon-btn";
        rename.title = "Renomear projeto";
        rename.setAttribute("aria-label", "Renomear projeto");
        rename.innerHTML = icon("pencil");
        rename.onclick = (event) => {
          event.stopPropagation();
          beginRenameProject(p);
        };
        row.appendChild(rename);
        const add = document.createElement("button");
        add.type = "button";
        add.className = "icon-btn";
        add.title = "Nova conversa";
        add.setAttribute("aria-label", "Nova conversa");
        add.innerHTML = icon("chat");
        add.onclick = (event) => {
          event.stopPropagation();
          startConversation();
        };
        row.appendChild(add);
      }
      li.appendChild(row);
      if (state.selectedProject?.id === p.id && state.conversations.length) {
        const chats = document.createElement("ul");
        chats.className = "chats";
        state.conversations.forEach((conversation) => appendChat(chats, conversation, selectConversation));
        li.appendChild(chats);
      }
      ul.appendChild(li);
    });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function selectProject(p) {
  state.selectedProject = p;
  state.selectedTaskId = null;
  state.currentRun = null;
  savePrefs({ lastProjectId: p.id });
  document.getElementById("run-toolbar").hidden = false;
  document.getElementById("btn-new-chat").hidden = false;
  state.conversations = await api(`/projects/${p.id}/conversations`);
  const prefs = loadPrefs();
  state.conversation =
    state.conversations.find((item) => item.id === prefs.lastConversationId) || state.conversations[0] || null;
  if (state.conversation) savePrefs({ lastConversationId: state.conversation.id });
  paintWorkspace();
  renderProjects(document.getElementById("project-search").value);
  await refreshAll();
  updateRunButtons();
}

function selectConversation(conversation) {
  state.conversation = conversation;
  state.selectedTaskId = null;
  state.openStageIds = new Set();
  state.followLatest = false;
  state.resumeBrief = null;
  state.viewBranchId = conversation.active_branch_id || null;
  state.editingTaskId = null;
  savePrefs({ lastConversationId: conversation.id });
  paintWorkspace();
  renderProjects(document.getElementById("project-search").value);
  refreshTasks().catch((err) => toast(err.message, "error"));
}

function paintWorkspace() {
  const conversation = state.conversation;
  const title = document.getElementById("workspace-title");
  if (title && title.tagName === "H1") {
    title.textContent = conversation?.title || state.selectedProject?.name || "Novo chat";
  }
  const subtitle = document.getElementById("workspace-subtitle");
  if (subtitle) {
    const home = !state.selectedProject || state.selectedProject.path_origin === "home";
    const path = conversation?.root_path || state.selectedProject?.root_path || "";
    subtitle.textContent = home && conversation?.path_origin !== "chosen" ? "Pasta do usuário" : path || "Pasta do usuário";
    subtitle.title = path;
  }
  paintBranches();
}

function paintBranches() {
  const box = document.getElementById("branch-switch");
  const branches = state.conversation?.branches || [];
  if (!box) return;
  box.hidden = branches.length < 2;
  if (branches.length < 2) return;
  const active = state.viewBranchId || state.conversation.active_branch_id;
  const index = Math.max(0, branches.findIndex((item) => item.id === active));
  const label = document.getElementById("branch-label");
  if (label) label.textContent = `${index + 1}/${branches.length}`;
}

function applyConversation(updated) {
  if (!updated) return;
  if (updated.project_id) {
    state.conversations = state.conversations.map((item) => (item.id === updated.id ? updated : item));
  } else {
    state.loose = state.loose.map((item) => (item.id === updated.id ? updated : item));
    if (!state.loose.some((item) => item.id === updated.id)) state.loose = [updated, ...state.loose];
  }
  if (state.conversation?.id === updated.id) {
    state.conversation = updated;
    state.viewBranchId = updated.active_branch_id;
  }
}

function workspaceId() {
  return state.selectedProject?.id || state.conversation?.workspace_id || null;
}

function beginRename() {
  if (!state.conversation) return;
  const title = document.getElementById("workspace-title");
  if (!title || title.tagName !== "H1") return;
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = state.conversation.title || "";
  input.setAttribute("aria-label", "Nome da conversa");
  title.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    const h1 = document.createElement("h1");
    h1.id = "workspace-title";
    input.replaceWith(h1);
    if (save && value && value !== state.conversation.title) {
      const updated = await api(`/conversations/${state.conversation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: value }),
      });
      applyConversation(updated);
      renderProjects(document.getElementById("project-search").value);
      toast("Conversa renomeada");
    }
    paintWorkspace();
  };
  input.onkeydown = (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  };
  input.onblur = () => finish(true);
}

function beginRenameProject(project) {
  const field = document.createElement("input");
  field.className = "rename-input";
  field.value = project.name;
  field.setAttribute("aria-label", "Nome do projeto");
  const title = document.getElementById("workspace-title");
  if (!title || title.tagName !== "H1") return;
  title.replaceWith(field);
  field.focus();
  field.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const value = field.value.trim();
    const h1 = document.createElement("h1");
    h1.id = "workspace-title";
    field.replaceWith(h1);
    if (save && value && value !== project.name) {
      const updated = await api(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: value }),
      });
      state.projects = state.projects.map((item) => (item.id === updated.id ? updated : item));
      if (state.selectedProject?.id === updated.id) state.selectedProject = updated;
      renderProjects(document.getElementById("project-search").value);
      toast("Projeto renomeado");
    }
    paintWorkspace();
  };
  field.onkeydown = (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  };
  field.onblur = () => finish(true);
}

function selectLoose(conversation) {
  state.selectedProject = null;
  state.tasks = [];
  state.currentRun = null;
  state.selectedTaskId = null;
  document.getElementById("run-toolbar").hidden = true;
  document.getElementById("stats-bar").hidden = true;
  selectConversation(conversation);
  savePrefs({ lastProjectId: null, lastConversationId: conversation.id });
}

async function moveConversation(conversation, projectId) {
  const moved = await api(`/conversations/${conversation.id}/move`, {
    method: "POST",
    body: JSON.stringify({ project_id: projectId || null }),
  });
  state.loose = await api("/conversations");
  if (moved.project_id) {
    const project = state.projects.find((item) => item.id === moved.project_id);
    if (project) await selectProject(project);
    const current = state.conversations.find((item) => item.id === moved.id) || moved;
    selectConversation(current);
    toast("Conversa movida");
    return;
  }
  selectLoose(state.loose.find((item) => item.id === moved.id) || moved);
  toast("Conversa fora de projeto");
}

async function removeConversation(conversation) {
  await api(`/conversations/${conversation.id}`, { method: "DELETE" });
  if (state.conversation?.id === conversation.id) {
    state.conversation = null;
    state.tasks = [];
    state.selectedTaskId = null;
    document.getElementById("workspace-title").textContent = "Novo chat";
  }
  state.loose = await api("/conversations");
  if (state.selectedProject) {
    state.conversations = await api(`/projects/${state.selectedProject.id}/conversations`);
    await refreshTasks();
  }
  renderProjects(document.getElementById("project-search").value);
  renderChat();
  toast("Conversa removida");
}

async function openFolderPicker(start) {
  document.getElementById("folder-modal").hidden = false;
  paintIcons(document.getElementById("folder-modal"));
  await loadFolder(start || state.conversation?.root_path || state.selectedProject?.root_path || "");
}

async function loadFolder(path) {
  const data = await api(`/fs/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
  state.browsePath = data.path;
  document.getElementById("folder-path").textContent = data.path;
  document.getElementById("folder-up").dataset.parent = data.parent || "";
  document.getElementById("folder-up").disabled = !data.parent;
  const list = document.getElementById("folder-entries");
  list.innerHTML = "";
  (data.entries || []).forEach((entry) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `${icon("folder")}<span>${escapeHtml(entry.name)}</span>`;
    button.onclick = () => loadFolder(entry.path).catch((err) => toast(err.message, "error"));
    item.appendChild(button);
    list.appendChild(item);
  });
}

async function useFolder(path) {
  if (!path) return;
  document.getElementById("folder-modal").hidden = true;
  const target = state.folderTarget;
  state.folderTarget = null;
  if (!target) return;
  if (target.type === "project") {
    const updated = await api(`/projects/${target.id}`, {
      method: "PATCH",
      body: JSON.stringify({ root_path: path }),
    });
    state.projects = state.projects.map((item) => (item.id === updated.id ? updated : item));
    if (state.selectedProject?.id === updated.id) state.selectedProject = updated;
    toast("Pasta do projeto atualizada");
  } else {
    const updated = await api(`/conversations/${target.id}`, {
      method: "PATCH",
      body: JSON.stringify({ root_path: path }),
    });
    applyConversation(updated);
    toast("Pasta da conversa atualizada");
  }
  paintWorkspace();
  renderProjects(document.getElementById("project-search").value);
}

async function shiftBranch(delta) {
  const branches = state.conversation?.branches || [];
  if (branches.length < 2) return;
  const active = state.viewBranchId || state.conversation.active_branch_id;
  let index = branches.findIndex((item) => item.id === active);
  if (index < 0) index = 0;
  index = (index + delta + branches.length) % branches.length;
  const branch = branches[index];
  const updated = await api(`/conversations/${state.conversation.id}/branches/${branch.id}/activate`, {
    method: "POST",
  });
  applyConversation(updated);
  state.viewBranchId = branch.id;
  await refreshTasks();
  paintWorkspace();
}

async function startLooseConversation() {
  const conversation = await api("/conversations", { method: "POST", body: JSON.stringify({}) });
  state.loose = [conversation, ...state.loose.filter((item) => item.id !== conversation.id)];
  selectLoose(conversation);
  document.querySelector("#form-task textarea")?.focus();
}

async function startConversation() {
  if (!state.selectedProject) {
    await startLooseConversation();
    return;
  }
  const conversation = await api(`/projects/${state.selectedProject.id}/conversations`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.conversations = [conversation, ...state.conversations.filter((item) => item.id !== conversation.id)];
  selectConversation(conversation);
  document.querySelector("#form-task textarea")?.focus();
}

function buildTreeNodes(tasks, parentId = null, depth = 0) {
  const filter = document.getElementById("task-filter-status").value;
  return tasks
    .filter((t) => t.parent_id === parentId)
    .filter((t) => !filter || t.status === filter)
    .flatMap((t) => {
      const node = { task: t, depth };
      return [node, ...buildTreeNodes(tasks, t.id, depth + 1)];
    });
}

function renderTaskTree() {
  const container = document.getElementById("task-tree");
  container.innerHTML = "";
  const visible = state.conversation
    ? state.tasks.filter((task) => task.conversation_id === state.conversation.id)
    : state.tasks;
  const nodes = buildTreeNodes(visible);
  if (!nodes.length) {
    container.innerHTML = `<p class="muted">Nenhuma tarefa. Crie um objetivo acima.</p>`;
    return;
  }
  nodes.forEach(({ task, depth }) => {
    const div = document.createElement("div");
    const busy = ["RUNNING", "VERIFYING", "PLANNING"].includes(task.status) ? " busy" : "";
    div.className = `tree-node${task.id === state.selectedTaskId ? " selected" : ""}${busy}`;
    div.setAttribute("role", "treeitem");
    div.innerHTML = `<span class="indent" style="width:${depth * 12}px"></span>${statusBadge(task.status)} <span>${escapeHtml(titleOf(task))}</span>`;
    div.onclick = () => selectTask(task.id);
    container.appendChild(div);
  });
  if (!state.selectedTaskId && visible.length) {
    const root = visible.find((task) => !task.parent_id) || visible[0];
    selectTask(root.id);
  }
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  renderTaskTree();
  await loadInspector(taskId);
}

async function loadInspector(taskId) {
  const task = await api(`/tasks/${taskId}`);
  const detail = document.getElementById("tab-detail");
  detail.innerHTML = `
    <div class="detail-block"><h3>Título</h3><p>${escapeHtml(task.title)}</p></div>
    <div class="detail-block"><h3>Objetivo</h3><p>${escapeHtml(task.objective)}</p></div>
    <div class="detail-block"><h3>Estado</h3><p>${statusBadge(task.status)}</p></div>
    <div class="detail-block"><h3>Critérios</h3><p>${escapeHtml(task.acceptance_criteria || "—")}</p></div>
    <div class="detail-block"><h3>Metadata</h3><pre>${escapeHtml(JSON.stringify(task.metadata_json || {}, null, 2))}</pre></div>
    <div class="detail-block"><h3>Resultado consolidado</h3><pre>${escapeHtml(JSON.stringify(task.consolidated_result_json || {}, null, 2))}</pre></div>
  `;
  const [attempts, evidences] = await Promise.all([
    api(`/tasks/${taskId}/attempts`),
    api(`/tasks/${taskId}/evidences`),
  ]);
  document.getElementById("attempts-view").textContent = JSON.stringify(attempts, null, 2);
  document.getElementById("evidence-view").textContent = JSON.stringify(evidences, null, 2);
  try {
    const snaps = await api(`/tasks/${taskId}/context-snapshots`);
    document.getElementById("context-view").textContent = JSON.stringify(snaps, null, 2);
  } catch {
    document.getElementById("context-view").textContent = "—";
  }
  try {
    const contract = await api(`/tasks/${taskId}/contract`);
    detail.innerHTML += `<div class="detail-block"><h3>Contrato</h3><pre>${escapeHtml(JSON.stringify(contract, null, 2))}</pre></div>`;
  } catch {
    /* sem contrato */
  }
}

async function refreshOverview() {
  const workspace = workspaceId();
  if (!workspace) return;
  const ov = await api(`/projects/${workspace}/overview`);
  const bar = document.getElementById("stats-bar");
  const chips = Object.entries(ov.tasks_by_status || {})
    .map(([st, n]) => `<span class="stat-chip">${st}: ${n}</span>`)
    .join("");
  bar.innerHTML = `<span class="stat-chip">Tarefas: ${ov.task_total}</span>${chips}
    <span class="stat-chip ${ov.active_run_id ? "ok" : ""}">Run ativo: ${ov.active_run_id ? "sim" : "não"}</span>`;
  if (ov.active_run_id && !state.currentRun) {
    state.currentRun = { id: ov.active_run_id, status: "active" };
    updateRunButtons();
  }
}

async function refreshTasks() {
  if (state.conversation) {
    const branch = state.viewBranchId || state.conversation.active_branch_id;
    const query = branch ? `?branch_id=${encodeURIComponent(branch)}` : "";
    state.tasks = await api(`/conversations/${state.conversation.id}/tasks${query}`);
    renderTaskTree();
    renderChat();
    paintBranches();
    updateRunButtons();
    return;
  }
  const workspace = workspaceId();
  if (!workspace) return;
  state.tasks = await api(`/projects/${workspace}/tasks`);
  renderTaskTree();
  renderChat();
}

const ACTION_PT = {
  started_planning: "Começou a planejar",
  decomposed: "Dividiu em subtarefas",
  replanned: "Replanejou o restante",
  operation_ready: "Operação pronta",
  verified_ok: "Verificação passou",
  verify_failed: "Verificação falhou",
  run_completed: "Objetivo concluído",
  blocked_contract: "Bloqueou: falta contrato",
  blocked_loop: "Bloqueou: loop",
  tool_executed: "Executou ferramenta",
  consolidated_parent: "Consolidou o pai",
  model_operation_invalid: "Resposta do modelo inválida",
};

function eventLabel(ev) {
  const p = ev.payload_json || {};
  if (ev.event_type === "orchestrator.action") {
    const label = ACTION_PT[p.action] || p.action || "passo";
    const extra = p.source ? ` (${p.source})` : p.count ? ` · ${p.count} itens` : "";
    return `${label}${extra}`;
  }
  if (ev.event_type === "task.status_changed") return `${p.from} → ${p.to}${p.reason ? ` (${p.reason})` : ""}`;
  if (ev.event_type === "orchestrator.step") return `Olhando “${p.task || "tarefa"}” · ${p.status || ""}`;
  if (ev.event_type === "attempt.recorded") return p.success ? "Tentativa registrada" : "Tentativa com falha";
  return ev.event_type;
}

function renderLive(live) {
  const board = document.getElementById("live-board");
  if (board) board.hidden = true;
  const model = live?.model?.model_id || "—";
  const provider = live?.model?.provider || "";
  const tool = live?.operation?.tool || "";
  const statusAction = document.getElementById("status-action");
  const statusModel = document.getElementById("status-model");
  const statusTool = document.getElementById("status-tool");
  const headline = live?.headline || "Parado";
  if (statusAction) {
    const glyph = live?.thinking ? "spark" : live?.action === "run_completed" ? "check" : "circle";
    statusAction.innerHTML = icon(glyph);
    statusAction.title = headline;
  }
  if (statusModel) {
    statusModel.innerHTML = icon("spark");
    statusModel.title = provider ? `${provider} · ${model}` : model;
  }
  if (statusTool) {
    statusTool.innerHTML = icon(TOOL_ICON[tool] || "wrench");
    statusTool.title = tool || "sem ferramenta";
  }
}

async function refreshActivity() {
  const workspace = workspaceId();
  if (!workspace) return;
  const events = await api(`/projects/${workspace}/events`);
  const ul = document.getElementById("activity-feed");
  ul.innerHTML = "";
  events.slice(0, 40).forEach((ev) => {
    const li = document.createElement("li");
    li.innerHTML = `${stampTag(ev.created_at)}<span>${icon("circle")}${escapeHtml(eventLabel(ev))}</span>`;
    ul.appendChild(li);
  });
}

async function refreshLive() {
  const workspace = workspaceId();
  if (!workspace) return;
  const live = await api(`/projects/${workspace}/live`);
  state.live = live;
  renderLive(live);
  if (live.run && !state.currentRun) {
    state.currentRun = { id: live.run.id, status: live.run.status };
    updateRunButtons();
  }
}

function descendantIds(rootId) {
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

function sameTitleCount(task) {
  const title = String(task.title || "");
  let count = 0;
  const walk = (parentId) => {
    for (const child of state.tasks) {
      if (child.parent_id !== parentId) continue;
      if (String(child.title || "") === title) count += 1;
      walk(child.id);
    }
  };
  walk(task.id);
  return count;
}

function thoughtBlock(root) {
  const live = state.live;
  if (!live) return "";
  const ids = descendantIds(root.id);
  const focusHere = !live.focus || ids.has(live.focus.id);
  if (!focusHere) return "";
  const noisy = /^(Planejando|Pronta para executar|Concluída sem teste|Liberada|Aguardando|Começando|Planning|Ready to run|Finished without|Released|Waiting|Starting)/;
  const lines = (live.thoughts || []).filter((item) => {
    if (item.task_id && !ids.has(item.task_id)) return false;
    return item.phase !== "step" || !noisy.test(item.text || "");
  });
  if (!lines.length && !live.thinking) return "";
  const open = live.thinking ? " open" : "";
  const copy = chatCopy();
  const items = lines
    .map((item) => {
      const glyph = item.phase === "thinking" || item.phase === "model" ? "spark" : item.phase === "tool" ? "terminal" : "check";
      const again = Number(item.repeat) > 1 ? " · igual, sem diferença" : "";
      const klass = `${item.phase || "step"}${again ? " again" : ""}`;
      return `<li class="${escapeHtml(klass)}">${icon(glyph)}<span>${escapeHtml(item.text || "")}${escapeHtml(again)}</span></li>`;
    })
    .join("");
  const pending = live.thinking ? `<li class="thinking">${icon("spark")}<span>${copy.pending}</span></li>` : "";
  const label = live.thinking ? copy.thinking : copy.thought;
  return `<details class="thought"${open}><summary>${live.thinking ? '<i class="spin"></i>' : icon("spark")}<span>${label}</span></summary><ol>${items}${pending}</ol></details>`;
}

function toolOf(task) {
  const meta = task.metadata_json || {};
  if (meta.tool) return meta.tool;
  if (meta.verification) return "verificação";
  if (meta.model_operation) return "modelo";
  return "";
}

function resultLine(task) {
  const result = task.consolidated_result_json;
  if (!result) return "";
  const inner = result.result || result;
  if (inner.stderr && inner.success) return String(inner.stderr).split("\n").slice(-3).join(" ");
  if (inner.error) return String(inner.error);
  if (inner.summary) return String(inner.summary);
  if (inner.stdout) return String(inner.stdout).trim().split("\n").slice(-2).join(" ");
  return "";
}

function linkifyText(html) {
  return html
    .split(/(<[^>]+>)/)
    .map((part) => {
      if (part.startsWith("<")) return part;
      return part.replace(/https?:\/\/[^\s<]+/g, (url) => {
        const clean = url.replace(/[),.;]+$/, "");
        const tail = url.slice(clean.length);
        return `<a href="${clean}" target="_blank" rel="noreferrer">${clean}</a>${tail}`;
      });
    })
    .join("");
}

function renderInline(text) {
  const html = escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
      if (/^https?:\/\//i.test(href)) {
        return `<a href="${href}" target="_blank" rel="noreferrer">${label}</a>`;
      }
      if (/^(?:\/|\.\/|\.\.\/)/.test(href) || /[\w.-]+\.[A-Za-z0-9]{1,8}$/.test(href)) {
        return `<button type="button" class="ref-link" data-change-path="${href}">${label}</button>`;
      }
      return label;
    });
  return linkifyText(html);
}

function renderDiagram(source) {
  const nodes = new Map();
  const edges = [];
  String(source || "")
    .split("\n")
    .forEach((line) => {
      const labeled = [...line.matchAll(/([A-Za-z0-9_]+)\[([^\]]+)\]/g)];
      labeled.forEach((match) => nodes.set(match[1], match[2]));
      const edge = line.match(/([A-Za-z0-9_]+)\s*-->(?:\|[^|]*\|)?\s*([A-Za-z0-9_]+)/);
      if (edge) {
        nodes.set(edge[1], nodes.get(edge[1]) || edge[1]);
        nodes.set(edge[2], nodes.get(edge[2]) || edge[2]);
        edges.push([edge[1], edge[2]]);
      }
    });
  if (!nodes.size) return `<pre class="diagram">${escapeHtml(source)}</pre>`;
  const ids = [...nodes.keys()];
  const width = 280;
  const height = ids.length * 56 + 16;
  const boxes = ids
    .map((id, index) => {
      const y = 16 + index * 56;
      return `<rect x="40" y="${y}" width="200" height="36" rx="8" class="box"/><text x="140" y="${y + 23}" text-anchor="middle">${escapeHtml(nodes.get(id))}</text>`;
    })
    .join("");
  const arrows = edges
    .map(([from, to]) => {
      const a = ids.indexOf(from);
      const b = ids.indexOf(to);
      if (a < 0 || b < 0) return "";
      const y1 = 16 + a * 56 + 36;
      const y2 = 16 + b * 56;
      return `<line x1="140" y1="${y1}" x2="140" y2="${y2}" class="arrow"/>`;
    })
    .join("");
  return `<div class="diagram"><svg viewBox="0 0 ${width} ${height}" role="img">${arrows}${boxes}</svg></div>`;
}

function renderMarkdownBlocks(chunk) {
  const lines = String(chunk || "").split("\n");
  const html = [];
  let list = null;
  let table = [];
  const flushList = () => {
    if (!list) return;
    html.push(`<${list.tag}>${list.items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</${list.tag}>`);
    list = null;
  };
  const flushTable = () => {
    if (!table.length) return;
    const parsed = table.filter((row) => row.includes("|") && !/^\s*\|?[\s:|-]+\|?\s*$/.test(row));
    if (parsed.length) {
      const head = parsed[0].split("|").slice(1, -1).map((c) => c.trim());
      const body = parsed.slice(1);
      html.push(
        `<table class="md-table"><thead><tr>${head.map((c) => `<th>${renderInline(c)}</th>`).join("")}</tr></thead><tbody>${body
          .map((row) => `<tr>${row.split("|").slice(1, -1).map((c) => `<td>${renderInline(c.trim())}</td>`).join("")}</tr>`)
          .join("")}</tbody></table>`
      );
    }
    table = [];
  };
  lines.forEach((line) => {
    if (line.trim().startsWith("|")) {
      flushList();
      table.push(line);
      return;
    }
    flushTable();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = heading[1].length;
      html.push(`<h${level + 2}>${renderInline(heading[2])}</h${level + 2}>`);
      return;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (bullet || ordered) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) {
        flushList();
        list = { tag, items: [] };
      }
      list.items.push((bullet || ordered)[1]);
      return;
    }
    flushList();
    if (line.trim()) html.push(`<p>${renderInline(line)}</p>`);
  });
  flushList();
  flushTable();
  return html.join("");
}

export function renderMarkdown(raw) {
  const parts = String(raw || "").replace(/\r\n/g, "\n").split("```");
  return parts
    .map((part, index) => {
      if (index % 2 === 0) return renderMarkdownBlocks(part);
      const breakAt = part.indexOf("\n");
      const lang = (breakAt === -1 ? part : part.slice(0, breakAt)).trim().toLowerCase();
      const body = breakAt === -1 ? "" : part.slice(breakAt + 1);
      if (lang === "mermaid") return renderDiagram(body);
      return `<pre class="md-code"><code>${escapeHtml(body)}</code></pre>`;
    })
    .join("");
}

function visibleReply(markdown) {
  const text = String(markdown || "").replace(/\r\n/g, "\n").trim();
  const section = text.match(/^#{1,3}[^\n]*resposta final[^\n]*\n+([\s\S]*?)(?=\n#{1,3}\s|$)/im);
  if (section) {
    const body = section[1].replace(/^---\s*$/gm, "").trim().replace(/^\*\*([\s\S]+)\*\*$/, "$1").trim();
    if (body) return body;
  }
  if (/\n#{1,3}\s*(etapas|verifica|fontes|fluxo|objetivo)\b/i.test(text)) {
    const files = [];
    for (const match of text.matchAll(/^- `([^`]+)`/gm)) {
      const path = match[1];
      if (/^[ab]\//.test(path) || files.includes(path)) continue;
      files.push(path);
    }
    if (files.length) return `O resultado está em ${files.map((path) => `[${path}](${path})`).join(", ")}.`;
    const now = text.match(/^Agora:\s*(.+)$/im);
    if (now) return now[1].replace(/\.$/, "").trim();
  }
  return text;
}

function fileChangeFrom(result) {
  if (!result || typeof result !== "object") return null;
  const write = result.write && typeof result.write === "object" ? result.write : null;
  const inner = result.result && typeof result.result === "object" ? result.result : null;
  const bag = write && typeof write.diff === "string" ? write : inner && typeof inner.diff === "string" ? inner : result;
  if (!bag || typeof bag.diff !== "string" || !bag.diff.trim()) return null;
  const path = String(bag.path || result.path || "").trim();
  if (!path || /^[ab]\//.test(path)) return null;
  return {
    path,
    added: Number(bag.added) || 0,
    removed: Number(bag.removed) || 0,
    diff: bag.diff,
  };
}

function collectChanges(root) {
  const ids = descendantIds(root.id);
  const found = [];
  const seen = new Set();
  for (const task of state.tasks) {
    if (!ids.has(task.id)) continue;
    const item = fileChangeFrom(task.consolidated_result_json);
    if (!item || seen.has(item.path)) continue;
    seen.add(item.path);
    found.push(item);
  }
  return found;
}

function changesHtml(root) {
  const items = collectChanges(root);
  if (!items.length) return "";
  return `<div class="changes">${items
    .map((item) => {
      const open = state.openChangePaths.has(item.path);
      const detail = open ? `<div class="diff">${diffHtml(item.diff)}</div>` : "";
      return `<div class="change${open ? " open" : ""}"><button type="button" class="row" data-change-path="${escapeHtml(item.path)}"><strong>${escapeHtml(item.path)}</strong><span class="counts"><span class="add">+${item.added}</span> <span class="del">−${item.removed}</span></span></button>${detail}</div>`;
    })
    .join("")}</div>`;
}

function referenceLinks(markdown, root) {
  const urls = [];
  const add = (value) => {
    const url = String(value || "").trim().replace(/[),.;]+$/, "");
    if (!/^https?:\/\//i.test(url) || urls.includes(url)) return;
    urls.push(url);
  };
  for (const match of String(markdown || "").matchAll(/https?:\/\/[^\s)<]+/g)) add(match[0]);
  const report = root.consolidated_result_json || {};
  const child = state.tasks.find((task) => task.parent_id === root.id && (task.metadata_json || {}).final_answer);
  for (const source of report.sources || child?.consolidated_result_json?.sources || []) add(source);
  return urls;
}

function refsHtml(markdown, root) {
  const urls = referenceLinks(markdown, root);
  if (!urls.length) return "";
  return `<div class="refs">${urls
    .map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>`)
    .join("")}</div>`;
}

function answerHtml(root) {
  const report = root.consolidated_result_json || {};
  const child = state.tasks.find((task) => task.parent_id === root.id && (task.metadata_json || {}).final_answer);
  const markdown = report.final_answer || child?.consolidated_result_json?.markdown;
  const reply = visibleReply(markdown);
  const changes = changesHtml(root);
  const refs = refsHtml(markdown, root);
  const meters = reply ? stageMetersHtml(root) : "";
  if (!reply && !changes && !refs) return "";
  return `<div class="answer">${reply ? renderMarkdown(reply) : ""}${changes}${refs}${meters}</div>`;
}

function stageMetersHtml(root) {
  const kids = state.tasks.filter((task) => task.parent_id === root.id);
  const bits = kids
    .map((task) => {
      const meter = stageMeter(task);
      return meter ? `<span>${escapeHtml(titleOf(task))} ${meter}</span>` : "";
    })
    .filter(Boolean);
  return bits.length ? `<p class="meters">${bits.join("")}</p>` : "";
}

function titleOf(task) {
  return task.display_title || task.title;
}

function diffHtml(diff) {
  return String(diff)
    .split("\n")
    .map((line) => {
      let kind = "ctx";
      if (line.startsWith("+") && !line.startsWith("+++")) kind = "add";
      else if (line.startsWith("-") && !line.startsWith("---")) kind = "del";
      return `<div class="${kind}">${escapeHtml(line || " ")}</div>`;
    })
    .join("");
}

function stageDetail(task) {
  const result = fileChangeFrom(task.consolidated_result_json) || task.consolidated_result_json?.result || task.consolidated_result_json || {};
  const diff = typeof result.diff === "string" ? result.diff : "";
  const line = resultLine(task);
  const counts = result.added != null ? ` +${result.added} −${result.removed || 0}` : "";
  const path = result.path ? `<p class="stage-path">${escapeHtml(result.path)}${escapeHtml(counts)}</p>` : "";
  const diffBlock = diff ? `<div class="diff">${diffHtml(diff)}</div>` : "";
  const note = line && !diff ? `<p>${escapeHtml(String(line).slice(0, 500))}</p>` : "";
  return `${path}${diffBlock}${note}`;
}

function currentRoot() {
  const inChat = (task) => !task.parent_id && (!state.conversation || task.conversation_id === state.conversation.id);
  return state.tasks.find((task) => task.id === state.selectedTaskId && inChat(task)) || state.tasks.find(inChat);
}

function resumeHtml(root) {
  const brief = state.resumeBrief;
  if (!brief || brief.root_id !== root.id) return "";
  const done = (brief.done || []).map((item) => escapeHtml(item)).join(", ") || "—";
  const missing = (brief.missing || []).map((item) => escapeHtml(item)).join(", ") || "—";
  const fix = brief.corrected_instruction ? `<p>${escapeHtml(brief.corrected_instruction)}</p>` : "";
  const reason = brief.reason ? `<p>Motivo: ${escapeHtml(brief.reason)}</p>` : "";
  const action = brief.can_continue ? `<button type="button" data-continue="${root.id}">Continuar</button>` : "";
  return `<div class="resume"><strong>Parou em ${escapeHtml(brief.stopped_at || "um ponto intermediário")}</strong><p>Feito: ${done}</p><p>Falta: ${missing}</p>${reason}${fix}${action}</div>`;
}

function renderChat() {
  const log = document.getElementById("chat-log");
  if (!log) return;
  const copy = chatCopy();
  const roots = state.tasks.filter(
    (task) => !task.parent_id && (!state.conversation || task.conversation_id === state.conversation.id)
  );
  if (!roots.length) {
    const body = state.conversation && !state.selectedProject
      ? "Esta conversa usa a pasta do usuário. A pasta pode ser trocada quando quiser."
      : copy.emptyBody;
    log.innerHTML = `<div class="chat-empty"><h2>${escapeHtml(copy.emptyTitle)}</h2><p>${escapeHtml(body)}</p></div>`;
    return;
  }
  const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  const model = state.live?.model?.model_id ? ` · ${escapeHtml(state.live.model.model_id)}` : "";
  const busy = ["PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"];
  log.innerHTML = roots
    .map((root) => {
      const kids = state.tasks.filter((task) => task.parent_id === root.id);
      const ids = descendantIds(root.id);
      const focusHere = state.live?.focus && ids.has(state.live.focus.id);
      const glowing =
        busy.includes(root.status) ||
        kids.some((task) => busy.includes(task.status)) ||
        Boolean(state.live?.thinking && focusHere);
      const last = kids[kids.length - 1];
      if (state.followLatest && last) state.openStageIds.add(last.id);
      const cards = kids
        .map((task, index) => {
          const tool = toolOf(task);
          const glyph = TOOL_ICON[tool] || "circle";
          const active = busy.includes(task.status) ? " busy" : "";
          const open = state.openStageIds.has(task.id);
          const detail = open ? stageDetail(task) : "";
          const copies = sameTitleCount(task);
          const same = copies ? `<em class="same">igual ×${copies}</em>` : "";
          return `<div class="tool-card${active}${open ? " open" : ""}"><button type="button" class="row" data-stage="${task.id}" data-last="${index === kids.length - 1 ? "1" : "0"}">${statusBadge(task.status)}${icon(glyph)}<strong>${escapeHtml(titleOf(task))}</strong>${stageMeter(task)}${same}</button>${detail ? `<div class="stage-detail">${detail}</div>` : ""}</div>`;
        })
        .join("");
      const thoughts = thoughtBlock(root);
      const spoken = String(root.objective || "").split("\n\nAnexos do usuário:")[0];
      const chips = ((root.metadata_json || {}).attachments || [])
        .map((item) => `<span class="chip">${escapeHtml(item.name || item.path || "anexo")}</span>`)
        .join("");
      const editing = state.editingTaskId === root.id;
      const message = editing
        ? `<form class="edit-box" data-edit-form="${root.id}"><textarea>${escapeHtml(spoken)}</textarea><button type="submit">Salvar e ramificar</button></form>`
        : `<div>${escapeHtml(spoken)}</div>`;
      const editBtn = `<button type="button" class="icon-btn edit-msg" data-edit="${root.id}" title="Editar mensagem" aria-label="Editar mensagem">${icon("pencil")}</button>`;
      const asked = stampTag(root.created_at);
      const answered = stampTag((last || root).updated_at || root.updated_at);
      const reply = answerHtml(root);
      const pendingLine = glowing && !reply ? `<p class="muted">${escapeHtml(copy.planning)}</p>` : "";
      const process = reply ? "" : `${thoughts}${cards}`;
      return `<div class="bubble user"><div class="who"><span>${copy.you}</span>${asked}${editBtn}</div>${message}${chips ? `<div class="attach-row">${chips}</div>` : ""}</div>
        <div class="bubble agent${glowing ? " live" : ""}"><div class="agent-body"><div class="who"><span>${copy.agent}${model}</span>${answered}${runMeter(root)}</div>${process}${pendingLine}${resumeHtml(root)}${reply}</div></div>`;
    })
    .join("");
  if (stick) log.scrollTop = log.scrollHeight;
}

async function refreshAll() {
  const results = await Promise.allSettled([
    refreshTasks(),
    refreshOverview(),
    refreshActivity(),
    refreshLive(),
  ]);
  renderChat();
  const failed = results.find((r) => r.status === "rejected");
  if (failed) console.warn(failed.reason);
}

function updateRunButtons() {
  const hasProject = Boolean(workspaceId());
  const root = currentRoot();
  const resume = document.getElementById("btn-resume");
  if (resume) {
    const incomplete = Boolean(root && !["COMPLETED", "CANCELLED"].includes(root.status));
    resume.hidden = !incomplete || Boolean(state.live?.thinking);
  }
  const hasRoot = Boolean(root);
  document.getElementById("btn-run").disabled = !hasProject || !hasRoot;
  const runActive = Boolean(state.currentRun);
  document.getElementById("btn-step").disabled = !runActive;
  document.getElementById("btn-execute").disabled = !runActive;
  document.getElementById("btn-pause").disabled = !runActive;
  document.getElementById("btn-cancel-run").disabled = !runActive;
}

function startPolling() {
  stopPolling();
  if (!document.getElementById("poll-active").checked || !state.currentRun) return;
  state.pollTimer = setInterval(async () => {
    try {
      await refreshAll();
      const panel = document.getElementById("details-panel");
      if (state.selectedTaskId && panel && !panel.hidden) await loadInspector(state.selectedTaskId);
    } catch (e) {
      console.warn(e);
    }
  }, 2500);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function loadModels() {
  const sel = document.getElementById("sel-model");
  const prefs = loadPrefs();
  sel.innerHTML = "";
  const provider = document.getElementById("sel-provider").value;
  if (provider === "mock") {
    sel.innerHTML = `<option value="mock-model">mock-model</option>`;
    return;
  }
  const endpoint = provider === "llamacpp" ? "/providers/llamacpp/models" : "/providers/ollama/models";
  const offlineLabel = provider === "llamacpp" ? "llama.cpp offline" : "Ollama offline";
  try {
    const data = await api(endpoint);
    (data.models || []).forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      sel.appendChild(opt);
    });
    if (!sel.options.length) {
      sel.innerHTML = `<option value="${state.uiDefaults?.model_id || "llama3.2"}">${state.uiDefaults?.model_id || "llama3.2"} (fallback)</option>`;
    }
  } catch {
    sel.innerHTML = `<option value="${state.uiDefaults?.model_id || "llama3.2"}">${offlineLabel} — fallback</option>`;
  }
  if (prefs.model_id) sel.value = prefs.model_id;
  const chip = document.getElementById("model-chip");
  if (chip) chip.textContent = sel.selectedOptions[0]?.textContent || sel.value || "modelo";
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
    };
  });
}

function paintBrowser() {
  const chip = document.getElementById("browser-chip");
  if (!chip) return;
  const labels = { off: "Desligado", headless: "Invisível", visible: "Janela" };
  chip.title = `Navegador ${labels[state.browserMode] || "Desligado"}`;
  chip.classList.toggle("on", state.browserMode !== "off");
  const text = chip.querySelector("span");
  if (text) text.textContent = labels[state.browserMode] || "Desligado";
}

async function continueResume(taskId) {
  const brief = await api(`/tasks/${taskId}/resume-brief`, {
    method: "POST",
    body: JSON.stringify({ apply: true }),
  });
  state.resumeBrief = brief;
  if (brief.reactivated_run_id) {
    state.currentRun = { id: brief.reactivated_run_id, status: "active" };
    updateRunButtons();
    startPolling();
    await api(`/runs/${brief.reactivated_run_id}/step`, { method: "POST" });
    await refreshAll();
    return;
  }
  state.selectedTaskId = taskId;
  await document.getElementById("btn-run").onclick();
}

function tickMeters() {
  document.querySelectorAll("time.meter[data-meter-live='1']").forEach((el) => {
    const parts = meterParts(el.dataset.meterStart, el.dataset.meterEnd, el.dataset.meterTokens, true);
    const span = el.querySelector(".span");
    if (parts && span) span.textContent = parts.span;
  });
}

async function init() {
  paintIcons();
  setInterval(tickMeters, 1000);
  setupTabs();
  document.getElementById("chat-log").addEventListener("click", async (event) => {
    const cont = event.target.closest("[data-continue]");
    if (cont) {
      try {
        await continueResume(cont.dataset.continue);
      } catch (err) {
        toast(err.message, "error");
      }
      return;
    }
    const edit = event.target.closest("[data-edit]");
    if (edit) {
      event.preventDefault();
      state.editingTaskId = edit.dataset.edit;
      renderChat();
      return;
    }
    const change = event.target.closest("[data-change-path]");
    if (change) {
      event.preventDefault();
      const path = change.dataset.changePath;
      if (state.openChangePaths.has(path)) state.openChangePaths.delete(path);
      else state.openChangePaths.add(path);
      renderChat();
      return;
    }
    const row = event.target.closest("[data-stage]");
    if (!row) return;
    const id = row.dataset.stage;
    const isLast = row.dataset.last === "1";
    if (state.openStageIds.has(id)) {
      state.openStageIds.delete(id);
      if (isLast) state.followLatest = false;
    } else {
      state.openStageIds.add(id);
      if (isLast) state.followLatest = true;
    }
    renderChat();
  });
  document.getElementById("chat-log").addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-edit-form]");
    if (!form || !state.conversation) return;
    event.preventDefault();
    const taskId = form.dataset.editForm;
    const text = form.querySelector("textarea").value.trim();
    const original = state.tasks.find((task) => task.id === taskId);
    const spoken = String(original?.objective || "").split("\n\nAnexos do usuário:")[0].trim();
    state.editingTaskId = null;
    if (!text || text === spoken) {
      renderChat();
      return;
    }
    try {
      const forked = await api(`/conversations/${state.conversation.id}/fork`, {
        method: "POST",
        body: JSON.stringify({ task_id: taskId, objective: text }),
      });
      applyConversation(forked.conversation);
      state.viewBranchId = forked.conversation.active_branch_id;
      state.selectedTaskId = forked.task.id;
      renderProjects(document.getElementById("project-search").value);
      await refreshTasks();
      document.getElementById("btn-run").click();
    } catch (err) {
      toast(err.message, "error");
      renderChat();
    }
  });
  state.uiDefaults = await api("/config/ui-defaults");
  const health = await api("/health");
  const healthEl = document.getElementById("health-indicator");
  healthEl.innerHTML = icon("check");
  healthEl.title = `API ${health.status} · v${health.version || "?"}`;
  const barHealth = document.getElementById("health-indicator-bar");
  if (barHealth) {
    barHealth.innerHTML = icon("check");
    barHealth.title = healthEl.title;
  }

  const prefs = loadPrefs();
  state.browserMode = prefs.browserMode || "off";
  paintBrowser();
  document.getElementById("browser-menu").addEventListener("click", (event) => {
    const choice = event.target.closest("[data-browser]");
    if (!choice) return;
    state.browserMode = choice.dataset.browser;
    savePrefs({ browserMode: state.browserMode });
    paintBrowser();
    document.getElementById("browser-menu").open = false;
  });
  document.getElementById("btn-resume").onclick = async () => {
    const root = currentRoot();
    if (!root) return;
    try {
      state.resumeBrief = await api(`/tasks/${root.id}/resume-brief`, {
        method: "POST",
        body: JSON.stringify({ apply: false }),
      });
      renderChat();
    } catch (err) {
      toast(err.message, "error");
    }
  };
  if (prefs.provider) document.getElementById("sel-provider").value = prefs.provider;
  document.getElementById("sel-provider").onchange = async () => {
    savePrefs({ provider: document.getElementById("sel-provider").value });
    await loadModels();
  };
  document.getElementById("sel-model").onchange = () => {
    savePrefs({ model_id: document.getElementById("sel-model").value });
    const chip = document.getElementById("model-chip");
    const sel = document.getElementById("sel-model");
    if (chip) chip.textContent = sel.selectedOptions[0]?.textContent || sel.value || "modelo";
  };

  await loadModels();
  state.projects = await api("/projects");
  state.loose = await api("/conversations");
  renderProjects();
  if (!prefs.lastProjectId && prefs.lastConversationId) {
    const loose = state.loose.find((item) => item.id === prefs.lastConversationId);
    if (loose) selectLoose(loose);
  }

  if (prefs.lastProjectId) {
    const p = state.projects.find((x) => x.id === prefs.lastProjectId);
    if (p) await selectProject(p);
  }

  document.getElementById("project-search").oninput = (e) => renderProjects(e.target.value);
  document.getElementById("btn-toggle-project-form").onclick = async () => {
    try {
      const created = await api("/projects", {
        method: "POST",
        body: JSON.stringify({ name: "Projeto", root_path: "" }),
      });
      state.projects = await api("/projects");
      await selectProject(created);
      toast("Projeto na pasta do usuário");
    } catch (err) {
      toast(err.message, "error");
    }
  };
  document.getElementById("btn-new-chat").onclick = () => startConversation().catch((err) => toast(err.message, "error"));
  document.getElementById("btn-loose-chat").onclick = () => startLooseConversation().catch((err) => toast(err.message, "error"));
  document.getElementById("btn-rename").onclick = () => beginRename();
  document.getElementById("btn-folder").onclick = () => {
    if (state.conversation) {
      state.folderTarget = { type: "conversation", id: state.conversation.id };
      openFolderPicker(state.conversation.root_path).catch((err) => toast(err.message, "error"));
      return;
    }
    if (state.selectedProject) {
      state.folderTarget = { type: "project", id: state.selectedProject.id };
      openFolderPicker(state.selectedProject.root_path).catch((err) => toast(err.message, "error"));
    }
  };
  document.getElementById("branch-prev").onclick = () => shiftBranch(-1).catch((err) => toast(err.message, "error"));
  document.getElementById("branch-next").onclick = () => shiftBranch(1).catch((err) => toast(err.message, "error"));
  document.getElementById("folder-close").onclick = () => {
    state.folderTarget = null;
    document.getElementById("folder-modal").hidden = true;
  };
  document.getElementById("folder-up").onclick = () => {
    const parent = document.getElementById("folder-up").dataset.parent;
    if (parent) loadFolder(parent);
  };
  document.getElementById("folder-use").onclick = () => useFolder(state.browsePath).catch((err) => toast(err.message, "error"));
  document.getElementById("folder-native").onclick = async () => {
    try {
      const chosen = await api("/fs/pick-folder", { method: "POST", body: "{}" });
      await useFolder(chosen.path);
    } catch (err) {
      toast(err.message || "Seleção cancelada", "error");
    }
  };
  document.getElementById("folder-modal").onclick = (event) => {
    if (event.target.id === "folder-modal") {
      state.folderTarget = null;
      event.currentTarget.hidden = true;
    }
  };

  document.getElementById("objective-template").onchange = (e) => {
    const key = e.target.value;
    if (!key || key === "custom") return;
    const t = templates[key];
    if (!t) return;
    const form = document.getElementById("form-task");
    form.title.value = t.title;
    form.objective.value = t.objective;
    if (t.rootHint && state.selectedProject) {
      toast(`Use path absoluto terminando em ${E2E_FIXTURE_HINT}`, "info");
    }
  };

  const attachments = [];
  const PASTE_CHARS = 1500;
  const PASTE_LINES = 40;
  const TEXT_NAME = /\.(txt|md|py|json|csv|js|ts|tsx|html|css|xml|yaml|yml|toml|rs|go|java|c|h|cpp|sql|sh)$/i;

  function renderAttachmentChips() {
    const row = document.getElementById("attach-row");
    row.hidden = attachments.length === 0;
    row.innerHTML = attachments
      .map((item, index) => {
        const thumb = item.preview ? `<img alt="" src="${item.preview}" />` : "";
        return `<span class="chip">${thumb}<span>${escapeHtml(item.name)}</span><button type="button" data-remove="${index}" aria-label="Remover ${escapeHtml(item.name)}">×</button></span>`;
      })
      .join("");
  }

  function addAttachment(item) {
    attachments.push(item);
    renderAttachmentChips();
  }

  function fileToAttachment(file) {
    const isImage = (file.type || "").startsWith("image/");
    const isText = (file.type || "").startsWith("text/") || TEXT_NAME.test(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      if (isText) {
        addAttachment({ kind: "text", name: file.name, mime: file.type || "text/plain", content: String(reader.result) });
        return;
      }
      addAttachment({
        kind: isImage ? "image" : "file",
        name: file.name,
        mime: file.type || "application/octet-stream",
        content_base64: String(reader.result),
        preview: isImage ? String(reader.result) : "",
      });
    };
    if (isText) reader.readAsText(file);
    else reader.readAsDataURL(file);
  }

  document.getElementById("attach-row").onclick = (e) => {
    const button = e.target.closest("[data-remove]");
    if (!button) return;
    attachments.splice(Number(button.dataset.remove), 1);
    renderAttachmentChips();
  };
  document.getElementById("btn-attach").onclick = () => document.getElementById("file-attach").click();
  document.getElementById("file-attach").onchange = (e) => {
    [...e.target.files].forEach(fileToAttachment);
    e.target.value = "";
  };

  const composer = document.getElementById("form-task");
  composer.addEventListener("dragover", (e) => {
    e.preventDefault();
    composer.classList.add("dragover");
  });
  composer.addEventListener("dragleave", () => composer.classList.remove("dragover"));
  composer.addEventListener("drop", (e) => {
    e.preventDefault();
    composer.classList.remove("dragover");
    [...(e.dataTransfer?.files || [])].forEach(fileToAttachment);
  });

  const objectiveBox = document.querySelector("#form-task textarea[name=objective]");
  objectiveBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("form-task").requestSubmit();
    }
  });
  objectiveBox.addEventListener("paste", (e) => {
    const data = e.clipboardData;
    if (!data) return;
    const files = [...(data.files || [])];
    if (files.length) {
      e.preventDefault();
      files.forEach(fileToAttachment);
      return;
    }
    const image = [...(data.items || [])].find((item) => item.kind === "file" && item.type.startsWith("image/"));
    if (image) {
      const file = image.getAsFile();
      if (file) {
        e.preventDefault();
        fileToAttachment(file);
        return;
      }
    }
    const text = data.getData("text/plain");
    if (text && (text.length > PASTE_CHARS || text.split("\n").length > PASTE_LINES)) {
      e.preventDefault();
      const n = attachments.filter((item) => item.name.startsWith("texto-colado")).length + 1;
      addAttachment({
        kind: "text",
        name: n === 1 ? "texto-colado.txt" : `texto-colado-${n}.txt`,
        mime: "text/plain",
        content: text,
      });
    }
  });

  document.getElementById("btn-toggle-details").onclick = () => {
    const panel = document.getElementById("details-panel");
    panel.hidden = !panel.hidden;
  };

  document.getElementById("form-task").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    let objective = String(fd.get("objective") || "").trim();
    if (!objective && !attachments.length) return;
    if (!objective) objective = "Use os anexos.";
    const title = String(fd.get("title") || objective).slice(0, 80);
    const metadata = attachments.length
      ? {
          attachments: attachments.map(({ kind, name, mime, content, content_base64 }) => ({
            kind,
            name,
            mime,
            content,
            content_base64,
          })),
        }
      : undefined;
    if (!state.conversation) {
      if (state.selectedProject) {
        state.conversation = await api(`/projects/${state.selectedProject.id}/conversations`, {
          method: "POST",
          body: JSON.stringify({ title }),
        });
        state.conversations = [state.conversation, ...state.conversations];
      } else {
        await startLooseConversation();
      }
    }
    const workspace = workspaceId();
    if (!workspace || !state.conversation) {
      toast("Não foi possível abrir a conversa", "error");
      return;
    }
    let task;
    try {
      task = await api(`/projects/${workspace}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title,
          objective,
          kind: "objective",
          conversation_id: state.conversation.id,
          metadata,
        }),
      });
    } catch (err) {
      toast(err.message || "Falha ao enviar", "error");
      return;
    }
    state.selectedTaskId = task.id;
    state.tasks = [...state.tasks, { ...task, parent_id: task.parent_id || null }];
    if (state.selectedProject) {
      state.conversations = await api(`/projects/${state.selectedProject.id}/conversations`);
      state.conversation = state.conversations.find((item) => item.id === state.conversation.id) || state.conversation;
    } else {
      state.loose = await api("/conversations");
      state.conversation = state.loose.find((item) => item.id === state.conversation.id) || state.conversation;
    }
    paintWorkspace();
    renderProjects(document.getElementById("project-search").value);
    attachments.splice(0, attachments.length);
    renderAttachmentChips();
    e.target.reset();
    renderChat();
    try {
      await startRun();
    } catch (err) {
      toast(err.message || "Falha ao iniciar", "error");
    }
  };

  document.getElementById("task-filter-status").onchange = () => renderTaskTree();

  document.getElementById("btn-run").onclick = () => startRun().catch((err) => toast(err.message, "error"));

  async function startRun() {
    const root = state.tasks.find((t) => t.id === state.selectedTaskId) || state.tasks.find((t) => !t.parent_id);
    const workspace = workspaceId();
    if (!root || !workspace) throw new Error("Não há mensagem para executar");
    const cfg = runConfigFromUI(root.objective || "");
    state.currentRun = await api(`/projects/${workspace}/runs`, {
      method: "POST",
      body: JSON.stringify({ root_task_id: root.id, config: cfg }),
    });
    await api(`/runs/${state.currentRun.id}/autonomous/enable`, { method: "POST" });
    const auto = document.getElementById("chk-autonomous");
    if (auto) auto.checked = true;
    updateRunButtons();
    startPolling();
    toast("Execução iniciada — primeiro passo");
    renderLive({
      action: "started_planning",
      headline: `Começando: ${root.title}`,
      how: "O orquestrador vai planejar e dividir o objetivo.",
      run: { status: "active", autonomous: true },
    });
    const out = await api(`/runs/${state.currentRun.id}/step`, { method: "POST" });
    toast(out.headline || out.action || "Passo dado");
    await refreshAll();
  };

  document.getElementById("btn-step").onclick = async () => {
    if (!state.currentRun) return;
    const out = await api(`/runs/${state.currentRun.id}/step`, { method: "POST" });
    toast(`Passo: ${out.action}`);
    await refreshAll();
    if (state.selectedTaskId) await loadInspector(state.selectedTaskId);
  };

  document.getElementById("btn-execute").onclick = async () => {
    if (!state.currentRun) return;
    const out = await api(`/runs/${state.currentRun.id}/execute?max_steps=80`, { method: "POST" });
    toast(`Auto: ${out.steps} passos`);
    await refreshAll();
    if (state.selectedTaskId) await loadInspector(state.selectedTaskId);
  };

  document.getElementById("btn-pause").onclick = async () => {
    if (!state.currentRun) return;
    await api(`/runs/${state.currentRun.id}/pause`, { method: "POST" });
    toast("Execução pausada");
    stopPolling();
  };

  document.getElementById("btn-cancel-run").onclick = async () => {
    if (!state.currentRun) return;
    await api(`/runs/${state.currentRun.id}/cancel`, { method: "POST" });
    state.currentRun = null;
    stopPolling();
    updateRunButtons();
    toast("Execução cancelada");
    await refreshAll();
  };

  document.getElementById("poll-active").onchange = () => {
    if (document.getElementById("poll-active").checked) startPolling();
    else stopPolling();
  };

  document.getElementById("btn-refresh-all").onclick = () => refreshAll().catch((e) => toast(e.message, "error"));
  document.getElementById("btn-refresh-diff").onclick = async () => {
    if (!state.selectedProject) return;
    const diff = await api(`/projects/${state.selectedProject.id}/git-diff`);
    document.getElementById("diff-view").textContent = diff.stdout || diff.stderr || JSON.stringify(diff, null, 2);
  };

  document.getElementById("btn-refresh-metrics").onclick = async () => {
    if (!state.selectedProject) return;
    const m = await api(`/projects/${state.selectedProject.id}/metrics`);
    document.getElementById("metrics-view").textContent = JSON.stringify(m, null, 2);
  };

  document.getElementById("btn-kg-reindex").onclick = async () => {
    if (!state.selectedProject) return;
    const r = await api(`/projects/${state.selectedProject.id}/knowledge/reindex`, { method: "POST" });
    toast(`Grafo: ${r.nodes} nós, ${r.edges} arestas`);
    document.getElementById("graph-view").textContent = JSON.stringify(r, null, 2);
  };

  document.getElementById("kg-search").onkeydown = async (e) => {
    if (e.key !== "Enter" || !state.selectedProject) return;
    const q = e.target.value.trim();
    if (!q) return;
    const r = await api(
      `/projects/${state.selectedProject.id}/knowledge/search?q=${encodeURIComponent(q)}`
    );
    document.getElementById("graph-view").textContent = JSON.stringify(r, null, 2);
  };

  document.getElementById("btn-mcp-discover").onclick = async () => {
    try {
      const r = await api("/mcp/discover", { method: "POST" });
      toast(`MCP: ${r.discovered} ferramentas`);
    } catch (e) {
      toast(e.message, "error");
    }
  };

  try {
    const tools = await api("/tools");
    document.getElementById("tools-view").textContent = JSON.stringify(tools, null, 2);
  } catch {
    /* ignore */
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") document.getElementById("btn-execute").click();
    if (e.ctrlKey && e.key === ".") document.getElementById("btn-step").click();
  });
}

init().catch((e) => toast(e.message, "error"));
