/**
 * Arquivo: tests/web/compatibility.test.mjs
 * Nome: compatibility.test.mjs
 * Propósito: testar compatibilidade com navegadores sem APIs opcionais (localStorage, matchMedia).
 * Responsabilidade: teste do frontend — comportamento quando `localStorage` e `matchMedia` estão indisponíveis.
 * Componentes: setTheme, setDensity, setFeedOpen, setAutoMode, watchViewport, state.
 * Dependências: node:test, node:assert, web/static/assets/app/store.js.
 * Observações: `window`, `localStorage`, `matchMedia`, `document` e `Vue` são simulados.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

const originalWindow = globalThis.window;
const originalDocument = globalThis.document;

/**
 * Monta um ambiente mínimo, importa o módulo store e retorna o módulo + restaurador.
 *
 * @param {object} opts Opções: { noLocalStorage, noMatchMedia }.
 * @returns {Promise<{mod: object, restore: function}>}
 */
async function setupEnvironment(opts = {}) {
  const throwing = opts.noLocalStorage;
  const localStorageMock = {
    getItem: () => { if (throwing) throw new Error("QuotaExceededError"); return null; },
    setItem: () => { if (throwing) throw new Error("QuotaExceededError"); },
    removeItem: () => {},
    clear: () => {},
  };

  const documentMock = { documentElement: { dataset: {} } };
  const matchMedia = opts.noMatchMedia
    ? undefined
    : () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} });

  const windowMock = {
    localStorage: localStorageMock,
    matchMedia,
    dispatchEvent: () => true,
    addEventListener: () => {},
    removeEventListener: () => {},
    document: documentMock,
  };

  globalThis.window = windowMock;
  globalThis.document = documentMock;
  globalThis.localStorage = localStorageMock;
  globalThis.Vue = { reactive: (obj) => obj };

  const mod = await import("../../web/static/assets/app/store.js");

  // Reseta o estado compartilhado do módulo (cacheado pelo Node) para evitar vazamento entre testes.
  mod.state.theme = "dark";
  mod.state.density = "confortavel";
  mod.state.feedOpen = "fechado";
  mod.state.autoMode = true;
  mod.state.ready = false;

  const restore = () => {
    globalThis.window = originalWindow;
    globalThis.document = originalDocument;
    delete globalThis.localStorage;
    delete globalThis.Vue;
  };

  return { mod, restore };
}

test("localStorage indisponível não impede setTheme/setDensity/setFeedOpen/setAutoMode", async (t) => {
  const { mod, restore } = await setupEnvironment({ noLocalStorage: true });
  try {
    mod.setTheme("light");
    mod.setDensity("compacta");
    mod.setFeedOpen("aberto");
    mod.setAutoMode(false);
    assert.equal(mod.state.theme, "light");
    assert.equal(mod.state.density, "compacta");
    assert.equal(mod.state.feedOpen, "aberto");
    assert.equal(mod.state.autoMode, false);
  } finally {
    restore();
  }
});

test("matchMedia ausente não impede watchViewport", async (t) => {
  const { mod, restore } = await setupEnvironment({ noMatchMedia: true });
  try {
    mod.watchViewport();
    assert.equal(mod.state.compact, false);
  } finally {
    restore();
  }
});

test("valores padrão são usados quando localStorage está vazio", async (t) => {
  const { mod, restore } = await setupEnvironment({});
  try {
    assert.equal(mod.state.theme, "dark");
    assert.equal(mod.state.density, "confortavel");
    assert.equal(mod.state.feedOpen, "fechado");
    assert.equal(mod.state.autoMode, true);
  } finally {
    restore();
  }
});
