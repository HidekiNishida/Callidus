/**
 * Arquivo: tests/web/usage-format.test.mjs
 * Nome: usage-format.test.mjs
 * Propósito: a interface distingue uso informado, estimativa e dado ausente.
 * Responsabilidade: teste do frontend — rótulos do demonstrativo de contexto.
 * Componentes: measurementLabel, formatTokenCount, formatRatio, budgetAlert.
 * Dependências: node:test e web/static/assets/app/ui.js.
 * Observações: não abre navegador; o texto é o contrato do painel.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { budgetAlert, formatRatio, formatTokenCount, measurementLabel } from "../../web/static/assets/app/ui.js";

test("contagem ausente não vira zero", () => {
  assert.equal(formatTokenCount(null), "indisponível");
  assert.equal(formatTokenCount({ value: null, measurement: "unavailable" }), "indisponível");
  assert.equal(formatTokenCount({ value: 0, measurement: "exact" }), "0 (informado pelo provedor)");
});

test("estimativa e uso real têm rótulos diferentes", () => {
  assert.equal(measurementLabel("estimate"), "estimativa");
  assert.equal(measurementLabel("exact"), "informado pelo provedor");
  assert.match(formatTokenCount({ value: 40, measurement: "partial" }), /parcial/);
});

test("ocupação e alerta separam janela de teto", () => {
  assert.equal(formatRatio(null), "indisponível");
  assert.equal(formatRatio(0.86), "86%");
  assert.match(budgetAlert("stop"), /reserva de conclusão/);
  assert.equal(budgetAlert("normal"), "");
});
