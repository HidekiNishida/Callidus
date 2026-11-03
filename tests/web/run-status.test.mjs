/**
 * Arquivo: tests/web/run-status.test.mjs
 * Nome: run-status.test.mjs
 * Propósito: verificar que a interface reconhece a run em curso qualquer que seja a grafia do estado.
 * Responsabilidade: teste do frontend — `runStatusOf`, `runIsActive` e `liveRunFor` (ui.js).
 * Componentes: testes de normalização do estado e da escolha da run da conversa.
 * Dependências: node:test, node:assert, web/static/assets/app/ui.js.
 * Observações: funções puras; não faz rede nem abre navegador.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { liveRunFor, runIsActive, runStatusOf } from "../../web/static/assets/app/ui.js";

test("o estado em minúsculas da API conta como run ativa", () => {
  // Regressão: a API devolve "active" e a interface comparava com "ACTIVE".
  assert.equal(runStatusOf({ status: "active" }), "ACTIVE");
  assert.equal(runIsActive({ status: "active" }), true);
  assert.equal(runIsActive({ status: "ACTIVE" }), true);
  assert.equal(runIsActive({ status: "paused" }), false);
  assert.equal(runIsActive(null), false);
});

test("a run da conversa é a mais recente em curso, preferindo a ativa", () => {
  const runs = [
    { id: "a", root_task_id: "r1", status: "completed", created_at: "2026-11-03T15:50:00" },
    { id: "b", root_task_id: "r1", status: "paused", created_at: "2026-11-03T15:40:00" },
    { id: "c", root_task_id: "r2", status: "active", created_at: "2026-11-03T15:30:00" },
    { id: "d", root_task_id: "outra", status: "active", created_at: "2026-11-03T15:55:00" },
  ];
  assert.equal(liveRunFor(runs, ["r1", "r2"]).id, "c");
  assert.equal(liveRunFor(runs, ["r1"]).id, "b");
  assert.equal(liveRunFor(runs, ["sem-run"]), null);
});
