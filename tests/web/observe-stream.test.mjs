/**
 * Arquivo: tests/web/observe-stream.test.mjs
 * Nome: observe-stream.test.mjs
 * Propósito: verificar a assinatura do stream SSE da observabilidade: abertura, reconexão, rotação e encerramento.
 * Responsabilidade: camada de testes — comportamento do cliente de streaming de eventos no navegador.
 * Componentes: abertura a partir do cursor, queda transitória, espera crescente na reabertura, rotação do servidor, evento de fim e cancelamento.
 * Dependências: web/static/assets/app/live-stream.js, node:test.
 * Observações: a fonte de eventos e os temporizadores são substituídos por dobles; nenhuma conexão de rede é aberta.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { createStream } from "../../web/static/assets/app/live-stream.js";

class FakeSource {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.listeners = {};
    this.closed = false;
    FakeSource.instances.push(this);
  }
  /**
   * Registra um ouvinte do evento.
   * @param {string} name - nome do evento.
   * @param {Function} fn - função chamada com a mensagem.
   */
  addEventListener(name, fn) {
    (this.listeners[name] ||= []).push(fn);
  }
  /**
   * Dispara um evento para os ouvintes registrados.
   * @param {string} name - nome do evento.
   * @param {object} data - payload serializado antes da entrega.
   */
  emit(name, data) {
    const msg = { data: JSON.stringify(data) };
    if (name === "message") this.onmessage?.(msg);
    else (this.listeners[name] || []).forEach((fn) => fn(msg));
  }
  /**
   * Marca a fonte como fechada e pronta para ser encerrada.
   */
  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

/**
 * Cria um par de temporizadores falsos que não esperam de verdade.
 * @returns {object} os temporizadores falsos e a fila de chamadas agendadas.
 */
function fakeTimers() {
  const queue = [];
  return {
    queue,
    setTimeout(fn, ms) {
      queue.push({ fn, ms });
      return queue.length;
    },
    clearTimeout() {},
  };
}

/**
 * Monta um stream de teste com a fonte e os temporizadores falsos.
 * @param {object} cursorRef - referência com o cursor corrente.
 * @returns {object} o stream criado e o registro dos eventos recebidos.
 */
function harness(cursorRef) {
  FakeSource.instances = [];
  const log = { envs: [], status: [], live: 0, resync: 0, end: 0 };
  const timers = fakeTimers();
  const stream = createStream({
    runId: "r1",
    cursor: () => cursorRef.value,
    EventSourceImpl: FakeSource,
    onEnvelope: (e) => log.envs.push(e),
    onLive: () => (log.live += 1),
    onResync: () => (log.resync += 1),
    onEnd: () => (log.end += 1),
    onStatus: (s) => log.status.push(s),
    timers,
  });
  return { stream, log, timers };
}

/**
 * O stream abre a partir do último cursor aplicado e repassa eventos, live e resync.
 */
test("abre o SSE a partir do último seq aplicado e repassa eventos, live e resync", () => {
  const cursor = { value: 7 };
  const { log } = harness(cursor);
  const es = FakeSource.instances[0];
  assert.equal(es.url, "/runs/r1/stream?after=7");
  es.onopen();
  es.emit("message", { seq: 8, type: "plan.started" });
  es.emit("live", { outputs: [] });
  es.emit("resync", { dropped: 3 });
  assert.deepEqual(log.status, ["connecting", "live"]);
  assert.equal(log.envs[0].seq, 8);
  assert.equal(log.live, 1);
  assert.equal(log.resync, 1);
});

/**
 * Uma queda transitória fica com a reconexão nativa, sem abrir outra conexão.
 */
test("queda transitória fica com a reconexão nativa (Last-Event-ID), sem abrir outra conexão", () => {
  const { log } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  es.readyState = 0;
  es.onerror();
  assert.equal(log.status.at(-1), "reconnecting");
  assert.equal(FakeSource.instances.length, 1);
});

/**
 * Quando o navegador desiste, o stream reabre com o cursor atual e espera crescente.
 */
test("se o navegador desistir, reabre com o cursor atual e espera crescente", () => {
  const cursor = { value: 3 };
  const { timers } = harness(cursor);
  const first = FakeSource.instances[0];
  first.readyState = 2;
  first.onerror();
  assert.equal(timers.queue[0].ms, 1000);
  cursor.value = 12;
  timers.queue[0].fn();
  const second = FakeSource.instances[1];
  assert.equal(second.url, "/runs/r1/stream?after=12");
  second.readyState = 2;
  second.onerror();
  assert.equal(timers.queue[1].ms, 2000);
});

/**
 * A rotação do servidor reabre na hora a partir do cursor atual, sem contar como queda.
 */
test("rotate do servidor reabre na hora a partir do cursor atual, sem contar como queda", () => {
  const cursor = { value: 4 };
  const { log, timers } = harness(cursor);
  const first = FakeSource.instances[0];
  first.onopen();
  cursor.value = 20;
  first.emit("rotate", { last_seq: 20 });
  assert.equal(first.closed, true);
  assert.equal(FakeSource.instances[1].url, "/runs/r1/stream?after=20");
  assert.equal(timers.queue.length, 0);
  assert.ok(!log.status.includes("reconnecting"));
});

/**
 * O evento de fim encerra a conexão e impede nova reconexão.
 */
test("evento end encerra a conexão e não reconecta", () => {
  const { log, timers } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  es.emit("end", { last_seq: 4 });
  assert.equal(es.closed, true);
  assert.equal(log.end, 1);
  es.onerror();
  assert.equal(timers.queue.length, 0);
});

/**
 * O cancelamento fecha a assinatura com segurança e não agenda reconexão.
 */
test("stop cancela a assinatura com segurança", () => {
  const { stream, timers } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  stream.stop();
  assert.equal(es.closed, true);
  es.onerror();
  assert.equal(timers.queue.length, 0);
  assert.equal(FakeSource.instances.length, 1);
});
