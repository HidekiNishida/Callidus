/**
 * Arquivo: tests/web/organization.test.mjs
 * Nome: organization.test.mjs
 * Propósito: a aba Organização mostra indicador indisponível como indisponível e nomeia todos os portões e etapas.
 * Responsabilidade: teste do frontend — formatação dos indicadores de entrega e rótulos do quadro.
 * Componentes: formatMetric, GATE_LABEL, STAGE_LABEL.
 * Dependências: node:test e web/static/assets/app/components/intelligence-organization.js.
 * Observações: não abre navegador; o texto é o contrato do painel.
 */
import assert from "node:assert/strict";
import test from "node:test";

globalThis.Vue ??= { ref: (value) => ({ value }), reactive: (o) => o, computed: (fn) => ({ get value() { return fn(); } }), onMounted: () => {}, watch: () => {} };
const { formatMetric, GATE_LABEL, STAGE_LABEL, IntelligenceOrganization } = await import(
  "../../web/static/assets/app/components/intelligence-organization.js"
);

test("indicador sem denominador não vira zero", () => {
  assert.equal(formatMetric({ kind: "unavailable", unit: "ratio", value: null }), "indisponível");
  assert.equal(formatMetric(null), "indisponível");
  assert.equal(formatMetric({ kind: "measured", unit: "ratio", value: 0.5, numerator: 1, denominator: 2 }), "50.0% (1/2)");
});

test("latência mostra os percentis que existem e a amostra", () => {
  const text = formatMetric({ kind: "measured", unit: "seconds", p50: 12.4, p95: null, p99: null, count: 3 });
  assert.equal(text, "P50 12s · P95 — · P99 — (n=3)");
});

test("todo portão e toda etapa da API têm rótulo", () => {
  for (const state of ["passed", "failed", "pending", "not_applicable"]) assert.ok(GATE_LABEL[state]);
  for (const stage of ["INBOX", "ANALYSIS", "ARCHITECTURE_REVIEW", "READY", "IN_PROGRESS", "IMPLEMENTATION_COMPLETE",
    "QA_REVIEW", "TECHNICAL_AUDIT", "READY_FOR_INTEGRATION", "INTEGRATED", "DONE", "REWORK", "BLOCKED", "FAILED",
    "CANCELLED"]) assert.ok(STAGE_LABEL[stage], stage);
});

test("detalhe da tarefa carrega e conserva a passagem de trabalho", async () => {
  const requested = [];
  globalThis.fetch = async (path) => {
    requested.push(path);
    const payload = path.endsWith("/handoff")
      ? { next_owner: "qa_engineer", next_action: "Revisar os testes", findings: ["Busca implementada"] }
      : { stage: "QA_REVIEW", status: "in_progress", gates: [], evaluation: { dimensions: [] }, reviews: [] };
    return { ok: true, status: 200, text: async () => JSON.stringify(payload) };
  };

  const component = IntelligenceOrganization.setup();
  await component.open({ task_id: "task-1", title: "Busca" });

  assert.deepEqual(requested, ["/tasks/task-1/gates", "/tasks/task-1/handoff"]);
  assert.equal(component.handoff.value.next_action, "Revisar os testes");
  assert.equal(component.handoff.value.findings[0], "Busca implementada");
});
