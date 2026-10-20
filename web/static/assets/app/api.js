/**
 * Arquivo: web/static/assets/app/api.js
 * Nome: api.js
 * Propósito: cliente HTTP e stream SSE do Callidus.
 * Responsabilidade: frontend/transport — fala com a API local e traduz as respostas em objetos.
 * Componentes: api(), cleanError(), openRunStream().
 * Dependências: fetch e EventSource do navegador; rotas /api do servidor.
 * Observações: o erro carrega a mensagem original da resposta; a credencial nunca é exibida.
 */

/**
 * Executa uma requisição JSON na API e devolve o corpo desserializado.
 *
 * @param {string} path Caminho da rota (ex.: `/projects`).
 * @param {object} [opts] Opções passadas ao `fetch` (method, body, headers).
 * @returns {Promise<any|null>} O JSON da resposta, ou `null` quando o status é 204.
 * @throws {Error} Com a mensagem extraída do corpo da resposta de erro.
 */
export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(cleanError(text));
  }
  if (res.status === 204) return null;
  return res.json();
}

/**
 * Extrai uma mensagem legível de um corpo de erro da API.
 *
 * @param {string} text Corpo bruto da resposta de erro.
 * @returns {string} A mensagem do campo `detail` (string ou lista de erros por campo),
 *   ou o texto original quando a resposta não é JSON.
 */
function cleanError(text) {
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    // Validação do FastAPI: lista de erros por campo.
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
    /* resposta não é JSON: usa o texto */
  }
  return String(text || "erro desconhecido").slice(0, 300);
}

/**
 * Abre o stream SSE de uma run e repassa cada evento aos handlers informados.
 *
 * @param {string} runId Identificador da run.
 * @param {object} [handlers] Handlers opcionais: onEvent, onLive, onEnd, onResync, onError.
 * @returns {{close: function(): void}} Handle com `close()`, que encerra o stream.
 * Observações: eventos com payload inválido são ignorados; o stream fecha sozinho no evento `end`.
 */
export function openRunStream(runId, handlers = {}) {
  const source = new EventSource(`/runs/${runId}/stream`);
  source.onmessage = (event) => {
    try {
      handlers.onEvent?.(JSON.parse(event.data));
    } catch {
      /* payload inesperado: ignora */
    }
  };
  source.addEventListener("live", (event) => {
    try {
      handlers.onLive?.(JSON.parse(event.data));
    } catch {
      /* ignora */
    }
  });
  source.addEventListener("end", (event) => {
    try {
      handlers.onEnd?.(JSON.parse(event.data));
    } catch {
      /* ignora */
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
