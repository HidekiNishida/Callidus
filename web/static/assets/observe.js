/** Painel de acompanhamento: busca a foto da run, assina o SSE e redesenha no máximo uma vez por quadro. */
import { applyEvent, applyLive, createState, markConnection, markResync } from "./observe-core.js";
import {
  esc,
  renderActivity,
  renderFiles,
  renderFilters,
  renderHeader,
  renderInterrupted,
  renderMetrics,
  renderOutputs,
  renderTaskHistory,
  renderTerminal,
  renderTools,
  renderTree,
  renderVerification,
} from "./observe-view.js";

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 15000;

/** Conexão SSE de uma run. A reconexão automática do navegador manda `Last-Event-ID`; se o navegador desistir
 * (resposta de erro), reabre com `after` = último `seq` aplicado, com espera crescente. */
export function createStream({ runId, cursor, EventSourceImpl, onEnvelope, onLive, onResync, onEnd, onStatus, timers = globalThis }) {
  let es = null;
  let stopped = false;
  let retryMs = RECONNECT_MIN_MS;
  let retryTimer = null;

  const parse = (raw) => {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  function open() {
    if (stopped) return;
    onStatus("connecting");
    es = new EventSourceImpl(`/runs/${encodeURIComponent(runId)}/stream?after=${cursor()}`);
    es.onopen = () => {
      retryMs = RECONNECT_MIN_MS;
      onStatus("live");
    };
    es.onmessage = (m) => {
      const env = parse(m.data);
      if (env) onEnvelope(env);
    };
    es.addEventListener("live", (m) => {
      const live = parse(m.data);
      if (live) onLive(live);
    });
    es.addEventListener("resync", () => onResync());
    es.addEventListener("rotate", () => {
      es.close();
      open();
    });
    es.addEventListener("end", () => {
      stop();
      onEnd();
    });
    es.onerror = () => {
      if (stopped) return;
      onStatus("reconnecting");
      if (es.readyState === 2) {
        es.close();
        retryTimer = timers.setTimeout(open, retryMs);
        retryMs = Math.min(retryMs * 2, RECONNECT_MAX_MS);
      }
    };
  }

  function stop() {
    stopped = true;
    if (retryTimer) timers.clearTimeout(retryTimer);
    retryTimer = null;
    if (es) es.close();
    es = null;
  }

  open();
  return { stop, get source() { return es; } };
}

const AREAS = [
  ["tree", "Tarefas"],
  ["activity", "Atividade"],
  ["outputs", "Respostas do Callidus"],
  ["terminal", "Terminal"],
  ["files", "Arquivos"],
  ["verification", "Verificação"],
];

function layout() {
  const sections = AREAS.map(([key, title]) => {
    const body = key === "activity" ? `<ul class="obs-activity" data-area="activity"></ul>` : key === "tree" ? `<div class="obs-tree" role="tree" data-area="tree"></div><div data-area="history"></div>` : key === "terminal" ? `<div data-area="tools"></div><div data-area="terminal"></div>` : `<div data-area="${key}"></div>`;
    return `<details class="obs-area obs-area-${key}" open><summary>${esc(title)}</summary>${body}</details>`;
  }).join("");
  return `<div class="obs-head" data-area="header"></div>
    <div data-area="interrupted"></div>
    <div class="obs-filters" data-area="filters"></div>
    <div class="obs-areas">${sections}</div>
    <div class="obs-metrics muted" data-area="metrics"></div>`;
}

export function createObserver({ root, fetchJson, EventSourceImpl = globalThis.EventSource, now = () => Date.now(), raf = (fn) => globalThis.requestAnimationFrame(fn) }) {
  let state = null;
  let runId = null;
  let stream = null;
  let token = 0;
  let pending = false;
  let ticker = null;
  const painted = new Map();
  const ui = { expanded: new Set(), collapsed: new Set(), openFiles: new Set(), filters: { categories: new Set(), taskId: null, text: "", errorsOnly: false } };

  root.innerHTML = layout();
  const area = (name) => root.querySelector(`[data-area="${name}"]`);

  function paint(name, html) {
    if (painted.get(name) === html) return false;
    painted.set(name, html);
    const el = area(name);
    if (el) el.innerHTML = html;
    return true;
  }

  function render() {
    pending = false;
    if (!state) return;
    const f = ui.filters;
    paint("header", renderHeader(state, now()));
    paint("interrupted", renderInterrupted(state));
    paint("tree", renderTree(state, { expanded: ui.expanded, collapsed: ui.collapsed, selected: f.taskId }));
    paint("history", f.taskId ? renderTaskHistory(state, f.taskId) : "");
    paint("activity", renderActivity(state, f));
    if (paint("outputs", renderOutputs(state, f))) followBottom("outputs");
    paint("tools", renderTools(state, f));
    if (paint("terminal", renderTerminal(state, f))) followBottom("terminal");
    paint("files", renderFiles(state, f, ui.openFiles));
    paint("verification", renderVerification(state, f));
    paint("metrics", renderMetrics(state));
  }

  function followBottom(name) {
    area(name)?.querySelectorAll("pre").forEach((pre) => {
      pre.scrollTop = pre.scrollHeight;
    });
  }

  function paintFilters() {
    if (!state) return;
    painted.delete("filters");
    paint("filters", renderFilters(state, ui.filters));
  }

  function schedule() {
    if (pending) return;
    pending = true;
    raf(render);
  }

  function toggleCategory(cat) {
    const cats = ui.filters.categories;
    if (!cats.size) cats.add(cat);
    else if (cats.has(cat)) cats.delete(cat);
    else cats.add(cat);
  }

  root.addEventListener("click", (event) => {
    const t = event.target.closest("[data-obs-toggle],[data-obs-cat],[data-obs-errors],[data-obs-clear-task],[data-obs-file],[data-obs-task]");
    if (!t || !state) return;
    if (t.dataset.obsToggle) {
      const id = t.dataset.obsToggle;
      const open = t.classList.contains("open");
      (open ? ui.expanded : ui.collapsed).delete(id);
      (open ? ui.collapsed : ui.expanded).add(id);
    } else if (t.dataset.obsCat) {
      toggleCategory(t.dataset.obsCat);
      paintFilters();
    } else if (t.hasAttribute("data-obs-errors")) {
      ui.filters.errorsOnly = !ui.filters.errorsOnly;
      paintFilters();
    } else if (t.hasAttribute("data-obs-clear-task")) {
      ui.filters.taskId = null;
      paintFilters();
    } else if (t.dataset.obsFile) {
      const seq = Number(t.dataset.obsFile);
      if (ui.openFiles.has(seq)) ui.openFiles.delete(seq);
      else ui.openFiles.add(seq);
    } else if (t.dataset.obsTask) {
      ui.filters.taskId = ui.filters.taskId === t.dataset.obsTask ? null : t.dataset.obsTask;
      paintFilters();
    }
    schedule();
  });
  root.addEventListener("input", (event) => {
    if (!event.target.matches("[data-obs-text]")) return;
    ui.filters.text = event.target.value;
    schedule();
  });

  async function load(id, mine) {
    const snap = await fetchJson(`/runs/${encodeURIComponent(id)}/observe`);
    if (mine !== token) return null;
    return snap;
  }

  function stopStream() {
    if (stream) stream.stop();
    stream = null;
  }

  async function finish(mine) {
    stopStream();
    const snap = await load(runId, mine).catch(() => null);
    if (!snap || mine !== token) return;
    const { metrics, lastActivity } = state;
    state = createState(snap, now());
    Object.assign(state, { metrics, lastActivity });
    markConnection(state, "ended");
    paintFilters();
    schedule();
  }

  async function open(id) {
    if (!id) return;
    if (id === runId && state) return;
    close();
    const mine = ++token;
    runId = id;
    painted.clear();
    const snap = await load(id, mine);
    if (!snap) return;
    state = createState(snap, now());
    paintFilters();
    if (state.ended) {
      markConnection(state, "replay");
    } else {
      stream = createStream({
        runId: id,
        cursor: () => state.lastSeq,
        EventSourceImpl,
        onEnvelope: (env) => {
          if (mine !== token) return;
          applyEvent(state, env, { now: now() });
          if (state.ended && env.persisted !== false && /^run\.(completed|failed|cancelled)$/.test(env.type)) finish(mine);
          schedule();
        },
        onLive: (live) => {
          applyLive(state, live);
          schedule();
        },
        onResync: () => {
          markResync(state);
          schedule();
        },
        onEnd: () => finish(mine),
        onStatus: (s) => {
          markConnection(state, s);
          schedule();
        },
      });
      ticker = setInterval(() => {
        painted.delete("header");
        schedule();
      }, 1000);
    }
    schedule();
  }

  function close() {
    token += 1;
    stopStream();
    if (ticker) clearInterval(ticker);
    ticker = null;
    if (state) markConnection(state, "closed");
    state = null;
    runId = null;
  }

  return {
    open,
    close,
    get runId() {
      return runId;
    },
    get state() {
      return state;
    },
  };
}
