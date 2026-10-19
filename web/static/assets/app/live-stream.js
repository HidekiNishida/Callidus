/** Conexão SSE de uma run: reconexão com espera crescente e cursor do último `seq` aplicado. */
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
