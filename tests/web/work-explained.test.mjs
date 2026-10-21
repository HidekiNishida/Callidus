/**
 * Arquivo: tests/web/work-explained.test.mjs
 * Nome: work-explained.test.mjs
 * Propósito: verificar que o feed traduz o evento work.explained sem inventar texto.
 * Responsabilidade: teste do frontend — describeActivity para explicações do orquestrador.
 * Componentes: describeActivity.
 * Dependências: node:test, web/static/assets/app/ui.js.
 * Observações: o módulo de interface não acessa a rede nem o DOM.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { describeActivity } from "../../web/static/assets/app/ui.js";

test("work.explained vira uma linha com o texto real do evento", () => {
  const entry = describeActivity({
    type: "work.explained",
    data: { category: "decision", text: "Vou investigar onde o erro aparece.", phase: "investigate" },
  });
  assert.equal(entry.kind, "decision");
  assert.equal(entry.title, "Vou investigar onde o erro aparece.");
  assert.equal(entry.explanation, entry.title);
});

test("work.explained sem texto não entra no feed", () => {
  assert.equal(describeActivity({ type: "work.explained", data: { category: "result", text: "" } }), null);
});
