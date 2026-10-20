/**
 * Arquivo: web/static/assets/app/live-stream.js
 * Nome: live-stream.js
 * Propósito: manter a conexão SSE de uma run viva, com reconexão e cursor do último `seq` aplicado.
 * Responsabilidade: frontend/transport — ciclo de vida do stream de execução.
 * Componentes: createStream(), constantes de reconexão (RECONNECT_MIN_MS, RECONNECT_MAX_MS).
 * Dependências: EventSource do navegador; rota `/runs/{id}/stream`; injeção de timers para teste.
 * Observações: a reconexão automática do navegador manda `Last-Event-ID`; se o navegador desistir
 * (resposta de erro), reabre com `after` = último `seq` aplicado, com espera crescente.
 */
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 15000;

/**
 * Abre (e reabre) o stream SSE de uma run, encaminhando cada evento ao callback correspondente.
 *
 * @param {object} options Opções da conexão.
 * @param {string} options.runId Identificador da run.
 * @param {function(): number} options.cursor Último `seq` aplicado, usado ao reabrir o stream.
 * @param {Function} options.EventSourceImpl Construtor de EventSource (injetável para teste).
 * @param {function(object): void} options.onEnvelope Recebe cada envelope persistido.
 * @param {function(object): void} options.onLive Recebe o retrato `live` do servidor.
 * @param {function(): void} options.onResync Chamado quando o servidor pede ressincronização.
 * @param {function(): void} options.onEnd Chamado quando a run termina.
 * @param {function(string): void} options.onStatus Recebe o estado da conexão
 *   ("connecting", "live" ou "reconnecting").
 * @param {object} [timers] Fonte de `setTimeout`/`clearTimeout` (injetável para teste).
 * @returns {{stop: function(): void, source: EventSource|null}} Handle com `stop()`, que encerra
 *   o stream e cancela a reconexão pendente, e `source`, com a conexão viva.
 */
export function createStream({ runId, cursor, EventSourceImpl, onEnvelope, onLive, onResync, onEnd, onStatus, timers = globalThis }) {
  let es = null;
  let stopped = false;
  let retryMs = RECONNECT_MIN_MS;
  let retryTimer = null;

  /**
   * Converte o dado bruto de um evento SSE em objeto.
   *
   * @param {string} raw Conteúdo do campo `data` do evento.
   * @returns {object|null} O objeto desserializado, ou `null` quando o JSON é inválido.
   */
  const parse = (raw) => {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  /**
   * Abre a conexão SSE e registra os handlers de cada tipo de evento.
   *
   * @returns {void}
   * Observações: ignora a abertura se o stream já foi parado.
   */
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

  /**
   * Encerra o stream: cancela a reconexão pendente e fecha a conexão ativa.
   *
   * @returns {void}
   * Observações: depois de `stop()`, nenhuma reconexão é tentada.
   */
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
