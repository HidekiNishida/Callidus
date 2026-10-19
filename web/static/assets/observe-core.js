/** Estado da tela de acompanhamento de uma run: puro (sem DOM), alimentado pela foto do servidor
 * (`/runs/{id}/observe`) e pelos envelopes do SSE (`/runs/{id}/stream`). Nada aqui decide o estado real:
 * tarefas e status vêm do servidor; o navegador só agrega para exibir. */

export const LIMITS = {
  events: 2000,
  taskHistory: 200,
  outputs: 60,
  outputText: 200_000,
  terminal: 80,
  terminalText: 60_000,
  files: 300,
  verifications: 200,
  latencySamples: 50,
};

export const TERMINAL_RUN = new Set(["completed", "failed", "cancelled"]);
const RUN_STATUS = { "run.completed": "completed", "run.failed": "failed", "run.cancelled": "cancelled", "run.paused": "paused", "run.resumed": "active", "run.started": "active" };
const OP_KINDS = new Set(["tool", "command", "test"]);
const CURRENT_ORDER = ["RUNNING", "VERIFYING", "READY", "RETRY_PENDING", "PLANNING"];

export const STATUS_LABEL = {
  PENDING: "aguardando",
  READY: "pronta",
  PLANNING: "planejando",
  RUNNING: "executando",
  VERIFYING: "verificando",
  RETRY_PENDING: "nova tentativa",
  BLOCKED: "bloqueada",
  FAILED: "falhou",
  COMPLETED: "concluída",
  CANCELLED: "cancelada",
};

export const CATEGORIES = ["run", "plan", "task", "agent", "tool", "command", "file", "test", "verification"];

export function category(type) {
  return String(type || "").split(".", 1)[0];
}

function cap(list, max) {
  if (list.length > max) list.splice(0, list.length - max);
  return list;
}

function tailText(text, max) {
  return text.length > max ? text.slice(text.length - max) : text;
}

function emptyMetrics() {
  return { received: 0, persisted: 0, ephemeral: 0, duplicates: 0, stale: 0, resyncs: 0, reconnects: 0, latencies: [], maxLatencyMs: 0, droppedEvents: 0 };
}

export function createState(snapshot, now = Date.now()) {
  const header = snapshot.header || {};
  const state = {
    runId: snapshot.run?.id || null,
    run: { ...(snapshot.run || {}) },
    header: { ...header, progress: { ...(header.progress || {}) } },
    elapsedBase: header.elapsed_s ?? null,
    loadedAt: now,
    baseSeq: snapshot.last_seq || 0,
    lastSeq: snapshot.last_seq || 0,
    tasks: new Map(),
    events: [],
    eventsTruncated: Boolean(snapshot.events_truncated),
    seen: new Set(),
    outputs: new Map(),
    ops: new Map(),
    files: [],
    verifications: [],
    interrupted: snapshot.interrupted || [],
    connection: "connecting",
    lastActivity: null,
    ended: TERMINAL_RUN.has(header.status),
    metrics: emptyMetrics(),
    serverStats: snapshot.stats || {},
  };
  for (const t of snapshot.tasks || []) state.tasks.set(t.id, { ...t, history: [] });
  for (const env of snapshot.events || []) applyEvent(state, env, { replay: true });
  applyLive(state, snapshot.live || {});
  for (const op of state.interrupted) {
    const key = `${op.kind}:${op.id}`;
    if (op.kind === "output") {
      const out = state.outputs.get(op.id);
      if (out && out.status !== "completed" && out.status !== "failed") out.status = "interrupted";
    } else {
      const entry = state.ops.get(key) || newOp(op.kind, op.id, op.task_id, op.seq);
      entry.tool = entry.tool || op.tool;
      entry.command = entry.command || op.command;
      entry.status = "interrupted";
      state.ops.set(key, entry);
    }
  }
  state.metrics = emptyMetrics();
  return state;
}

function newOp(kind, callId, taskId, seq) {
  return { kind, call_id: callId, task_id: taskId || null, tool: null, command: null, status: "running", output: "", exit_code: null, duration_ms: null, counts: null, error: null, seq: seq || 0, started_seq: seq || 0, ts: null };
}

function newOutput(id, env) {
  return { output_id: id, task_id: env.task_id || null, agent: env.agent || null, provider: null, model: null, streaming: null, purpose: null, status: "waiting", text: "", received: 0, gap: false, seq: env.seq || 0, started_seq: env.seq || 0, ts: env.ts || null, error: null, chars: null, duration_ms: null };
}

function insertSorted(list, env) {
  if (!list.length || list[list.length - 1].seq < env.seq) {
    list.push(env);
    return;
  }
  let lo = 0;
  let hi = list.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid].seq < env.seq) lo = mid + 1;
    else hi = mid;
  }
  list.splice(lo, 0, env);
}

/** Carimbos do servidor são UTC; sem fuso explícito, `Date.parse` os leria como hora local. */
export function parseTs(iso) {
  if (!iso) return NaN;
  const text = String(iso);
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`);
}

function recordLatency(state, env, now) {
  const ts = parseTs(env.ts);
  if (Number.isNaN(ts)) return;
  const ms = Math.max(0, now - ts);
  state.metrics.latencies.push(ms);
  cap(state.metrics.latencies, LIMITS.latencySamples);
  state.metrics.maxLatencyMs = Math.max(state.metrics.maxLatencyMs, ms);
}

/** Aplica um envelope. Persistidos são deduplicados por `seq`; fragmentos (sem persistência) só valem se forem
 * mais novos que o que a saída/operação já tem. Retorna false quando o envelope foi descartado. */
export function applyEvent(state, env, { replay = false, now = Date.now() } = {}) {
  if (!env || !env.type || env.run_id && state.runId && env.run_id !== state.runId) return false;
  const persisted = env.persisted !== false;
  if (!replay) state.metrics.received += 1;
  if (persisted) {
    if (state.seen.has(env.seq)) {
      if (!replay) state.metrics.duplicates += 1;
      return false;
    }
    state.seen.add(env.seq);
    insertSorted(state.events, env);
    if (state.events.length > LIMITS.events) {
      const dropped = state.events.splice(0, state.events.length - LIMITS.events);
      state.metrics.droppedEvents += dropped.length;
      state.eventsTruncated = true;
    }
    state.lastSeq = Math.max(state.lastSeq, env.seq);
    if (!replay) state.metrics.persisted += 1;
  } else if (!replay) {
    state.metrics.ephemeral += 1;
  }
  if (!replay) {
    recordLatency(state, env, now);
    state.lastActivity = env.ts || state.lastActivity;
    if (!state.ended && (state.header.mode === "idle" || state.header.mode === "interrupted") && category(env.type) !== "run") state.header.mode = "live";
  }
  const fresh = env.seq > state.baseSeq;
  const handled = reduce(state, env, { fresh, persisted });
  if (persisted && env.task_id) {
    const task = state.tasks.get(env.task_id);
    if (task) cap(task.history, LIMITS.taskHistory).push(env.seq);
  }
  return handled;
}

function reduce(state, env, { fresh, persisted }) {
  const d = env.data || {};
  const type = env.type;
  const cat = category(type);
  if (cat === "run") return reduceRun(state, type, d, fresh);
  if (cat === "task" || type === "plan.updated") return reduceTask(state, env, d, fresh);
  if (cat === "agent") return reduceAgent(state, env, d, persisted);
  if (OP_KINDS.has(cat)) return reduceOp(state, env, d, cat, persisted);
  if (cat === "file") {
    if (type === "file.read") return true;
    state.files.push({ seq: env.seq, ts: env.ts, task_id: env.task_id || null, type, path: d.path, added: d.added ?? null, removed: d.removed ?? null, diff: d.diff ?? null, truncated: Boolean(d.truncated), sensitive: Boolean(d.sensitive), moved_to: d.moved_to || null, moved_from: d.moved_from || null });
    cap(state.files, LIMITS.files);
    return true;
  }
  if (cat === "verification") {
    const status = type.split(".")[1];
    const task = env.task_id || null;
    const open = status === "started" ? null : findLast(state.verifications, (v) => v.status === "started" && v.verifier === d.verifier && v.task_id === task);
    const entry = open || { seq: env.seq, ts: env.ts, task_id: task, verifier: d.verifier };
    Object.assign(entry, { status, summary: d.summary || entry.summary || null, criterion: criterionText(d.criterion) || entry.criterion || null, exit_code: d.exit_code ?? null });
    if (!open) cap(state.verifications, LIMITS.verifications).push(entry);
    return true;
  }
  return true;
}

function findLast(list, pred) {
  for (let i = list.length - 1; i >= 0; i -= 1) if (pred(list[i])) return list[i];
  return null;
}

function criterionText(value) {
  if (value == null || value === "") return null;
  if (typeof value === "string") return value;
  return value.description || value.command || value.type || JSON.stringify(value);
}

function reduceRun(state, type, d, fresh) {
  if (!fresh) return true;
  if (type === "run.progress" && d.state) state.header.progress = { ...d.state };
  const status = RUN_STATUS[type];
  if (status) {
    state.header.status = status;
    state.run.status = status;
    if (TERMINAL_RUN.has(status)) {
      state.header.mode = "replay";
      state.ended = true;
      for (const out of state.outputs.values()) if (out.status !== "completed" && out.status !== "failed") out.status = "interrupted";
      for (const op of state.ops.values()) if (op.status === "running") op.status = "interrupted";
    } else if (status === "paused") {
      state.header.mode = "paused";
    } else {
      state.header.mode = "live";
    }
  }
  return true;
}

function reduceTask(state, env, d, fresh) {
  if (env.type === "plan.updated") return true;
  if (!env.task_id) return true;
  let task = state.tasks.get(env.task_id);
  if (env.type === "task.created") {
    if (!task) {
      task = { id: env.task_id, parent_id: d.parent_id || env.parent_task_id || null, title: d.title || "", status: "PENDING", kind: d.kind || null, sort_order: d.sort_order ?? 0, attempts: 0, evidence: null, interrupted: false, history: [] };
      state.tasks.set(task.id, task);
    }
    return true;
  }
  if (!task || !fresh) return true;
  if (d.to) task.status = d.to;
  if (d.title) task.title = d.title;
  task.interrupted = false;
  if (env.type === "task.blocked" && d.reason) task.blocked_reason = d.reason;
  if (env.type === "task.failed" && d.reason) task.last_failure = { category: null, detail: d.reason };
  if (env.type === "task.started") task.started_at = env.ts;
  if (env.type === "task.completed") task.completed_at = env.ts;
  return true;
}

function reduceAgent(state, env, d, persisted) {
  const id = d.output_id;
  if (!id) return true;
  let out = state.outputs.get(id);
  if (env.type === "agent.started") {
    if (!out) {
      out = newOutput(id, env);
      state.outputs.set(id, out);
      trimOutputs(state);
    }
    Object.assign(out, { provider: d.provider, model: d.model, streaming: Boolean(d.streaming), purpose: d.purpose || null });
    return true;
  }
  if (!out) {
    out = newOutput(id, env);
    out.status = "unknown";
    state.outputs.set(id, out);
    trimOutputs(state);
  }
  if (!persisted) {
    if (env.seq <= out.seq) {
      state.metrics.stale += 1;
      return false;
    }
    out.seq = env.seq;
    if (env.type === "agent.status") {
      if (out.status !== "completed" && out.status !== "failed") out.status = d.status;
      return true;
    }
    if (env.type === "agent.output.delta") {
      const offset = Number(d.offset) || 0;
      let text = String(d.text || "");
      if (offset > out.received) out.gap = true;
      else if (offset < out.received) text = text.slice(out.received - offset);
      out.text = tailText(out.text + text, LIMITS.outputText);
      out.received = Math.max(out.received, offset + String(d.text || "").length);
      out.status = "streaming";
      return true;
    }
    return true;
  }
  if (env.type === "agent.output.completed") {
    out.status = "completed";
    out.text = tailText(String(d.content ?? out.text), LIMITS.outputText);
    out.received = out.text.length;
    out.gap = false;
    out.chars = d.chars ?? out.text.length;
    out.duration_ms = d.duration_ms ?? null;
    out.seq = Math.max(out.seq, env.seq);
    return true;
  }
  if (env.type === "agent.output.failed") {
    out.status = d.cancelled ? "cancelled" : "failed";
    out.error = d.error || "falhou";
    if (!out.text && d.partial_tail) out.text = String(d.partial_tail);
    out.duration_ms = d.duration_ms ?? null;
    out.seq = Math.max(out.seq, env.seq);
    return true;
  }
  return true;
}

function trimOutputs(state) {
  if (state.outputs.size <= LIMITS.outputs) return;
  for (const [id, out] of state.outputs) {
    if (state.outputs.size <= LIMITS.outputs) break;
    if (out.status === "completed" || out.status === "failed" || out.status === "cancelled") state.outputs.delete(id);
  }
}

function reduceOp(state, env, d, kind, persisted) {
  const id = d.call_id;
  if (!id) return true;
  const key = `${kind}:${id}`;
  let op = state.ops.get(key);
  const phase = env.type.slice(kind.length + 1);
  if (phase === "started") {
    if (!op) {
      op = newOp(kind, id, env.task_id, env.seq);
      state.ops.set(key, op);
      trimOps(state);
    }
    Object.assign(op, { tool: d.tool || op.tool, command: d.command || op.command, ts: env.ts, args: d.args || null });
    return true;
  }
  if (!op) {
    op = newOp(kind, id, env.task_id, env.seq);
    op.tool = d.tool || null;
    state.ops.set(key, op);
    trimOps(state);
  }
  if (!persisted) {
    if (env.seq <= op.seq) {
      state.metrics.stale += 1;
      return false;
    }
    op.seq = env.seq;
    op.output = tailText(op.output + String(d.text || ""), LIMITS.terminalText);
    return true;
  }
  op.seq = Math.max(op.seq, env.seq);
  op.status = phase === "completed" ? "ok" : "failed";
  op.exit_code = d.exit_code ?? op.exit_code;
  op.duration_ms = d.duration_ms ?? null;
  op.counts = d.counts || op.counts;
  op.error = phase === "failed" ? d.error || "falhou" : null;
  op.summary = d.summary || null;
  op.executed = d.executed !== false;
  if (!op.output && (d.stdout_tail || d.stderr_tail)) {
    op.output = [d.stdout_tail, d.stderr_tail].filter(Boolean).join("\n");
  }
  return true;
}

function trimOps(state) {
  if (state.ops.size <= LIMITS.terminal) return;
  for (const [key, op] of state.ops) {
    if (state.ops.size <= LIMITS.terminal) break;
    if (op.status !== "running") state.ops.delete(key);
  }
}

/** `live` do servidor (texto parcial acumulado em memória): só substitui o que estiver mais atrasado. */
export function applyLive(state, live) {
  for (const o of live.outputs || []) {
    let out = state.outputs.get(o.output_id);
    if (!out) {
      out = newOutput(o.output_id, { task_id: o.task_id, agent: o.agent, seq: 0, ts: o.started_at });
      state.outputs.set(o.output_id, out);
    }
    Object.assign(out, { provider: o.provider ?? out.provider, model: o.model ?? out.model, streaming: o.streaming ?? out.streaming, purpose: o.purpose ?? out.purpose });
    if ((o.seq || 0) > out.seq) {
      out.text = tailText(String(o.text || ""), LIMITS.outputText);
      out.received = out.text.length;
      out.gap = false;
      out.status = o.status || out.status;
      out.seq = o.seq;
    }
  }
  for (const o of live.operations || []) {
    const key = `${o.kind}:${o.call_id}`;
    let op = state.ops.get(key);
    if (!op) {
      op = newOp(o.kind, o.call_id, o.task_id, 0);
      op.ts = o.started_at;
      state.ops.set(key, op);
    }
    op.tool = op.tool || o.tool;
    op.command = op.command || o.command;
    if ((o.seq || 0) > op.seq) {
      op.output = tailText(String(o.output || ""), LIMITS.terminalText);
      op.seq = o.seq;
    }
  }
}

export function markConnection(state, connection) {
  if (connection === "reconnecting" && state.connection !== "reconnecting") state.metrics.reconnects += 1;
  state.connection = connection;
}

export function markResync(state) {
  state.metrics.resyncs += 1;
}

// ---------- seletores ----------

export function currentTask(state) {
  for (const status of CURRENT_ORDER) {
    for (const t of state.tasks.values()) if (t.status === status && t.id !== state.run.root_task_id) return t;
  }
  return null;
}

export function elapsedSeconds(state, now = Date.now()) {
  if (state.elapsedBase == null) return null;
  if (state.ended || state.header.mode === "paused") return state.elapsedBase;
  return state.elapsedBase + Math.max(0, Math.floor((now - state.loadedAt) / 1000));
}

export function latency(state) {
  const xs = state.metrics.latencies;
  if (!xs.length) return null;
  return { avg: Math.round(xs.reduce((a, b) => a + b, 0) / xs.length), max: state.metrics.maxLatencyMs, last: xs[xs.length - 1] };
}

function sortTasks(a, b) {
  return (a.sort_order ?? 0) - (b.sort_order ?? 0) || String(a.title).localeCompare(String(b.title));
}

/** Árvore hierárquica a partir das tarefas reais. `done/total` contam folhas assentadas sob cada nó. */
export function buildTree(state) {
  const children = new Map();
  for (const t of state.tasks.values()) {
    const key = t.parent_id && state.tasks.has(t.parent_id) ? t.parent_id : null;
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(t);
  }
  const build = (task, depth) => {
    const kids = (children.get(task.id) || []).sort(sortTasks).map((k) => build(k, depth + 1));
    let done = 0;
    let total = 0;
    if (!kids.length) {
      total = 1;
      done = task.status === "COMPLETED" ? 1 : 0;
    } else {
      for (const k of kids) {
        done += k.done;
        total += k.total;
      }
    }
    return { task, depth, children: kids, done, total };
  };
  return (children.get(null) || []).sort(sortTasks).map((t) => build(t, 0));
}

export function subtreeIds(state, rootId) {
  const ids = new Set([rootId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const t of state.tasks.values()) {
      if (t.parent_id && ids.has(t.parent_id) && !ids.has(t.id)) {
        ids.add(t.id);
        grew = true;
      }
    }
  }
  return ids;
}

const ERROR_TYPES = /\.(failed|blocked|cancelled)$/;

/** Filtros: `categories` (Set; vazio = todas), `taskId` (inclui descendentes), `text`, `errorsOnly`. */
export function matches(state, item, filters = {}, scope = null) {
  if (filters.taskId) {
    const ids = scope || subtreeIds(state, filters.taskId);
    if (!item.task_id || !ids.has(item.task_id)) return false;
  }
  if (filters.categories && filters.categories.size && item.type && !filters.categories.has(category(item.type))) return false;
  if (filters.errorsOnly && item.type && !ERROR_TYPES.test(item.type)) return false;
  if (filters.text) {
    const needle = filters.text.toLowerCase();
    const hay = `${item.type || ""} ${describe(item)} ${JSON.stringify(item.data || {})}`.toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  return true;
}

export function visibleEvents(state, filters = {}, limit = 300) {
  const scope = filters.taskId ? subtreeIds(state, filters.taskId) : null;
  const out = [];
  for (let i = state.events.length - 1; i >= 0 && out.length < limit; i -= 1) {
    const env = state.events[i];
    if (matches(state, env, filters, scope)) out.push(env);
  }
  return out;
}

function scoped(state, filters, items) {
  if (!filters.taskId) return items;
  const ids = subtreeIds(state, filters.taskId);
  return items.filter((x) => x.task_id && ids.has(x.task_id));
}

export function outputsList(state, filters = {}) {
  return scoped(state, filters, [...state.outputs.values()]).sort((a, b) => a.started_seq - b.started_seq);
}

export function terminalList(state, filters = {}) {
  const ops = [...state.ops.values()].filter((op) => op.kind !== "tool" || op.output);
  return scoped(state, filters, ops).sort((a, b) => a.started_seq - b.started_seq);
}

export function toolList(state, filters = {}) {
  return scoped(state, filters, [...state.ops.values()].filter((op) => op.kind === "tool")).sort((a, b) => a.started_seq - b.started_seq);
}

export function filesList(state, filters = {}) {
  return scoped(state, filters, state.files);
}

export function verificationList(state, filters = {}) {
  const tests = [...state.ops.values()]
    .filter((op) => op.kind === "test")
    .map((op) => ({ seq: op.seq, ts: op.ts, task_id: op.task_id, status: op.status === "ok" ? "passed" : op.status === "running" ? "started" : op.status, verifier: "pytest", summary: op.counts ? countsText(op.counts) : op.error, criterion: op.command, exit_code: op.exit_code }));
  return scoped(state, filters, [...state.verifications, ...tests]).sort((a, b) => a.seq - b.seq);
}

export function countsText(counts) {
  if (!counts) return "";
  return Object.entries(counts)
    .filter(([, n]) => n)
    .map(([k, n]) => `${n} ${k}`)
    .join(", ");
}

export function progressText(progress = {}) {
  const parts = [`${progress.verified || 0} verificadas`, `${progress.pending || 0} pendentes`];
  if (progress.failed) parts.push(`${progress.failed} com falha`);
  if (progress.blocked) parts.push(`${progress.blocked} bloqueadas`);
  return parts.join(" · ");
}

export function describe(env) {
  const d = env.data || {};
  switch (env.type) {
    case "run.started": return "Execução iniciada";
    case "run.progress": return `Progresso: ${progressText(d.state)}`;
    case "run.completed": return "Execução concluída";
    case "run.failed": return `Execução encerrada sem concluir: ${d.reason || d.kind || ""}`.trim();
    case "run.cancelled": return "Execução cancelada";
    case "run.paused": return `Execução pausada${d.reason ? `: ${d.reason}` : ""}`;
    case "run.resumed": return "Execução retomada";
    case "plan.started": return "Planejando subtarefas";
    case "plan.updated": return `Plano com ${Array.isArray(d.tasks) ? d.tasks.length : d.tasks} subtarefas`;
    case "task.created": return `Nova tarefa: ${d.title || ""}`;
    case "task.replanned": return `Replanejada: ${d.reason || ""}`;
    case "agent.started": return `Modelo chamado (${d.provider || "?"} · ${d.model || "?"}${d.streaming ? ", transmitindo" : ", resposta inteira"})`;
    case "agent.output.completed": return `Resposta do modelo (${d.chars ?? String(d.content || "").length} caracteres)`;
    case "agent.output.failed": return `Modelo falhou: ${d.error || ""}`;
    case "tool.started": return `Ferramenta ${d.tool}`;
    case "tool.completed": return `Ferramenta ${d.tool} concluída${d.duration_ms != null ? ` em ${d.duration_ms} ms` : ""}`;
    case "tool.failed": return `Ferramenta ${d.tool} falhou: ${d.error || ""}${d.executed === false ? " (não executada)" : ""}`;
    case "command.started": return `Comando: ${d.command || ""}`;
    case "command.completed": return `Comando terminou (código ${d.exit_code})`;
    case "command.failed": return `Comando falhou: ${d.error || ""}`;
    case "test.started": return `Testes: ${d.command || ""}`;
    case "test.completed": return `Testes passaram${d.counts ? ` (${countsText(d.counts)})` : ""}`;
    case "test.failed": return `Testes falharam${d.counts ? ` (${countsText(d.counts)})` : `: ${d.error || ""}`}`;
    case "file.read": return `Leu ${d.path}`;
    case "file.created": return `Criou ${d.path}${d.moved_from ? ` (movido de ${d.moved_from})` : ""}`;
    case "file.changed": return `Alterou ${d.path}${d.added != null ? ` (+${d.added} −${d.removed})` : ""}`;
    case "file.deleted": return `Removeu ${d.path}${d.moved_to ? ` (movido para ${d.moved_to})` : ""}`;
    case "verification.started": return `Verificação ${d.verifier}`;
    case "verification.passed": return `Verificação ${d.verifier} aprovada`;
    case "verification.failed": return `Verificação ${d.verifier} reprovada${d.summary ? `: ${d.summary}` : ""}`;
    case "verification.inconclusive": return `Verificação ${d.verifier} sem veredito`;
    case "agent.thought": return d.text || d.thought || "Pensamento";
    case "orchestrator.action": return `Passo do orquestrador: ${d.action || "?"}`;
    case "orchestrator.step": return `Olhando “${d.task || "tarefa"}”${d.status ? ` · ${d.status}` : ""}`;
    case "attempt.recorded": return d.success ? "Tentativa registrada" : "Tentativa com falha";
    default:
      if (category(env.type) === "task" && d.to) return `${d.title || "Tarefa"}: ${STATUS_LABEL[d.to] || d.to}${d.reason ? ` — ${d.reason}` : ""}`;
      return env.type;
  }
}
