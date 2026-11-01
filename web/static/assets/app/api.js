/**
 * Arquivo: web/static/assets/app/api.js
 * Nome: api.js
 * Propósito: cliente HTTP e stream SSE do Callidus com timeout, cancelamento e tratamento de erros.
 * Responsabilidade: frontend/transport — fala com a API local e traduz as respostas em objetos.
 * Componentes: api(), cleanError(), openRunStream(), DEFAULT_TIMEOUT, ADMIN_TIMEOUT, HEALTH_TIMEOUT.
 * Dependências: fetch e EventSource do navegador; rotas /api do servidor.
 * Observações: o erro carrega a mensagem original da resposta; a credencial nunca é exibida.
 */

export const DEFAULT_TIMEOUT = 10000;
export const ADMIN_TIMEOUT = 30000;
export const HEALTH_TIMEOUT = 5000;

export class CancelError extends Error {
  constructor() {
    super("cancelado");
    this.name = "CancelError";
    this.cancel = true;
  }
}

export class TimeoutError extends Error {
  constructor(path) {
    super(`tempo limite excedido: ${path}`);
    this.name = "TimeoutError";
    this.timeout = true;
    this.path = path;
  }
}

export class ConnectionError extends Error {
  constructor(path, cause) {
    super(`sem conexão com o servidor: ${path}`);
    this.name = "ConnectionError";
    this.connection = true;
    this.path = path;
    this.cause = cause;
  }
}

export class HttpError extends Error {
  constructor(path, status, message) {
    super(message || `erro HTTP ${status}: ${path}`);
    this.name = "HttpError";
    this.http = true;
    this.path = path;
    this.status = status;
  }
}

export class InvalidJsonError extends Error {
  constructor(path) {
    super(`resposta não é JSON válido: ${path}`);
    this.name = "InvalidJsonError";
    this.invalidJson = true;
    this.path = path;
  }
}

function cleanError(text) {
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : item.loc;
          return `${field}: ${item.msg}`;
        })
        .join(" · ")
        .slice(0, 300);
    }
  } catch {
  }
  return String(text || "erro desconhecido").slice(0, 300);
}

export async function api(path, opts = {}) {
  const timeout = opts.timeout === undefined ? DEFAULT_TIMEOUT : opts.timeout;
  const externalSignal = opts.signal || null;
  delete opts.timeout;
  delete opts.signal;

  let timeoutTimer = null;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutTimer = setTimeout(() => reject(new TimeoutError(path)), timeout);
  });

  let cleanup = () => clearTimeout(timeoutTimer);

  if (externalSignal && externalSignal.aborted) {
    cleanup();
    throw new CancelError();
  }

  const fetchSignal = externalSignal;

  try {
    const res = await Promise.race([
      fetch(path, {
        headers: { "Content-Type": "application/json" },
        signal: fetchSignal,
        ...opts,
      }),
      timeoutPromise,
    ]);

    if (!res.ok) {
      let message = "";
      try {
        message = await res.text();
      } catch {
      }
      throw new HttpError(path, res.status, cleanError(message));
    }

    if (res.status === 204) return null;
    const text = await res.text();
    if (!text || !text.trim()) return null;
    try {
      return JSON.parse(text);
    } catch {
      throw new InvalidJsonError(path);
    }
  } catch (err) {
    cleanup();
    if (err instanceof CancelError || err instanceof TimeoutError || err instanceof ConnectionError || err instanceof HttpError || err instanceof InvalidJsonError) {
      throw err;
    }
    if (err.name === "AbortError") {
      throw new CancelError();
    }
    throw new ConnectionError(path, err);
  } finally {
    cleanup();
  }
}

export function openRunStream(runId, handlers = {}) {
  const source = new EventSource(`/runs/${runId}/stream`);
  source.onmessage = (event) => {
    try {
      handlers.onEvent?.(JSON.parse(event.data));
    } catch {
    }
  };
  source.addEventListener("live", (event) => {
    try {
      handlers.onLive?.(JSON.parse(event.data));
    } catch {
    }
  });
  source.addEventListener("end", (event) => {
    try {
      handlers.onEnd?.(JSON.parse(event.data));
    } catch {
    }
    source.close();
  });
  source.addEventListener("resync", () => handlers.onResync?.());
  source.onerror = () => handlers.onError?.();
  return {
    close() {
      source.close();
    },
  };
}
