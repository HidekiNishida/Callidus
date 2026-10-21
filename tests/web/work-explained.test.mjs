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

import { describeActivity, integrateNarrative, splitFeed } from "../../web/static/assets/app/ui.js";

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

test("integrateNarrative acopla explicação ao item operacional seguinte", () => {
  const explained = describeActivity({
    type: "work.explained",
    data: { category: "alert", text: "A ferramenta falhou. Vou corrigir os argumentos.", phase: "recover" },
  });
  const model = describeActivity({
    type: "agent.output.completed",
    data: { chars: 12, output_id: "o1" },
  });
  const tool = describeActivity({
    type: "tool.started",
    data: { call_id: "c1", tool: "read_file", args: { path: "a.py" } },
  });
  const rows = integrateNarrative([explained, model, tool]);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].narrations.map((item) => item.kind), ["alert"]);
  assert.equal(rows[0].narrations[0].title, "A ferramenta falhou. Vou corrigir os argumentos.");
  assert.equal(rows[0].kind, "model");
  assert.equal(rows[1].kind, "tool");
  assert.deepEqual(rows[1].narrations || [], []);
});

test("splitFeed ainda classifica tipos narrativos vs operacionais", () => {
  const explained = describeActivity({
    type: "work.explained",
    data: { category: "decision", text: "Próximo passo.", phase: "plan" },
  });
  const tool = describeActivity({
    type: "tool.started",
    data: { call_id: "c2", tool: "grep", args: { pattern: "x" } },
  });
  const parts = splitFeed([explained, tool]);
  assert.deepEqual(parts.narrative.map((item) => item.kind), ["decision"]);
  assert.deepEqual(parts.operations.map((item) => item.kind), ["tool"]);
});
