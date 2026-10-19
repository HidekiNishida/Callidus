import assert from "node:assert/strict";
import { test } from "node:test";

import { createStream } from "../../web/static/assets/observe.js";

class FakeSource {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.listeners = {};
    this.closed = false;
    FakeSource.instances.push(this);
  }
  addEventListener(name, fn) {
    (this.listeners[name] ||= []).push(fn);
  }
  emit(name, data) {
    const msg = { data: JSON.stringify(data) };
    if (name === "message") this.onmessage?.(msg);
    else (this.listeners[name] || []).forEach((fn) => fn(msg));
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

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

test("queda transitória fica com a reconexão nativa (Last-Event-ID), sem abrir outra conexão", () => {
  const { log } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  es.readyState = 0;
  es.onerror();
  assert.equal(log.status.at(-1), "reconnecting");
  assert.equal(FakeSource.instances.length, 1);
});

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

test("evento end encerra a conexão e não reconecta", () => {
  const { log, timers } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  es.emit("end", { last_seq: 4 });
  assert.equal(es.closed, true);
  assert.equal(log.end, 1);
  es.onerror();
  assert.equal(timers.queue.length, 0);
});

test("stop cancela a assinatura com segurança", () => {
  const { stream, timers } = harness({ value: 0 });
  const es = FakeSource.instances[0];
  stream.stop();
  assert.equal(es.closed, true);
  es.onerror();
  assert.equal(timers.queue.length, 0);
  assert.equal(FakeSource.instances.length, 1);
});
