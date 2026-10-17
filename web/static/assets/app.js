const api = (path, opts = {}) =>
  fetch(path, { headers: { "Content-Type": "application/json" }, ...opts }).then(async (r) => {
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  });

let selectedProject = null;
let selectedTask = null;
let currentRun = null;

function renderProjects(projects) {
  const ul = document.getElementById("project-list");
  ul.innerHTML = "";
  projects.forEach((p) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.textContent = `${p.name} (${p.root_path})`;
    btn.onclick = () => selectProject(p);
    li.appendChild(btn);
    ul.appendChild(li);
  });
}

async function selectProject(p) {
  selectedProject = p;
  selectedTask = null;
  currentRun = null;
  document.getElementById("run-status").textContent = `Projeto: ${p.name}`;
  await refreshTasks();
  await refreshEvents();
  updateButtons();
}

function buildTree(tasks, parentId = null, depth = 0) {
  return tasks
    .filter((t) => t.parent_id === parentId)
    .map((t) => {
      const pad = "  ".repeat(depth);
      const line = `${pad}• ${t.title} [${t.status}]`;
      return line + "\n" + buildTree(tasks, t.id, depth + 1);
    })
    .join("");
}

async function refreshTasks() {
  if (!selectedProject) return;
  const tasks = await api(`/projects/${selectedProject.id}/tasks`);
  document.getElementById("task-tree").textContent = buildTree(tasks) || "(sem tarefas)";
  if (!selectedTask && tasks.length) selectedTask = tasks.find((t) => !t.parent_id) || tasks[0];
}

async function refreshEvents() {
  if (!selectedProject) return;
  const events = await api(`/projects/${selectedProject.id}/events`);
  document.getElementById("events").textContent = JSON.stringify(events.slice(0, 30), null, 2);
}

function updateButtons() {
  const ok = Boolean(selectedProject && selectedTask);
  document.getElementById("btn-run").disabled = !ok;
  document.getElementById("btn-step").disabled = !currentRun;
  document.getElementById("btn-execute").disabled = !currentRun;
}

document.getElementById("form-project").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api("/projects", {
    method: "POST",
    body: JSON.stringify({ name: fd.get("name"), root_path: fd.get("root_path") }),
  });
  e.target.reset();
  renderProjects(await api("/projects"));
};

document.getElementById("form-task").onsubmit = async (e) => {
  e.preventDefault();
  if (!selectedProject) return alert("Selecione um projeto");
  const fd = new FormData(e.target);
  const task = await api(`/projects/${selectedProject.id}/tasks`, {
    method: "POST",
    body: JSON.stringify({ title: fd.get("title"), objective: fd.get("objective"), kind: "objective" }),
  });
  selectedTask = task;
  e.target.reset();
  await refreshTasks();
  updateButtons();
};

document.getElementById("btn-run").onclick = async () => {
  if (!selectedProject || !selectedTask) return;
  const objective = (selectedTask.objective || "").toLowerCase();
  const demoE2e = objective.includes("e2e");
  currentRun = await api(`/projects/${selectedProject.id}/runs`, {
    method: "POST",
    body: JSON.stringify({
      root_task_id: selectedTask.id,
      config: demoE2e
        ? { provider: "mock", approve_risky_tools: true }
        : {
            provider: "ollama",
            model_id: "llama3.2",
            approve_risky_tools: true,
            use_generic_template: true,
          },
    }),
  });
  document.getElementById("run-status").textContent = `Run ${currentRun.id} (${currentRun.status})`;
  updateButtons();
};

document.getElementById("btn-step").onclick = async () => {
  if (!currentRun) return;
  const out = await api(`/runs/${currentRun.id}/step`, { method: "POST" });
  document.getElementById("run-status").textContent = JSON.stringify(out);
  await refreshTasks();
  await refreshEvents();
};

document.getElementById("btn-execute").onclick = async () => {
  if (!currentRun) return;
  const out = await api(`/runs/${currentRun.id}/execute?max_steps=80`, { method: "POST" });
  document.getElementById("run-status").textContent = `Passos: ${out.steps}`;
  await refreshTasks();
  await refreshEvents();
};

(async function init() {
  renderProjects(await api("/projects"));
})();
