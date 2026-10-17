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

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

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
  document.getElementById("stats-bar").hidden = false;
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
  if (!state.selectedProject) {
    board.hidden = true;
    return;
  }
  board.hidden = false;
  const action = live?.action || "idle";
  board.classList.remove("busy", "ok", "bad");
  if (["run_completed"].includes(action)) board.classList.add("ok");
  else if (String(action).startsWith("blocked") || action === "verify_failed" || action === "global_verify_failed") board.classList.add("bad");
  else if (live?.run || ["RUNNING", "VERIFYING", "PLANNING"].includes(live?.focus?.status)) board.classList.add("busy");
  const model = live?.model?.model_id || state.uiDefaults?.model_id || "—";
  const provider = live?.model?.provider || document.getElementById("sel-provider")?.value || "—";
  const tool = live?.operation?.tool || "—";
  document.getElementById("live-kicker").textContent = live?.run
    ? `Agente · ${provider} · ${live.run.status}`
    : "Agente";
  document.getElementById("live-title").textContent = live?.headline || "Aguardando uma execução";
  document.getElementById("live-how").textContent = live?.how || "";
  const meta = document.getElementById("live-meta");
  if (meta) {
    meta.innerHTML = `<strong>${escapeHtml(model)}</strong><span>${escapeHtml(provider)} · ${escapeHtml(tool)}</span>`;
  }
  const statusAction = document.getElementById("status-action");
  const statusModel = document.getElementById("status-model");
  const statusTool = document.getElementById("status-tool");
  if (statusAction) statusAction.textContent = live?.headline || "parado";
  if (statusModel) statusModel.textContent = `${provider} · ${model}`;
  if (statusTool) statusTool.textContent = tool === "—" ? "sem ferramenta" : tool;
}

async function refreshActivity() {
  if (!state.selectedProject) return;
  const events = await api(`/projects/${state.selectedProject.id}/events`);
  const ul = document.getElementById("activity-feed");
  ul.innerHTML = "";
  events.slice(0, 40).forEach((ev) => {
    const li = document.createElement("li");
    li.innerHTML = `<time>${formatTime(ev.created_at)}</time><span><strong>${escapeHtml(ev.event_type)}</strong> — ${escapeHtml(eventLabel(ev))}</span>`;
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
  if (inner.path) return String(inner.path);
  return "";
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
          return `<div class="tool-card"><div class="row">${statusBadge(k.status)} <strong>${escapeHtml(k.title)}</strong>${tool ? ` <span class="muted">${escapeHtml(tool)}</span>` : ""}</div>${line ? `<p>${escapeHtml(line.slice(0, 320))}</p>` : ""}</div>`;
        })
        .join("");
      const live =
        state.live?.headline && state.live.action !== "run_completed"
          ? `<div class="tool-card"><div class="row"><strong>${escapeHtml(state.live.headline)}</strong></div><p>${escapeHtml(state.live.how || "")}</p></div>`
          : "";
      return `<div class="bubble user"><div class="who">Você</div><div>${escapeHtml(root.objective)}</div></div>
        <div class="bubble agent"><div class="who">Agente${model}</div>${cards || `<p class="muted">Vou planejar e dividir isso em passos.</p>`}${live}</div>`;
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
      if (state.selectedTaskId) await loadInspector(state.selectedTaskId);
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
  try {
    const data = await api("/providers/ollama/models");
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
    sel.innerHTML = `<option value="${state.uiDefaults?.model_id || "llama3.2"}">Ollama offline — fallback</option>`;
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
  setupTabs();
  state.uiDefaults = await api("/config/ui-defaults");
  const health = await api("/health");
  document.getElementById("health-indicator").textContent = `API ${health.status} · v${health.version || "?"}`;
  const barHealth = document.getElementById("health-indicator-bar");
  if (barHealth) barHealth.textContent = `API ${health.status}`;

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

  const objectiveBox = document.querySelector("#form-task textarea[name=objective]");
  objectiveBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("form-task").requestSubmit();
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
    const objective = String(fd.get("objective") || "").trim();
    if (!objective) return;
    const title = String(fd.get("title") || objective).slice(0, 80);
    const task = await api(`/projects/${state.selectedProject.id}/tasks`, {
      method: "POST",
      body: JSON.stringify({ title, objective, kind: "objective" }),
    });
    state.selectedTaskId = task.id;
    state.tasks = [...state.tasks, { ...task, parent_id: null }];
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
