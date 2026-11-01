/**
 * Arquivo: tests/web/bootstrap.test.mjs
 * Nome: bootstrap.test.mjs
 * Propósito: testar o bootstrap resiliente da interface (estados por recurso, idempotência, recuperação).
 * Responsabilidade: teste do frontend — comportamento de `bootstrap()`, `reloadProjects()`, etc. sob sucesso e falha.
 * Componentes: bootstrap, reloadProjects, reloadConversations, reloadConfiguration, reloadProviders, reloadHealth, reloadBootstrap, state, getBootEvents.
 * Dependências: node:test, node:assert, web/static/assets/app/store.js, web/static/assets/app/api.js.
 * Observações: `fetch`, `window`, `localStorage`, `matchMedia`, `document` e `Vue` são simulados; não faz rede nem abre navegador.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
const originalDocument = globalThis.document;

class MockResponse {
  constructor(body, status, statusText) {
    this.body = body;
    this.status = status;
    this.statusText = statusText;
    this.ok = status >= 200 && status < 300;
    this.headers = { "content-type": "application/json" };
  }
  async text() { return this.body; }
  async json() { return JSON.parse(this.body || "{}"); }
}

/**
 * Define um `fetch` simulado com as rotas dadas.
 *
 * @param {object} routes Mapeia caminho -> {status, ok, body, delay?}.
 * @returns {function} Restaura o `fetch` original.
 */
function installFetch(routes = {}) {
  globalThis.fetch = async (url, opts = {}) => {
    console.log("DEBUG fetch chamado:", url);
    const route = routes[url] || routes[url.replace(/\?.*$/, "")];
    if (route === undefined) {
      return new MockResponse("", 404, "Not Found");
    }
    if (route.delay) await new Promise((r) => setTimeout(r, route.delay));
    const status = route.status ?? 200;
    let body = "";
    if (status !== 204 && status !== 304) {
      body = route.body === undefined ? "{}" : typeof route.body === "string" ? route.body : JSON.stringify(route.body);
    }
    return new MockResponse(body, status, route.ok === false ? "Error" : "OK");
  };
  return () => { globalThis.fetch = originalFetch; };
}

/**
 * Monta um ambiente mínimo de navegador.
 *
 * @returns {{restore: function}}
 */
function installEnvironment() {
  let storage = {};
  const localStorageMock = {
    getItem: (k) => storage[k] || null,
    setItem: (k, v) => { storage[k] = String(v); },
    removeItem: (k) => { delete storage[k]; },
    clear: () => { storage = {}; },
  };

  const documentMock = { documentElement: { dataset: {} } };
  const windowMock = {
    localStorage: localStorageMock,
    matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} }),
    dispatchEvent: () => true,
    addEventListener: () => {},
    removeEventListener: () => {},
    document: documentMock,
  };

  globalThis.window = windowMock;
  globalThis.document = documentMock;
  globalThis.localStorage = localStorageMock;
  globalThis.Vue = { reactive: (obj) => obj };

  return {
    restore: () => {
      globalThis.window = originalWindow;
      globalThis.document = originalDocument;
      delete globalThis.localStorage;
      delete globalThis.Vue;
    },
  };
}

/**
 * Reseta o estado reativo do store para valores iniciais.
 *
 * @param {object} mod Módulo store importado.
 */
function resetState(mod) {
  mod.state.view = "chat";
  mod.state.theme = "dark";
  mod.state.density = "confortavel";
  mod.state.feedOpen = "fechado";
  mod.state.ready = false;
  mod.state.railOpen = false;
  mod.state.paletteOpen = false;
  mod.state.compact = false;
  mod.state.settingsTab = "geral";
  mod.state.projects = [];
  mod.state.conversations = [];
  mod.state.loose = [];
  mod.state.selectedProject = null;
  mod.state.conversation = null;
  mod.state.tasks = [];
  mod.state.selectedTaskId = null;
  mod.state.currentRun = null;
  mod.state.uiDefaults = null;
  mod.state.search = "";
  mod.state.providers = [];
  mod.state.providerConfig = null;
  mod.state.providerModels = {};
  mod.state.providerHealth = {};
  mod.state.providerBusy = {};
  mod.state.sending = false;
  mod.state.running = false;
  mod.state.queued = null;
  mod.state.toasts = [];
  mod.state.live = null;
  mod.state.outputs = [];
  mod.state.streamEvents = [];
  mod.state.feed = [];
  mod.state.feeds = {};
  mod.state.currentRootId = null;
  mod.state.provider = "ollama";
  mod.state.modelId = "";
  mod.state.browserMode = "off";
  mod.state.approveTools = true;
  mod.state.autoMode = true;
  mod.state.objective = "";
  mod.state.attachments = [];
  mod.state.detailsOpen = true;
  mod.state.detailsTab = "detail";
  mod.state.taskFilter = "";
  mod.state.inspector = null;
  mod.state.diffText = "";
  mod.state.metricsText = "";
  mod.state.graphText = "";
  mod.state.toolsText = "";
  mod.state.toolsReport = null;
  mod.state.mcpText = "";
  mod.state.automations = [];
  mod.state.automationDetail = null;
  mod.state.supervisor = null;
  mod.state.intelligenceOverview = null;
  mod.state.runMetrics = null;
  mod.state.architectureGraph = null;
  mod.state.runGraph = null;
  mod.state.runGraphHistory = null;
  mod.state.benchmarkScenarios = [];
  mod.state.benchmarkResults = [];
  mod.state.benchmarkComparison = null;
  mod.state.lastBenchmarkResult = null;
  mod.state.diagnostics = [];
  mod.state.diagnosticAnalysis = null;
  mod.state.diagnosticsSummary = null;
  mod.state.initialization = {
    interface: "ready",
    bootstrap: "idle",
    api: "unknown",
    startedAt: null,
    completedAt: null,
    errors: [],
    degraded: false,
    projects: "idle",
    conversations: "idle",
    configuration: "idle",
    providers: "idle",
    health: "idle",
  };
  mod.state.resourceError = {
    projects: null,
    conversations: null,
    configuration: null,
    providers: null,
    health: null,
  };
}

const SUCCESS_ROUTES = {
  "/projects": { status: 200, body: [{ id: "p1", name: "Projeto" }] },
  "/conversations": { status: 200, body: [] },
  "/config/ui-defaults": { status: 200, body: { provider: "ollama", model_id: "llama3.2" } },
  "/health": { status: 200, body: { status: "ok" } },
  "/providers": { status: 200, body: { providers: [{ name: "ollama", type: "ollama", model: "llama3.2" }], default_provider: "ollama" } },
  "/providers/config": { status: 200, body: { default_provider: "ollama" } },
};

test("bootstrap com todos os serviços disponíveis deixa estados em 'ready'", async (t) => {
  const restoreFetch = installFetch(SUCCESS_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.projects, "ready");
    assert.equal(mod.state.initialization.conversations, "ready");
    assert.equal(mod.state.initialization.configuration, "ready");
    assert.equal(mod.state.initialization.health, "ready");
    assert.equal(mod.state.initialization.providers, "ready");
    assert.equal(mod.state.ready, true);
    assert.equal(mod.state.projects.length, 1);
    assert.equal(mod.state.provider, "ollama");
    assert.equal(mod.state.modelId, "llama3.2");
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("bootstrap com API indisponível deixa interface pronta e recursos em 'error'", async (t) => {
  const { restore: restoreEnv } = installEnvironment();
  try {
    globalThis.fetch = async () => { throw new TypeError("recusada"); };
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.ready, true);
    assert.equal(mod.state.initialization.projects, "error");
    assert.equal(mod.state.initialization.conversations, "error");
    assert.equal(mod.state.initialization.configuration, "error");
    assert.equal(mod.state.initialization.health, "error");
    assert.equal(mod.state.initialization.providers, "error");
    assert.equal(mod.state.projects.length, 0);
    assert.equal(mod.state.loose.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
    restoreEnv();
  }
});

test("health check lento não bloqueia a interface (usa timeout curto)", async (t) => {
  const restoreFetch = installFetch({
    ...SUCCESS_ROUTES,
    "/health": { status: 200, body: { status: "ok" }, delay: 200 },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    const start = Date.now();
    await mod.bootstrap();
    const elapsed = Date.now() - start;
    assert.ok(elapsed < 500, `bootstrap não deve esperar pelo health lento: ${elapsed}ms`);
    assert.equal(mod.state.ready, true);
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("reloadProjects recupera apenas projetos sem alterar outros estados", async (t) => {
  const restoreFetch = installFetch({
    "/projects": { status: 200, body: [{ id: "p1", name: "Recuperado" }] },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    mod.state.initialization.projects = "error";
    mod.state.resourceError.projects = "falha anterior";
    await mod.reloadProjects();
    assert.equal(mod.state.initialization.projects, "ready");
    assert.equal(mod.state.resourceError.projects, null);
    assert.equal(mod.state.projects.length, 1);
    assert.equal(mod.state.projects[0].name, "Recuperado");
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("reloadProviders recarrega o catálogo de provedores", async (t) => {
  const restoreFetch = installFetch({
    "/providers": { status: 200, body: { providers: [{ name: "ollama", type: "ollama", model: "llama3.2" }], default_provider: "ollama" } },
    "/providers/config": { status: 200, body: { default_provider: "ollama" } },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.reloadProviders();
    assert.equal(mod.state.initialization.providers, "ready");
    assert.equal(mod.state.providers.length, 1);
    assert.equal(mod.state.provider, "ollama");
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("bootstrap é idempotente: segunda execução sobrescreve estados da primeira", async (t) => {
  const restoreFetch = installFetch(SUCCESS_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.projects[0].name, "Projeto");

    const firstFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
      if (url === "/projects") return new MockResponse(JSON.stringify([{ id: "p2", name: "Segundo" }]), 200, "OK");
      return new MockResponse("{}", 200, "OK");
    };
    try {
      await mod.bootstrap();
      assert.equal(mod.state.projects[0].name, "Segundo");
    } finally {
      globalThis.fetch = firstFetch;
    }
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("getBootEvents registra etapas do ciclo de vida", async (t) => {
  const restoreFetch = installFetch(SUCCESS_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    const events = mod.getBootEvents();
    const stages = events.map((e) => e.stage);
    assert.ok(stages.includes("BOOTSTRAP_STARTED"));
    assert.ok(stages.includes("BOOT_COMPLETED"));
    assert.ok(stages.some((s) => s.startsWith("BOOT_PROJECTS")));
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

const PARTIAL_ROUTES = {
  ...SUCCESS_ROUTES,
  "/conversations": { status: 500, body: { detail: "erro interno" } },
  "/health": { status: 500, body: { detail: "erro interno" } },
  "/providers": { status: 500, body: { detail: "erro interno" } },
};

test("bootstrap com API parcialmente disponível deixa bootstrap em 'degraded'", async (t) => {
  const restoreFetch = installFetch(PARTIAL_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.projects, "ready");
    assert.equal(mod.state.initialization.conversations, "error");
    assert.equal(mod.state.initialization.configuration, "ready");
    assert.equal(mod.state.initialization.health, "error");
    assert.equal(mod.state.initialization.providers, "error");
    assert.equal(mod.state.initialization.bootstrap, "degraded");
    assert.equal(mod.state.initialization.api, "partial");
    assert.equal(mod.state.initialization.degraded, true);
    assert.equal(mod.state.ready, true);
    assert.equal(mod.state.initialization.errors.length, 3);
    assert.ok(
      mod.state.initialization.errors.some((e) => e.resource === "conversations"),
      "erro de conversas registrado"
    );
    assert.ok(mod.state.initialization.startedAt != null, "início registrado");
    assert.ok(mod.state.initialization.completedAt != null, "término registrado");
    assert.ok(
      mod.state.initialization.completedAt >= mod.state.initialization.startedAt,
      "término não é anterior ao início"
    );
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("chamadas simultâneas de bootstrap reutilizam a mesma promessa", async (t) => {
  let projetosFetchCount = 0;
  const wrappedFetch = async (url, opts = {}) => {
    if (url === "/projects") projetosFetchCount += 1;
    return globalThis.__testFetch(url, opts);
  };
  const restoreFetch = installFetch(SUCCESS_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    globalThis.__testFetch = globalThis.fetch;
    globalThis.fetch = wrappedFetch;
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    const primeira = mod.bootstrap();
    const segunda = mod.bootstrap();
    await primeira;
    assert.equal(mod.state.initialization.bootstrap, "ready");
    assert.equal(projetosFetchCount, 1, "/projects deve ser buscado uma única vez");
  } finally {
    globalThis.fetch = globalThis.__testFetch;
    delete globalThis.__testFetch;
    restoreFetch();
    restoreEnv();
  }
});

test("bootstrap repetido após conclusão reexecuta as requisições", async (t) => {
  const restoreFetch = installFetch(SUCCESS_ROUTES);
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.bootstrap, "ready");
    await mod.bootstrap();
    assert.equal(mod.state.initialization.bootstrap, "ready");
    assert.equal(mod.state.projects.length, 1);
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("HTTP 500 deixa o recurso em 'error' sem travar o bootstrap", async (t) => {
  const restoreFetch = installFetch({
    ...SUCCESS_ROUTES,
    "/projects": { status: 500, body: { detail: "erro interno" } },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.projects, "error");
    assert.equal(mod.state.ready, true);
    assert.equal(mod.state.initialization.bootstrap, "degraded");
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("JSON inválido deixa o recurso em 'error' sem travar o bootstrap", async (t) => {
  const restoreFetch = installFetch({
    ...SUCCESS_ROUTES,
    "/projects": { status: 200, body: "não é json" },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.projects, "error");
    assert.equal(mod.state.ready, true);
  } finally {
    restoreFetch();
    restoreEnv();
  }
});

test("resposta vazia válida não é tratada como falha", async (t) => {
  const restoreFetch = installFetch({
    ...SUCCESS_ROUTES,
    "/projects": { status: 200, body: "" },
  });
  const { restore: restoreEnv } = installEnvironment();
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    resetState(mod);
    await mod.bootstrap();
    assert.equal(mod.state.initialization.projects, "ready");
    assert.equal(mod.state.projects.length, 0);
    assert.equal(mod.state.ready, true);
  } finally {
    restoreFetch();
    restoreEnv();
  }
});
