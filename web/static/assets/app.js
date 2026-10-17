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
  selectedProject: null,
  tasks: [],
  selectedTaskId: null,
  currentRun: null,
  uiDefaults: null,
  pollTimer: null,
};

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
};

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
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
  };
}

function renderProjects(filter = "") {
  const ul = document.getElementById("project-list");
  ul.innerHTML = "";
  const q = filter.trim().toLowerCase();
  state.projects
    .filter((p) => !q || p.name.toLowerCase().includes(q) || p.root_path.toLowerCase().includes(q))
    .forEach((p) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      if (state.selectedProject?.id === p.id) btn.classList.add("active");
      btn.innerHTML = `<span>${escapeHtml(p.name)}</span><span class="path">${escapeHtml(p.root_path)}</span>`;
      btn.onclick = () => selectProject(p);
      li.appendChild(btn);
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
  document.getElementById("workspace-title").textContent = p.name;
  document.getElementById("workspace-subtitle").textContent = p.root_path;
  document.getElementById("run-toolbar").hidden = false;
  renderProjects(document.getElementById("project-search").value);
  await refreshAll();
  updateRunButtons();
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
  const nodes = buildTreeNodes(state.tasks);
  if (!nodes.length) {
    container.innerHTML = `<p class="muted">Nenhuma tarefa. Crie um objetivo acima.</p>`;
    return;
  }
  nodes.forEach(({ task, depth }) => {
    const div = document.createElement("div");
    const busy = ["RUNNING", "VERIFYING", "PLANNING"].includes(task.status) ? " busy" : "";
    div.className = `tree-node${task.id === state.selectedTaskId ? " selected" : ""}${busy}`;
    div.setAttribute("role", "treeitem");
    div.innerHTML = `<span class="indent" style="width:${depth * 12}px"></span>${statusBadge(task.status)} <span>${escapeHtml(task.title)}</span>`;
    div.onclick = () => selectTask(task.id);
    container.appendChild(div);
  });
  if (!state.selectedTaskId && state.tasks.length) {
    const root = state.tasks.find((t) => !t.parent_id) || state.tasks[0];
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
  if (!state.selectedProject) return;
  const ov = await api(`/projects/${state.selectedProject.id}/overview`);
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
  if (!state.selectedProject) return;
  state.tasks = await api(`/projects/${state.selectedProject.id}/tasks`);
  renderTaskTree();
  renderChat();
}

const ACTION_PT = {
  started_planning: "Começou a planejar",
  decomposed: "Dividiu em subtarefas",
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
  if (!state.selectedProject) return;
  const events = await api(`/projects/${state.selectedProject.id}/events`);
  const ul = document.getElementById("activity-feed");
  ul.innerHTML = "";
  events.slice(0, 40).forEach((ev) => {
    const li = document.createElement("li");
    li.innerHTML = `<time>${formatTime(ev.created_at)}</time><span>${icon("circle")}${escapeHtml(eventLabel(ev))}</span>`;
    ul.appendChild(li);
  });
}

async function refreshLive() {
  if (!state.selectedProject) return;
  const live = await api(`/projects/${state.selectedProject.id}/live`);
  state.live = live;
  renderLive(live);
  if (live.run && !state.currentRun) {
    state.currentRun = { id: live.run.id, status: live.run.status };
    updateRunButtons();
  }
}

function thoughtBlock(root) {
  const live = state.live;
  if (!live) return "";
  const focusHere = !live.focus || live.focus.id === root.id || state.tasks.some((t) => t.id === live.focus.id && t.parent_id === root.id);
  if (!focusHere && state.tasks.filter((t) => !t.parent_id).length > 1) return "";
  const noisy = /^(Planejando|Pronta para executar|Concluída sem teste|Liberada|Aguardando|Começando)/;
  const lines = (live.thoughts || []).filter((item) => item.phase !== "step" || !noisy.test(item.text || ""));
  if (!lines.length && !live.thinking) return "";
  const open = live.thinking ? " open" : "";
  const items = lines
    .map((item) => {
      const glyph = item.phase === "thinking" || item.phase === "model" ? "spark" : item.phase === "tool" ? "terminal" : "check";
      return `<li class="${escapeHtml(item.phase || "step")}">${icon(glyph)}<span>${escapeHtml(item.text || "")}</span></li>`;
    })
    .join("");
  const pending = live.thinking ? `<li class="thinking">${icon("spark")}<span>Pensando…</span></li>` : "";
  const label = live.thinking ? "Pensando" : "Pensou";
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

function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
      if (!/^(https?:|\/|\.\/|\.\.\/)/.test(href)) return label;
      return `<a href="${href}" rel="noreferrer">${label}</a>`;
    });
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

function answerHtml(root) {
  const report = root.consolidated_result_json || {};
  const child = state.tasks.find((task) => task.parent_id === root.id && (task.metadata_json || {}).final_answer);
  const markdown = report.final_answer || child?.consolidated_result_json?.markdown;
  if (!markdown) return "";
  return `<div class="answer">${renderMarkdown(markdown)}</div>`;
}

function renderChat() {
  const log = document.getElementById("chat-log");
  if (!log) return;
  const roots = state.tasks.filter((t) => !t.parent_id);
  if (!state.selectedProject || !roots.length) {
    log.innerHTML = `<div class="chat-empty"><h2>O que vamos construir?</h2><p>Escreva embaixo como no chat do Cursor. O agente divide o trabalho, edita os arquivos e mostra cada passo aqui.</p></div>`;
    return;
  }
  const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  const model = state.live?.model?.model_id ? ` · ${escapeHtml(state.live.model.model_id)}` : "";
  log.innerHTML = roots
    .map((root) => {
      const kids = state.tasks.filter((t) => t.parent_id === root.id);
      const cards = kids
        .map((k) => {
          const line = resultLine(k);
          const tool = toolOf(k);
          const glyph = TOOL_ICON[tool] || "circle";
          return `<div class="tool-card"><div class="row">${statusBadge(k.status)}${icon(glyph)}<strong>${escapeHtml(k.title)}</strong></div>${line ? `<p>${escapeHtml(line.slice(0, 220))}</p>` : ""}</div>`;
        })
        .join("");
      const thoughts = thoughtBlock(root);
      const spoken = String(root.objective || "").split("\n\nAnexos do usuário:")[0];
      const chips = ((root.metadata_json || {}).attachments || [])
        .map((a) => `<span class="chip">${escapeHtml(a.name || a.path || "anexo")}</span>`)
        .join("");
      return `<div class="bubble user"><div class="who">Você</div><div>${escapeHtml(spoken)}</div>${chips ? `<div class="attach-row">${chips}</div>` : ""}</div>
        <div class="bubble agent"><div class="who">Agente${model}</div>${thoughts}${cards || (thoughts ? "" : `<p class="muted">Vou planejar e dividir isso em passos.</p>`)}${answerHtml(root)}</div>`;
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
  const hasProject = Boolean(state.selectedProject);
  const root = state.tasks.find((t) => t.id === state.selectedTaskId) || state.tasks.find((t) => !t.parent_id);
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

async function init() {
  paintIcons();
  setupTabs();
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
  if (prefs.provider) document.getElementById("sel-provider").value = prefs.provider;
  document.getElementById("sel-provider").onchange = async () => {
    savePrefs({ provider: document.getElementById("sel-provider").value });
    await loadModels();
  };
  document.getElementById("sel-model").onchange = () => savePrefs({ model_id: document.getElementById("sel-model").value });

  await loadModels();
  state.projects = await api("/projects");
  renderProjects();

  if (prefs.lastProjectId) {
    const p = state.projects.find((x) => x.id === prefs.lastProjectId);
    if (p) await selectProject(p);
  }

  document.getElementById("project-search").oninput = (e) => renderProjects(e.target.value);
  document.getElementById("btn-toggle-project-form").onclick = () =>
    document.getElementById("form-project").classList.toggle("collapsed");

  document.getElementById("form-project").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await api("/projects", {
      method: "POST",
      body: JSON.stringify({ name: fd.get("name"), root_path: fd.get("root_path") }),
    });
    e.target.reset();
    document.getElementById("form-project").classList.add("collapsed");
    state.projects = await api("/projects");
    renderProjects();
    toast("Projeto criado");
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
    if (!state.selectedProject) return toast("Escolha um projeto na lateral", "error");
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
    let task;
    try {
      task = await api(`/projects/${state.selectedProject.id}/tasks`, {
        method: "POST",
        body: JSON.stringify({ title, objective, kind: "objective", metadata }),
      });
    } catch (err) {
      toast(err.message || "Falha ao enviar", "error");
      return;
    }
    state.selectedTaskId = task.id;
    state.tasks = [...state.tasks, { ...task, parent_id: null }];
    attachments.splice(0, attachments.length);
    renderAttachmentChips();
    e.target.reset();
    renderChat();
    document.getElementById("btn-run").click();
  };

  document.getElementById("task-filter-status").onchange = () => renderTaskTree();

  document.getElementById("btn-run").onclick = async () => {
    const root = state.tasks.find((t) => t.id === state.selectedTaskId) || state.tasks.find((t) => !t.parent_id);
    if (!root) return;
    const cfg = runConfigFromUI(root.objective || "");
    state.currentRun = await api(`/projects/${state.selectedProject.id}/runs`, {
      method: "POST",
      body: JSON.stringify({ root_task_id: root.id, config: cfg }),
    });
    await api(`/runs/${state.currentRun.id}/autonomous/enable`, { method: "POST" });
    document.getElementById("chk-autonomous").checked = true;
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
