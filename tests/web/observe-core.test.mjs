/**
 * Arquivo: tests/web/observe-core.test.mjs
 * Nome: observe-core.test.mjs
 * Propósito: verificar o redutor de estado da interface de observação: deduplicação, árvore, fragmentos, terminal e filtros.
 * Responsabilidade: camada de testes — comportamento do estado e da renderização da observabilidade no navegador.
 * Componentes: deduplicação por sequência, árvore de tarefas, fragmentos do modelo, operações e verificações, escape de texto, diff de arquivo, operações interrompidas, fim da run, filtros, memória limitada, carimbo de tempo e métricas.
 * Dependências: web/static/assets/app/live-state.js, web/static/assets/app/live-view.js, node:test.
 * Observações: execução com o test runner do Node, sem rede e sem servidor; o estado é montado a partir de fotos sintéticas.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LIMITS,
  applyEvent,
  applyLive,
  buildTree,
  createState,
  currentTask,
  elapsedSeconds,
  markConnection,
  parseTs,
  visibleEvents,
  verificationList,
} from "../../web/static/assets/app/live-state.js";
import { esc, renderFiles, renderHeader, renderOutputs, renderTools, renderTree } from "../../web/static/assets/app/live-view.js";

const RUN = "run-1";
const ROOT = "t-root";

/**
 * Monta um evento persistido de teste.
 * @param {number} seq - número de sequência do evento.
 * @param {string} type - tipo do evento.
 * @param {object} data - payload do evento.
 * @param {object} extra - campos extras, como run_id e task_id.
 * @returns {object} o evento no formato entregue pelo servidor.
 */
function env(seq, type, data = {}, extra = {}) {
  return { id: `e${seq}`, run_id: RUN, task_id: null, type, seq, ts: "2026-10-18T12:00:00+00:00", data, persisted: true, ...extra };
}

/**
 * Monta um fragmento efêmero de teste, que não é persistido.
 * @param {number} seq - número de sequência do fragmento.
 * @param {string} type - tipo do fragmento.
 * @param {object} data - payload do fragmento.
 * @param {object} extra - campos extras.
 * @returns {object} o fragmento no formato entregue pelo servidor.
 */
function frag(seq, type, data, extra = {}) {
  return env(seq, type, data, { persisted: false, ...extra });
}

/**
 * Monta a foto de uma run em andamento.
 * @param {object} overrides - campos trocados na foto padrão.
 * @returns {object} a foto no formato devolvido pelo servidor.
 */
function snapshot(overrides = {}) {
  return {
    run: { id: RUN, root_task_id: ROOT, status: "active" },
    header: { title: "Objetivo", status: "active", mode: "live", elapsed_s: 10, progress: { verified: 0, pending: 2, failed: 0, blocked: 0 } },
    tasks: [
      { id: ROOT, parent_id: null, title: "Objetivo", status: "RUNNING", sort_order: 0, attempts: 0, evidence: null, interrupted: false },
      { id: "t-a", parent_id: ROOT, title: "A", status: "PENDING", sort_order: 1, attempts: 0, evidence: null, interrupted: false },
    ],
    live: { outputs: [], operations: [] },
    interrupted: [],
    events: [env(1, "run.started")],
    events_truncated: false,
    last_seq: 1,
    stats: {},
    ...overrides,
  };
}

/**
 * Os eventos persistidos entram uma única vez e mantêm a ordem da sequência.
 */
test("eventos persistidos são deduplicados por seq e mantidos em ordem", () => {
  const s = createState(snapshot());
  assert.equal(applyEvent(s, env(5, "plan.started")), true);
  assert.equal(applyEvent(s, env(3, "task.created", { title: "B", parent_id: ROOT }, { task_id: "t-b" })), true);
  assert.equal(applyEvent(s, env(5, "plan.started")), false);
  assert.deepEqual(s.events.map((e) => e.seq), [1, 3, 5]);
  assert.equal(s.metrics.duplicates, 1);
  assert.equal(s.lastSeq, 5);
});

/**
 * Eventos de outra run são ignorados e não entram no estado.
 */
test("eventos de outra run são ignorados", () => {
  const s = createState(snapshot());
  assert.equal(applyEvent(s, env(9, "plan.started", {}, { run_id: "outra" })), false);
  assert.equal(s.events.length, 1);
});

/**
 * A árvore reflete o status vindo do servidor, conta as folhas e mostra o estado de cada tarefa.
 */
test("árvore hierárquica reflete status vindos do servidor e conta folhas", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "task.created", { title: "B", parent_id: ROOT, sort_order: 2 }, { task_id: "t-b" }));
  applyEvent(s, env(3, "task.started", { from: "READY", to: "RUNNING", title: "A" }, { task_id: "t-a" }));
  applyEvent(s, env(4, "task.completed", { from: "VERIFYING", to: "COMPLETED", title: "A" }, { task_id: "t-a" }));
  const [root] = buildTree(s);
  assert.equal(root.task.id, ROOT);
  assert.deepEqual(root.children.map((c) => c.task.title), ["A", "B"]);
  assert.equal(root.done, 1);
  assert.equal(root.total, 2);
  assert.equal(s.tasks.get("t-a").history.length, 2);
  const html = renderTree(s, { expanded: new Set(), collapsed: new Set(), selected: null });
  assert.match(html, /concluída/);
  assert.match(html, /aguardando/);
});

/**
 * Eventos já contidos na foto não regridem o status das tarefas.
 */
test("eventos já refletidos na foto não regridem o status das tarefas", () => {
  const s = createState(
    snapshot({
      tasks: [{ id: ROOT, parent_id: null, title: "Objetivo", status: "COMPLETED", sort_order: 0, attempts: 0 }],
      events: [env(1, "task.started", { from: "READY", to: "RUNNING" }, { task_id: ROOT })],
      last_seq: 1,
    }),
  );
  assert.equal(s.tasks.get(ROOT).status, "COMPLETED");
});

/**
 * Os fragmentos do modelo são aceitos só quando são mais novos, e a saída concluída substitui o texto parcial.
 */
test("fragmentos do modelo: só os mais novos entram; atrasados e repetidos são descartados", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "agent.started", { output_id: "o1", provider: "ollama", model: "m", streaming: true }, { task_id: "t-a" }));
  applyEvent(s, frag(3, "agent.output.delta", { output_id: "o1", text: "Olá ", offset: 0 }));
  applyEvent(s, frag(4, "agent.output.delta", { output_id: "o1", text: "mundo", offset: 4 }));
  assert.equal(applyEvent(s, frag(3, "agent.output.delta", { output_id: "o1", text: "Olá ", offset: 0 })), false);
  const out = s.outputs.get("o1");
  assert.equal(out.text, "Olá mundo");
  assert.equal(out.status, "streaming");
  assert.equal(s.metrics.stale, 1);
  applyEvent(s, env(5, "agent.output.completed", { output_id: "o1", content: "Olá mundo!", chars: 10 }));
  assert.equal(out.text, "Olá mundo!");
  assert.equal(out.status, "completed");
  assert.match(renderOutputs(s, {}), /Olá mundo!/);
});

/**
 * A sobreposição de offset não duplica texto e um buraco no texto é sinalizado.
 */
test("fragmento com sobreposição de offset não duplica texto; buraco é sinalizado", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "agent.started", { output_id: "o1", provider: "ollama", model: "m", streaming: true }));
  applyEvent(s, frag(3, "agent.output.delta", { output_id: "o1", text: "abc", offset: 0 }));
  applyEvent(s, frag(4, "agent.output.delta", { output_id: "o1", text: "bcd", offset: 1 }));
  assert.equal(s.outputs.get("o1").text, "abcd");
  applyEvent(s, frag(5, "agent.output.delta", { output_id: "o1", text: "xyz", offset: 10 }));
  assert.equal(s.outputs.get("o1").gap, true);
});

/**
 * Provedor sem streaming aparece como espera pela resposta inteira, sem texto inventado.
 */
test("provedor sem streaming aparece como espera pela resposta inteira, sem texto inventado", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "agent.started", { output_id: "o2", provider: "openai", model: "x", streaming: false }));
  applyEvent(s, frag(3, "agent.status", { output_id: "o2", status: "waiting_full_response" }));
  const out = s.outputs.get("o2");
  assert.equal(out.text, "");
  assert.match(renderOutputs(s, {}), /provedor sem streaming/);
});

/**
 * O texto parcial que vem do servidor é preservado e os fragmentos antigos não repetem.
 */
test("foto com saída em andamento: texto parcial vem do servidor e fragmentos antigos não repetem", () => {
  const s = createState(
    snapshot({
      events: [env(1, "run.started"), env(2, "agent.started", { output_id: "o1", provider: "ollama", model: "m", streaming: true })],
      live: { outputs: [{ output_id: "o1", text: "parcial", status: "streaming", seq: 6 }], operations: [] },
      last_seq: 2,
    }),
  );
  assert.equal(s.outputs.get("o1").text, "parcial");
  assert.equal(applyEvent(s, frag(6, "agent.output.delta", { output_id: "o1", text: "l", offset: 6 })), false);
  applyEvent(s, frag(7, "agent.output.delta", { output_id: "o1", text: " mais", offset: 7 }));
  assert.equal(s.outputs.get("o1").text, "parcial mais");
});

/**
 * O estado ao vivo substitui apenas o que estiver atrasado.
 */
test("live depois de ressincronizar só substitui o que estiver atrasado", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "command.started", { call_id: "c1", command: "ls" }));
  applyEvent(s, frag(3, "command.output", { call_id: "c1", stream: "stdout", text: "a\n" }));
  applyLive(s, { outputs: [], operations: [{ kind: "command", call_id: "c1", output: "a\nb\n", seq: 9 }] });
  assert.equal(s.ops.get("command:c1").output, "a\nb\n");
  applyLive(s, { outputs: [], operations: [{ kind: "command", call_id: "c1", output: "velho", seq: 4 }] });
  assert.equal(s.ops.get("command:c1").output, "a\nb\n");
});

/**
 * Comandos e testes aparecem com a saída, a contagem e o veredito.
 */
test("terminal e verificação: comando, testes com contagem e veredito", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "test.started", { call_id: "p1", command: "pytest -q" }, { task_id: "t-a" }));
  applyEvent(s, frag(3, "test.output", { call_id: "p1", text: "..F\n" }));
  applyEvent(s, env(4, "test.failed", { call_id: "p1", exit_code: 1, counts: { passed: 2, failed: 1 }, error: "código de saída 1" }));
  applyEvent(s, env(5, "verification.failed", { verifier: "pytest", summary: "1 falhou" }, { task_id: "t-a" }));
  const op = s.ops.get("test:p1");
  assert.equal(op.status, "failed");
  assert.equal(op.output, "..F\n");
  const v = verificationList(s, {});
  assert.deepEqual(v.map((x) => x.status), ["failed", "failed"]);
  assert.match(v[0].summary, /2 passed, 1 failed/);
});

/**
 * O início e o veredito de uma verificação viram um item só, com o critério legível.
 */
test("verificação: início e veredito viram um item só; critério estruturado vira texto legível", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "verification.started", { verifier: "pytest", criterion: { type: "pytest", command: "pytest -q" } }, { task_id: "t-a" }));
  assert.equal(verificationList(s, {})[0].status, "started");
  applyEvent(s, env(3, "verification.passed", { verifier: "pytest", summary: "ok" }, { task_id: "t-a" }));
  const items = verificationList(s, {});
  assert.equal(items.length, 1);
  assert.equal(items[0].status, "passed");
  assert.equal(items[0].criterion, "pytest -q");
});

/**
 * O resumo da ferramenta é legível e a recusa aparece como não executada.
 */
test("ferramentas: resumo estruturado legível e recusa marcada como não executada", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "tool.started", { call_id: "w1", tool: "write_file" }));
  applyEvent(s, env(3, "tool.completed", { call_id: "w1", tool: "write_file", summary: { path: "a.py", bytes: 12, truncated: false } }));
  applyEvent(s, env(4, "tool.failed", { call_id: "r1", tool: "run_command", error: "approval_required", executed: false }));
  const html = renderTools(s, {});
  assert.match(html, /path a\.py · bytes 12/);
  assert.doesNotMatch(html, /object Object/);
  assert.match(html, /não executada/);
});

/**
 * O texto vindo dos eventos é escapado antes de virar HTML.
 */
test("texto vindo de eventos é escapado antes de virar HTML", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "agent.started", { output_id: "x", provider: "p", model: "m", streaming: true }));
  applyEvent(s, env(3, "agent.output.completed", { output_id: "x", content: "<img src=x onerror=alert(1)>" }));
  const html = renderOutputs(s, {});
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.equal(esc(`"'&`), "&quot;&#39;&amp;");
});

/**
 * Arquivo sensível não mostra diff, e arquivo comum mostra o diff ao ser aberto.
 */
test("arquivo sensível não mostra diff; arquivo comum mostra diff ao abrir", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "file.changed", { path: "a.py", added: 1, removed: 0, diff: "--- a/a.py\n+++ b/a.py\n+x = 1" }));
  applyEvent(s, env(3, "file.changed", { path: ".env", added: 1, removed: 1, diff: null, sensitive: true }));
  const closed = renderFiles(s, {}, new Set());
  assert.doesNotMatch(closed, /x = 1/);
  const open = renderFiles(s, {}, new Set([2, 3]));
  assert.match(open, /x = 1/);
  assert.match(open, /conteúdo não transmitido/);
});

/**
 * Operações interrompidas na foto nunca aparecem como concluídas.
 */
test("operações interrompidas na foto nunca aparecem como concluídas", () => {
  const s = createState(
    snapshot({
      header: { title: "x", status: "active", mode: "interrupted", elapsed_s: 5, progress: {} },
      tasks: [{ id: ROOT, parent_id: null, title: "Objetivo", status: "RUNNING", sort_order: 0, interrupted: true }],
      events: [env(1, "command.started", { call_id: "c1", command: "sleep 99" }, { task_id: ROOT })],
      interrupted: [{ kind: "command", id: "c1", task_id: ROOT, command: "sleep 99", seq: 1 }],
      last_seq: 1,
    }),
  );
  assert.equal(s.ops.get("command:c1").status, "interrupted");
  assert.match(renderTree(s, { expanded: new Set(), collapsed: new Set() }), /interrompida/);
  assert.match(renderHeader(s), /interrompida/);
});

/**
 * O fim da run fecha as operações abertas como interrompidas e para o relógio.
 */
test("fim da run fecha operações abertas como interrompidas e para o relógio", () => {
  const s = createState(snapshot(), 1_000);
  applyEvent(s, env(2, "command.started", { call_id: "c1", command: "x" }));
  applyEvent(s, env(3, "run.failed", { reason: "parada" }));
  assert.equal(s.ended, true);
  assert.equal(s.header.mode, "replay");
  assert.equal(s.ops.get("command:c1").status, "interrupted");
  assert.equal(elapsedSeconds(s, 999_999), 10);
});

/**
 * A foto de uma run encerrada nasce como reexibição.
 */
test("foto de run encerrada (status em minúsculas, como o servidor manda) já nasce como reexibição", () => {
  const s = createState(snapshot({ run: { id: RUN, root_task_id: ROOT, status: "completed" }, header: { title: "x", status: "completed", mode: "replay", elapsed_s: 30, progress: {} } }));
  assert.equal(s.ended, true);
  assert.match(renderHeader(s), /concluída/);
  assert.match(renderHeader(s), /reexibição/);
});

/**
 * Os filtros de categoria, tarefa, texto e só falhas selecionam os eventos certos.
 */
test("filtros por categoria, tarefa (com descendentes), texto e só falhas", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "task.created", { title: "Filha", parent_id: "t-a" }, { task_id: "t-c" }));
  applyEvent(s, env(3, "tool.failed", { call_id: "x", tool: "read_file", error: "não achou" }, { task_id: "t-c" }));
  applyEvent(s, env(4, "file.read", { path: "README.md" }, { task_id: ROOT }));
  assert.deepEqual(visibleEvents(s, { categories: new Set(["tool"]) }).map((e) => e.seq), [3]);
  assert.deepEqual(visibleEvents(s, { categories: new Set(), taskId: "t-a" }).map((e) => e.seq), [3, 2]);
  assert.deepEqual(visibleEvents(s, { categories: new Set(), text: "readme" }).map((e) => e.seq), [4]);
  assert.deepEqual(visibleEvents(s, { categories: new Set(), errorsOnly: true }).map((e) => e.seq), [3]);
});

/**
 * A tarefa atual segue a prioridade do servidor e ignora a raiz.
 */
test("tarefa atual segue a mesma prioridade do servidor e ignora a raiz", () => {
  const s = createState(snapshot());
  assert.equal(currentTask(s), null);
  applyEvent(s, env(2, "task.started", { from: "READY", to: "RUNNING" }, { task_id: "t-a" }));
  assert.equal(currentTask(s).id, "t-a");
});

/**
 * A memória de eventos é limitada e o descarte é sinalizado.
 */
test("memória limitada: eventos antigos saem e o truncamento é sinalizado", () => {
  const s = createState(snapshot());
  for (let i = 2; i < LIMITS.events + 50; i += 1) applyEvent(s, env(i, "file.read", { path: `f${i}` }));
  assert.equal(s.events.length, LIMITS.events);
  assert.equal(s.eventsTruncated, true);
  assert.ok(s.metrics.droppedEvents > 0);
});

/**
 * O carimbo sem fuso é lido como UTC e o carimbo com fuso é respeitado.
 */
test("carimbo sem fuso é lido como UTC (o SQLite perde o fuso), com fuso é respeitado", () => {
  assert.equal(parseTs("2026-10-18T12:00:00"), Date.parse("2026-10-18T12:00:00Z"));
  assert.equal(parseTs("2026-10-18T12:00:00+00:00"), Date.parse("2026-10-18T12:00:00Z"));
  assert.equal(parseTs("2026-10-18T09:00:00-03:00"), Date.parse("2026-10-18T12:00:00Z"));
  assert.ok(Number.isNaN(parseTs(null)));
});

/**
 * A latência é medida pelo carimbo do evento e as reconexões são contadas.
 */
test("métricas: atraso medido pelo carimbo do evento e contagem de reconexões", () => {
  const s = createState(snapshot());
  applyEvent(s, env(2, "plan.started"), { now: Date.parse("2026-10-18T12:00:00.250Z") });
  assert.equal(s.metrics.latencies[0], 250);
  markConnection(s, "reconnecting");
  markConnection(s, "reconnecting");
  markConnection(s, "live");
  assert.equal(s.metrics.reconnects, 1);
});
