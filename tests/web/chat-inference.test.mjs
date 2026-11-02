/**
 * Arquivo: tests/web/chat-inference.test.mjs
 * Nome: chat-inference.test.mjs
 * Propósito: verificar a distribuição do contexto das inferências no chat e a lista de tarefas sob falha.
 * Responsabilidade: teste do frontend — `inferenceView`/`flattenInferenceComponents` (ui.js) e `refreshTasks` (store.js).
 * Componentes: testes de normalização do detalhe da inferência e de resiliência da lista de tarefas.
 * Dependências: node:test, node:assert, web/static/assets/app/ui.js, web/static/assets/app/store.js.
 * Observações: `fetch`, `window`, `document` e `Vue` são simulados; não faz rede nem abre navegador.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { flattenInferenceComponents, inferenceView } from "../../web/static/assets/app/ui.js";

const DETAIL = {
  purpose: "operation",
  inference_type: "execution",
  provider: "openrouter",
  model: "llama3.2",
  status: "completed",
  measurement: "estimate",
  duration_ms: 153,
  prompt_tokens: null,
  completion_tokens: 40,
  estimated_prompt_tokens: 300,
  context_window_size: 1000,
  components: [
    { category: "objective", identification: "objetivo", tokens: 100, measurement: "estimate" },
    { category: "objective", identification: "requisitos", tokens: 50, measurement: "estimate" },
    { category: "instructions", identification: "sistema", tokens: 150, measurement: "estimate" },
  ],
};

test("inferenceView lê os campos do detalhe e soma a barra por categoria", () => {
  const view = inferenceView(DETAIL);
  assert.equal(view.model, "llama3.2");
  assert.equal(view.provider, "openrouter");
  assert.equal(view.measurement, "estimate");
  assert.equal(view.total_tokens, 300);
  assert.deepEqual(
    view.segments.map((seg) => [seg.category, seg.tokens, seg.pct]),
    [["objective", 150, 50], ["instructions", 150, 50]],
  );
  assert.equal(view.components.length, 3);
});

test("inferenceView cai na estimativa quando o provedor não informa tokens", () => {
  const view = inferenceView(DETAIL);
  assert.deepEqual(view.prompt_tokens, { value: 300, measurement: "estimate" });
  assert.deepEqual(view.completion_tokens, { value: 40, measurement: "exact" });
  assert.equal(view.occupancy, 0.3);
});

test("inferenceView sem registro não quebra e não inventa distribuição", () => {
  const view = inferenceView(null);
  assert.equal(view.measurement, "unavailable");
  assert.deepEqual(view.segments, []);
  assert.equal(view.occupancy, null);
});

test("flattenInferenceComponents aceita a resposta agrupada de /components", () => {
  const grouped = {
    inference_id: "x",
    categories: [
      { category: "objective", tokens: 150, components: DETAIL.components.slice(0, 2) },
      { category: "tools", tokens: 20, components: [] },
    ],
  };
  const flat = flattenInferenceComponents(grouped);
  assert.equal(flat.length, 3);
  assert.deepEqual(flat[2], { category: "tools", tokens: 20 });
  assert.deepEqual(flattenInferenceComponents(null), []);
});

/**
 * Monta o ambiente mínimo para importar o store.
 *
 * @param {Function} fetchImpl `fetch` simulado.
 * @returns {Function} Restaura os globais.
 */
function installEnvironment(fetchImpl) {
  const saved = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  const storage = {};
  const localStorageMock = {
    getItem: (k) => storage[k] || null,
    setItem: (k, v) => { storage[k] = String(v); },
    removeItem: (k) => { delete storage[k]; },
  };
  const documentMock = { documentElement: { dataset: {} } };
  globalThis.window = {
    localStorage: localStorageMock,
    matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
    document: documentMock,
  };
  globalThis.document = documentMock;
  globalThis.localStorage = localStorageMock;
  globalThis.Vue = { reactive: (obj) => obj };
  globalThis.fetch = fetchImpl;
  return () => {
    globalThis.fetch = saved.fetch;
    globalThis.window = saved.window;
    globalThis.document = saved.document;
    delete globalThis.localStorage;
    delete globalThis.Vue;
  };
}

/**
 * Resposta JSON simulada.
 *
 * @param {any} body Corpo.
 * @param {number} [status] Status HTTP.
 * @returns {object} Objeto com a forma de `Response` que o cliente usa.
 */
function json(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: { get: () => "application/json", "content-type": "application/json" },
    text: async () => JSON.stringify(body),
    json: async () => body,
  };
}

test("refreshTasks mantém a conversa na tela quando a leitura da lista falha", async () => {
  const tasks = [{ id: "t1", conversation_id: "c1", parent_id: null, status: "RUNNING" }];
  let failTasks = false;
  const restore = installEnvironment(async (url) => {
    if (String(url).includes("/conversations/c1/tasks")) {
      return failTasks ? json({ detail: "ocupado" }, 500) : json(tasks);
    }
    return json([]);
  });
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    mod.state.selectedProject = null;
    mod.state.conversation = { id: "c1", workspace_id: null };
    mod.state.tasks = [];
    await mod.refreshTasks();
    assert.equal(mod.state.tasks.length, 1);

    failTasks = true;
    await mod.refreshTasks();
    assert.equal(mod.state.tasks.length, 1, "falha na leitura não pode esvaziar o chat");
    assert.equal(mod.roots().length, 1);
  } finally {
    restore();
  }
});

test("refreshTasks descarta resposta antiga que chega depois de uma mais nova", async () => {
  const resolvers = [];
  const restore = installEnvironment((url) => {
    if (String(url).includes("/conversations/c2/tasks")) {
      return new Promise((resolve) => resolvers.push(resolve));
    }
    return Promise.resolve(json([]));
  });
  try {
    const mod = await import("../../web/static/assets/app/store.js");
    mod.state.selectedProject = null;
    mod.state.conversation = { id: "c2", workspace_id: null };
    mod.state.tasks = [];
    const older = mod.refreshTasks();
    const newer = mod.refreshTasks();
    await new Promise((r) => setTimeout(r, 0));
    resolvers[1](json([{ id: "a", conversation_id: "c2" }, { id: "b", conversation_id: "c2" }]));
    await newer;
    resolvers[0](json([]));
    await older;
    assert.deepEqual(mod.state.tasks.map((task) => task.id), ["a", "b"]);
  } finally {
    restore();
  }
});
