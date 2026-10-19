// web/static/assets/app/api.js — cliente HTTP e stream SSE do Callidus

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

function cleanError(text) {
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* resposta não é JSON: usa o texto */
  }
  return String(text || "erro desconhecido").slice(0, 300);
}

/** Stream SSE de uma run. Devolve um objeto com `close()`. */
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
