import assert from "node:assert/strict";
import { test } from "node:test";

import { createScrollFollow } from "../../web/static/assets/app/chat-scroll.js";

/** Elemento de rolagem falso: registra os `scrollTo` e simula a posição. */
function makeElement({ scrollHeight = 1000, clientHeight = 400, scrollTop = null } = {}) {
  const bottom = scrollHeight - clientHeight;
  return {
    scrollHeight,
    clientHeight,
    scrollTop: scrollTop === null ? bottom : scrollTop,
    scrolls: [],
    scrollTo({ top, behavior }) {
      this.scrolls.push({ top, behavior });
      this.scrollTop = top;
    },
    /** Simula o navegador rolando (evento `scroll`). */
    scrollBy(delta) {
      this.scrollTop = Math.max(0, Math.min(this.scrollHeight - this.clientHeight, this.scrollTop + delta));
      return this.scrollTop;
    },
  };
}

/** Temporizadores falsos: nada roda sozinho. */
function fakeTimers() {
  const pending = new Map();
  let seq = 0;
  return {
    pending,
    setTimeout(fn) {
      seq += 1;
      pending.set(seq, fn);
      return seq;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    run() {
      const entries = [...pending.entries()];
      pending.clear();
      for (const [, fn] of entries) fn();
    },
  };
}

function setup(options = {}) {
  const timers = fakeTimers();
  const states = [];
  const follow = createScrollFollow({
    timers,
    onChange: (following) => states.push(following),
    ...options,
  });
  return { timers, states, follow };
}

test("acompanha o feed enquanto a conversa está no fim", () => {
  const { follow } = setup();
  const element = makeElement();

  assert.equal(follow.followContent(element), true);
  assert.equal(element.scrolls.at(-1).top, element.scrollHeight);
  assert.equal(element.scrolls.at(-1).behavior, "smooth");
});

test("subir para ler desliga o acompanhamento do feed", () => {
  const { follow, states } = setup();
  const element = makeElement();

  follow.followContent(element);
  element.scrollBy(-200);
  follow.handleScroll(element);

  assert.equal(follow.isFollowing(), false);
  assert.ok(states.includes(false));
  // Conteúdo novo não puxa a conversa para o fim.
  element.scrolls.length = 0;
  assert.equal(follow.followContent(element), false);
  assert.equal(element.scrolls.length, 0);
});

test("voltar ao fim religa o acompanhamento do feed", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.followContent(element);
  element.scrollBy(-200);
  follow.handleScroll(element);
  assert.equal(follow.isFollowing(), false);

  // O usuário desce de volta até o fim.
  element.scrollTo({ top: element.scrollHeight - element.clientHeight, behavior: "auto" });
  follow.handleScroll(element);

  assert.equal(follow.isFollowing(), true);
  // E o feed volta a ser seguido.
  assert.equal(follow.followContent(element), true);
});

test("rolar para baixo com a roda não desliga o acompanhamento", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.handleWheel(element, 120);
  assert.equal(follow.isFollowing(), true);
});

test("rolar para cima com a roda desliga o acompanhamento", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.handleWheel(element, -120);
  assert.equal(follow.isFollowing(), false);
});

test("o botão de rolar para o fim religa o acompanhamento", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.handleWheel(element, -120);
  assert.equal(follow.isFollowing(), false);

  follow.scrollToBottom(element);
  assert.equal(follow.isFollowing(), true);
  assert.equal(element.scrolls.at(-1).top, element.scrollHeight);
});

test("a rolagem suave em andamento é cancelada quando o usuário sobe", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.followContent(element);
  element.scrollBy(-150);
  follow.handleScroll(element);

  // O cancelamento usa "instant" (ignora o scroll-behavior: smooth do CSS).
  const cancel = element.scrolls.at(-1);
  assert.equal(cancel.behavior, "instant");
  assert.equal(cancel.top, element.scrollTop);
});

test("conversa nova recomeça o acompanhamento colado no fim", () => {
  const { follow } = setup();
  const element = makeElement();

  follow.handleWheel(element, -120);
  assert.equal(follow.isFollowing(), false);

  follow.reset();
  assert.equal(follow.isFollowing(), true);
  assert.equal(follow.followContent(element), true);
});

test("rolar para cima e voltar para baixo durante a rolagem suave não trava o feed", () => {
  const { follow, timers } = setup();
  const element = makeElement();

  // O feed chega enquanto o usuário lê mais acima.
  follow.followContent(element);
  element.scrollBy(-300);
  follow.handleScroll(element);
  assert.equal(follow.isFollowing(), false);

  // O usuário desce de volta (a rolagem suave ainda estava em curso).
  timers.run();
  element.scrollTo({ top: element.scrollHeight - element.clientHeight, behavior: "auto" });
  follow.handleScroll(element);
  assert.equal(follow.isFollowing(), true);

  // E o feed volta a ser seguido.
  assert.equal(follow.followContent(element), true);
});
