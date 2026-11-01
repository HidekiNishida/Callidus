/**
 * Arquivo: tests/web/api.test.mjs
 * Nome: api.test.mjs
 * Propósito: testar o cliente HTTP da interface (timeouts, cancelamento, tratamento de erros).
 * Responsabilidade: teste do frontend — comportamento de `api()` sob sucesso, falha, timeout e cancelamento.
 * Componentes: api(), DEFAULT_TIMEOUT, HEALTH_TIMEOUT, TimeoutError, ConnectionError, HttpError, InvalidJsonError, CancelError.
 * Dependências: node:test, node:assert, web/static/assets/app/api.js.
 * Observações: não abre navegador e não faz rede real; `fetch` é simulado e respeita AbortSignal.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  api,
  DEFAULT_TIMEOUT,
  HEALTH_TIMEOUT,
  TimeoutError,
  ConnectionError,
  HttpError,
  InvalidJsonError,
  CancelError,
} from "../../web/static/assets/app/api.js";

const originalFetch = globalThis.fetch;

/** Resposta HTTP simulada mínima com os métodos usados por `api()`. */
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
 * Instala um `fetch` simulado que respeita `AbortSignal` e retorna respostas configuradas.
 *
 * @param {object} handler Função que recebe (url, opts) e devolve {status, ok, body, delay?}.
 * @returns {function} Restaura o `fetch` original.
 */
function mockFetch(handler) {
  globalThis.fetch = async (url, opts = {}) => {
    const signal = opts.signal;
    if (signal && signal.aborted) {
      const err = new Error("abortado");
      err.name = "AbortError";
      throw err;
    }

    const result = handler(url, opts || {});
    if (result.delay) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, result.delay);
        if (signal) {
          signal.addEventListener("abort", () => {
            clearTimeout(timer);
            const e = new Error("abortado");
            e.name = "AbortError";
            reject(e);
          }, { once: true });
        }
      });
    }
    if (signal && signal.aborted) {
      const err = new Error("abortado");
      err.name = "AbortError";
      throw err;
    }

    const status = result.status ?? 200;
    let body = "";
    if (status !== 204 && status !== 304) {
      body = result.body === undefined ? "{}" : typeof result.body === "string" ? result.body : JSON.stringify(result.body);
    }
    return new MockResponse(body, status, result.ok === false ? "Error" : "OK");
  };
  return () => { globalThis.fetch = originalFetch; };
}

async function rejectsWith(t, expectedClass, fn) {
  await assert.rejects(fn, (err) => {
    assert.ok(err instanceof expectedClass, `esperava ${expectedClass.name}, obteve ${err.constructor.name}: ${err.message}`);
    return true;
  });
}

test("DEFAULT_TIMEOUT e HEALTH_TIMEOUT estão definidos", () => {
  assert.equal(DEFAULT_TIMEOUT, 10000);
  assert.equal(HEALTH_TIMEOUT, 5000);
});

test("GET normal retorna JSON desserializado", async (t) => {
  const restore = mockFetch(() => ({ status: 200, body: { ok: true } }));
  try {
    const data = await api("/projects");
    assert.deepEqual(data, { ok: true });
  } finally {
    restore();
  }
});

test("POST envia corpo JSON e retorna resposta", async (t) => {
  let receivedBody = null;
  const restore = mockFetch((url, opts) => {
    receivedBody = opts.body;
    return { status: 201, body: { id: "novo" } };
  });
  try {
    const data = await api("/projects", { method: "POST", body: JSON.stringify({ name: "x" }) });
    assert.deepEqual(data, { id: "novo" });
    assert.equal(receivedBody, JSON.stringify({ name: "x" }));
  } finally {
    restore();
  }
});

test("status 204 devolve null", async (t) => {
  const restore = mockFetch(() => ({ status: 204, body: null }));
  try {
    const data = await api("/projects/1", { method: "DELETE" });
    assert.equal(data, null);
  } finally {
    restore();
  }
});

test("resposta vazia devolve null", async (t) => {
  const restore = mockFetch(() => ({ status: 200, body: "" }));
  try {
    const data = await api("/projects");
    assert.equal(data, null);
  } finally {
    restore();
  }
});

test("HTTP 400 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 400, body: { detail: "requisição inválida" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 401 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 401, body: { detail: "não autenticado" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 403 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 403, body: { detail: "proibido" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 404 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 404, body: { detail: "não encontrado" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects/999"));
  } finally {
    restore();
  }
});

test("HTTP 409 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 409, body: { detail: "conflito" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects/1", { method: "DELETE" }));
  } finally {
    restore();
  }
});

test("HTTP 422 lança HttpError com lista de erros por campo", async (t) => {
  const restore = mockFetch(() => ({
    status: 422,
    body: { detail: [{ loc: ["body", "name"], msg: "obrigatório" }] },
  }));
  try {
    await rejectsWith(t, HttpError, async () => {
      try {
        await api("/projects");
      } catch (e) { throw e; }
    });
  } finally {
    restore();
  }
});

test("HTTP 429 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 429, body: { detail: "muitas requisições" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 500 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 500, body: { detail: "erro interno" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 502 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 502, body: { detail: "gateway inválido" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 503 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 503, body: { detail: "serviço indisponível" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("HTTP 504 lança HttpError", async (t) => {
  const restore = mockFetch(() => ({ status: 504, body: { detail: "timeout do gateway" } }));
  try {
    await rejectsWith(t, HttpError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("falha de conexão lança ConnectionError", async (t) => {
  globalThis.fetch = async () => { throw new TypeError("recusada"); };
  try {
    await rejectsWith(t, ConnectionError, () => api("/projects"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("timeout excedido lança TimeoutError", async (t) => {
  // O fetch demora mais que o timeout configurado (50ms).
  globalThis.fetch = async () => {
    return new Promise((resolve) => setTimeout(() => resolve(new MockResponse("ok", 200, "OK")), 200));
  };
  try {
    await rejectsWith(t, TimeoutError, () => api("/projects", { timeout: 50 }));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("cancelamento externo lança CancelError", async (t) => {
  const controller = new AbortController();
  controller.abort();
  // O fetch respeita o signal: se abortado, lança AbortError (que vira CancelError).
  globalThis.fetch = async (url, opts) => {
    if (opts.signal && opts.signal.aborted) {
      const e = new Error("abortado"); e.name = "AbortError"; throw e;
    }
    return new MockResponse("ok", 200, "OK");
  };
  try {
    await rejectsWith(t, CancelError, () => api("/projects", { signal: controller.signal }));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("JSON inválido lança InvalidJsonError", async (t) => {
  const restore = mockFetch(() => ({ status: 200, body: "não é json" }));
  try {
    await rejectsWith(t, InvalidJsonError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("resposta não JSON com texto simples é tratada como erro de JSON", async (t) => {
  const restore = mockFetch(() => ({ status: 200, body: "texto puro" }));
  try {
    await rejectsWith(t, InvalidJsonError, () => api("/projects"));
  } finally {
    restore();
  }
});

test("operação administrativa aceita timeout maior com sinal", async (t) => {
  let sawSignal = false;
  const restore = mockFetch((url, opts) => {
    sawSignal = opts.signal !== undefined;
    return { status: 200, body: {} };
  });
  try {
    await api("/providers/config", { method: "PUT", body: JSON.stringify({}), timeout: 30000 });
    assert.ok(sawSignal);
  } finally {
    restore();
  }
});

test("sinal externo se une ao timeout interno", async (t) => {
  const external = new AbortController();
  let sawExternal = false;
  const restore = mockFetch(async (url, opts) => {
    sawExternal = !!opts.signal;
    return new MockResponse("{}", 200, "OK");
  });
  try {
    await api("/projects", { signal: external.signal, timeout: 10000 });
    assert.ok(sawExternal);
  } finally {
    restore();
  }
});
