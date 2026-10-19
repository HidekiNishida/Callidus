/** HTML das áreas de acompanhamento, a partir do estado de `observe-core.js`. Puro: recebe estado e opções,
 * devolve strings já escapadas. */
import {
  CATEGORIES,
  STATUS_LABEL,
  buildTree,
  countsText,
  currentTask,
  describe,
  elapsedSeconds,
  filesList,
  latency,
  outputsList,
  parseTs,
  progressText,
  terminalList,
  toolList,
  verificationList,
  visibleEvents,
} from "./live-state.js";

export function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const MODE_LABEL = {
  live: "ao vivo",
  idle: "parada (sem passo rodando)",
  interrupted: "interrompida",
  paused: "pausada",
  replay: "reexibição do histórico",
};
const CONNECTION_LABEL = {
  connecting: "conectando…",
  live: "conectado",
  reconnecting: "reconectando…",
  ended: "transmissão encerrada",
  closed: "desconectado",
  replay: "sem transmissão (run encerrada)",
};
const OUTPUT_STATUS = {
  waiting: "aguardando",
  waiting_first_token: "aguardando o primeiro trecho",
  waiting_full_response: "aguardando a resposta inteira (provedor sem streaming)",
  streaming: "transmitindo",
  completed: "concluída",
  failed: "falhou",
  cancelled: "cancelada",
  interrupted: "interrompida",
  unknown: "início fora da janela carregada",
};
const RUN_LABEL = { active: "ativa", paused: "pausada", completed: "concluída", failed: "falhou", cancelled: "cancelada" };
const OP_STATUS = { running: "rodando", ok: "ok", failed: "falhou", interrupted: "interrompida" };
const CATEGORY_LABEL = { run: "Execução", plan: "Plano", task: "Tarefas", agent: "Modelo", tool: "Ferramentas", command: "Comandos", file: "Arquivos", test: "Testes", verification: "Verificação" };

function clock(iso) {
  if (!iso) return "";
  const d = new Date(parseTs(iso));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function duration(seconds) {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}m` : m ? `${m}m${String(r).padStart(2, "0")}s` : `${r}s`;
}

function taskTitle(state, id) {
  return id ? state.tasks.get(id)?.title || "" : "";
}

function statusBadge(status, interrupted = false) {
  if (interrupted) return `<span class="obs-badge obs-interrupted">interrompida</span>`;
  return `<span class="obs-badge obs-${esc(status)}">${esc(STATUS_LABEL[status] || status || "—")}</span>`;
}

export function renderHeader(state, now = Date.now()) {
  const h = state.header;
  const current = currentTask(state);
  const lat = latency(state);
  const resumed = h.resumed_at ? `<span title="Última retomada">retomada às ${esc(clock(h.resumed_at))}</span>` : "";
  const truncated = state.eventsTruncated ? `<span class="muted">histórico antigo não carregado</span>` : "";
  return `
    <div class="obs-head-main">
      <strong class="obs-objective" title="${esc(h.objective || "")}">${esc(h.title || h.objective || "Execução")}</strong>
      <span class="obs-badge obs-run-${esc(h.status)}">${esc(RUN_LABEL[h.status] || h.status || "—")}</span>
      <span class="obs-mode obs-mode-${esc(h.mode)}">${esc(MODE_LABEL[h.mode] || h.mode || "")}</span>
    </div>
    <div class="obs-head-meta">
      <span title="Tempo decorrido">${esc(duration(elapsedSeconds(state, now)))}</span>
      <span title="Progresso calculado pelo servidor">${esc(progressText(h.progress))}</span>
      <span title="Tarefa atual">${current ? `agora: ${esc(current.title)}` : "nenhuma tarefa em andamento"}</span>
      <span class="obs-conn obs-conn-${esc(state.connection)}">${esc(CONNECTION_LABEL[state.connection] || state.connection)}</span>
      ${state.lastActivity ? `<span title="Último evento recebido">última atividade às ${esc(clock(state.lastActivity))}</span>` : ""}
      ${lat ? `<span title="Atraso entre o fato e a chegada aqui (média · máximo)">atraso ${lat.avg} · ${lat.max} ms</span>` : ""}
      ${resumed}${truncated}
    </div>`;
}

export function renderFilters(state, filters) {
  const cats = CATEGORIES.map((c) => {
    const on = !filters.categories.size || filters.categories.has(c);
    return `<button type="button" class="obs-chip${on ? " on" : ""}" data-obs-cat="${c}">${esc(CATEGORY_LABEL[c])}</button>`;
  }).join("");
  const task = filters.taskId ? `<button type="button" class="obs-chip on" data-obs-clear-task title="Mostrar todas">tarefa: ${esc(taskTitle(state, filters.taskId))} ×</button>` : "";
  return `${cats}
    <button type="button" class="obs-chip${filters.errorsOnly ? " on" : ""}" data-obs-errors>Só falhas</button>
    ${task}
    <input type="search" class="obs-search" data-obs-text placeholder="Filtrar texto…" value="${esc(filters.text || "")}" />`;
}

function treeNode(state, node, opts) {
  const t = node.task;
  const open = opts.expanded.has(t.id) || (!opts.collapsed.has(t.id) && node.depth < 1);
  const hasKids = node.children.length > 0;
  const twisty = hasKids ? `<button type="button" class="obs-twisty${open ? " open" : ""}" data-obs-toggle="${esc(t.id)}" aria-label="${open ? "Recolher" : "Expandir"}">▸</button>` : `<span class="obs-twisty-pad"></span>`;
  const progress = hasKids ? `<span class="obs-count" title="Folhas concluídas">${node.done}/${node.total}</span>` : "";
  const attempts = t.attempts > 1 ? `<span class="obs-count" title="Tentativas">${t.attempts}×</span>` : "";
  const ev = t.evidence ? `<span class="obs-ev ${t.evidence.passed ? "ok" : t.evidence.passed === false ? "bad" : ""}" title="${esc(t.evidence.summary || "")}">${t.evidence.passed ? "✓" : t.evidence.passed === false ? "✗" : "?"}</span>` : "";
  const reason = t.blocked_reason || t.last_failure?.detail;
  const selected = opts.selected === t.id ? " selected" : "";
  const row = `<div class="obs-node${selected}" role="treeitem" aria-expanded="${hasKids ? open : ""}" data-obs-task="${esc(t.id)}" style="--depth:${node.depth}">
      ${twisty}${statusBadge(t.status, t.interrupted)}<span class="obs-node-title">${esc(t.title)}</span>${progress}${attempts}${ev}
    </div>${reason && (t.status === "BLOCKED" || t.status === "FAILED") ? `<div class="obs-node-reason" style="--depth:${node.depth}">${esc(reason)}</div>` : ""}`;
  const kids = hasKids && open ? node.children.map((k) => treeNode(state, k, opts)).join("") : "";
  return row + kids;
}

export function renderTree(state, opts) {
  const roots = buildTree(state);
  if (!roots.length) return `<p class="muted">Sem tarefas.</p>`;
  return roots.map((n) => treeNode(state, n, opts)).join("");
}

export function renderTaskHistory(state, taskId) {
  const task = state.tasks.get(taskId);
  if (!task) return "";
  const bySeq = new Map(state.events.map((e) => [e.seq, e]));
  const items = task.history.map((s) => bySeq.get(s)).filter(Boolean).slice(-40).reverse();
  if (!items.length) return `<p class="muted">Sem eventos desta tarefa na janela carregada.</p>`;
  return `<ol class="obs-history">${items.map((e) => `<li><time>${esc(clock(e.ts))}</time> ${esc(describe(e))}</li>`).join("")}</ol>`;
}

export function renderActivity(state, filters, limit = 200) {
  const items = visibleEvents(state, filters, limit);
  if (!items.length) return `<li class="muted">Nada para mostrar com esses filtros.</li>`;
  return items
    .map((e) => {
      const bad = /\.(failed|blocked)$/.test(e.type) ? " bad" : /\.(completed|passed)$/.test(e.type) ? " ok" : "";
      const task = e.task_id ? `<span class="obs-task-ref" data-obs-task="${esc(e.task_id)}">${esc(taskTitle(state, e.task_id))}</span>` : "";
      return `<li class="obs-ev-${esc(e.type.split(".")[0])}${bad}"><time>${esc(clock(e.ts))}</time><span class="obs-seq">#${e.seq}</span><span>${esc(describe(e))}</span>${task}</li>`;
    })
    .join("");
}

export function renderOutputs(state, filters) {
  const items = outputsList(state, filters).slice(-12).reverse();
  if (!items.length) return `<p class="muted">Nenhuma chamada ao modelo nesta janela.</p>`;
  return items
    .map((o) => {
      const live = o.status === "streaming" || o.status.startsWith("waiting");
      const meta = [o.purpose, o.provider && `${o.provider} · ${o.model}`, o.streaming === false ? "sem streaming" : null, o.duration_ms != null ? `${o.duration_ms} ms` : null]
        .filter(Boolean)
        .join(" · ");
      const gap = o.gap ? `<p class="obs-warn">Trechos perdidos na reconexão; o texto completo chega ao final.</p>` : "";
      const error = o.error ? `<p class="obs-bad">${esc(o.error)}</p>` : "";
      const body = o.text ? `<pre class="obs-text">${esc(o.text)}${live ? '<span class="obs-caret"></span>' : ""}</pre>` : live ? `<p class="muted">${esc(OUTPUT_STATUS[o.status] || o.status)}…</p>` : "";
      return `<article class="obs-output obs-out-${esc(o.status)}" data-obs-output="${esc(o.output_id)}">
        <header>${live ? '<i class="spin"></i>' : ""}<strong>${esc(OUTPUT_STATUS[o.status] || o.status)}</strong><span class="muted">${esc(meta)}</span><span class="obs-task-ref" data-obs-task="${esc(o.task_id || "")}">${esc(taskTitle(state, o.task_id))}</span></header>
        ${gap}${body}${error}</article>`;
    })
    .join("");
}

export function renderTerminal(state, filters) {
  const items = terminalList(state, filters).slice(-15).reverse();
  if (!items.length) return `<p class="muted">Nenhum comando ou teste nesta janela.</p>`;
  return items
    .map((op) => {
      const meta = [op.exit_code != null ? `código ${op.exit_code}` : null, op.duration_ms != null ? `${op.duration_ms} ms` : null, op.counts ? countsText(op.counts) : null]
        .filter(Boolean)
        .join(" · ");
      return `<article class="obs-op obs-op-${esc(op.status)}">
        <header>${op.status === "running" ? '<i class="spin"></i>' : ""}<code>$ ${esc(op.command || op.tool || op.kind)}</code><span class="obs-badge obs-op-badge-${esc(op.status)}">${esc(OP_STATUS[op.status] || op.status)}</span><span class="muted">${esc(meta)}</span></header>
        ${op.output ? `<pre class="obs-term">${esc(op.output)}</pre>` : ""}
        ${op.error && op.status !== "ok" ? `<p class="obs-bad">${esc(op.error)}</p>` : ""}
      </article>`;
    })
    .join("");
}

export function summaryText(summary) {
  if (summary == null) return "";
  if (typeof summary !== "object") return String(summary);
  return Object.entries(summary)
    .filter(([, v]) => v !== null && v !== undefined && v !== false && typeof v !== "object")
    .map(([k, v]) => (v === true ? k : `${k} ${v}`))
    .join(" · ");
}

export function renderTools(state, filters) {
  const items = toolList(state, filters).slice(-30).reverse();
  if (!items.length) return "";
  return `<ul class="obs-tools">${items
    .map((op) => `<li class="obs-op-${esc(op.status)}"><span class="obs-badge obs-op-badge-${esc(op.status)}">${esc(OP_STATUS[op.status] || op.status)}</span><code>${esc(op.tool)}</code><span class="muted">${esc(op.error || summaryText(op.summary))}${op.executed === false ? " · não executada" : ""}</span></li>`)
    .join("")}</ul>`;
}

export function renderFiles(state, filters, openSeqs) {
  const items = filesList(state, filters).slice(-60).reverse();
  if (!items.length) return `<p class="muted">Nenhum arquivo criado, alterado ou removido.</p>`;
  return items
    .map((f) => {
      const verb = { "file.created": "criado", "file.changed": "alterado", "file.deleted": "removido" }[f.type] || f.type;
      const stats = f.added != null ? `<span class="obs-add">+${f.added}</span><span class="obs-del">−${f.removed}</span>` : "";
      const open = openSeqs.has(f.seq);
      const diff = f.sensitive
        ? `<p class="muted">Arquivo sensível: conteúdo não transmitido.</p>`
        : f.diff
          ? `<pre class="obs-diff">${f.diff.split("\n").map((l) => `<span class="${l.startsWith("+") ? "obs-add" : l.startsWith("-") ? "obs-del" : l.startsWith("@@") ? "obs-hunk" : ""}">${esc(l)}</span>`).join("\n")}</pre>${f.truncated ? `<p class="muted">diff cortado</p>` : ""}`
          : "";
      const toggle = diff ? `<button type="button" class="obs-link" data-obs-file="${f.seq}">${open ? "esconder" : "ver diff"}</button>` : "";
      return `<div class="obs-file"><div class="obs-file-row"><code>${esc(f.path)}</code><span class="obs-badge">${esc(verb)}</span>${stats}${toggle}<time>${esc(clock(f.ts))}</time></div>${open ? diff : ""}</div>`;
    })
    .join("");
}

export function renderVerification(state, filters) {
  const items = verificationList(state, filters).slice(-30).reverse();
  if (!items.length) return `<p class="muted">Nenhuma verificação ou teste ainda.</p>`;
  const label = { started: "rodando", passed: "aprovada", failed: "reprovada", inconclusive: "sem veredito", interrupted: "interrompida" };
  return `<ul class="obs-verif">${items
    .map((v) => `<li class="obs-v-${esc(v.status)}"><span class="obs-badge obs-v-badge-${esc(v.status)}">${esc(label[v.status] || v.status)}</span><strong>${esc(v.verifier || "")}</strong><span>${esc(v.summary || v.criterion || "")}</span><span class="obs-task-ref" data-obs-task="${esc(v.task_id || "")}">${esc(taskTitle(state, v.task_id))}</span></li>`)
    .join("")}</ul>`;
}

export function renderMetrics(state) {
  const m = state.metrics;
  const lat = latency(state);
  const parts = [
    `recebidos ${m.received}`,
    `persistidos ${m.persisted}`,
    `fragmentos ${m.ephemeral}`,
    m.duplicates ? `duplicados ignorados ${m.duplicates}` : null,
    m.stale ? `fragmentos atrasados ignorados ${m.stale}` : null,
    m.reconnects ? `reconexões ${m.reconnects}` : null,
    m.resyncs ? `ressincronizações ${m.resyncs}` : null,
    m.droppedEvents ? `antigos descartados da memória ${m.droppedEvents}` : null,
    lat ? `atraso médio ${lat.avg} ms` : null,
    `último seq ${state.lastSeq}`,
  ];
  return parts.filter(Boolean).map(esc).join(" · ");
}

export function renderInterrupted(state) {
  if (!state.interrupted.length) return "";
  const items = state.interrupted
    .map((op) => `<li>${esc(op.kind === "output" ? `chamada ao modelo (${op.provider || ""} ${op.model || ""})` : `${op.kind} ${op.command || op.tool || ""}`)} — ${esc(taskTitle(state, op.task_id))}</li>`)
    .join("");
  return `<div class="obs-warn-box"><strong>Interrompido sem conclusão gravada</strong><p>Estas operações começaram e o processo parou antes de registrar o fim. Não foram concluídas.</p><ul>${items}</ul></div>`;
}
