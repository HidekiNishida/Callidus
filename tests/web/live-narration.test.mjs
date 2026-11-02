/**
 * Arquivo: tests/web/live-narration.test.mjs
 * Nome: live-narration.test.mjs
 * Propósito: verificar que a fala do agente cresce na linha do tempo com os fragmentos reais, sem duplicar nem simular digitação.
 * Responsabilidade: teste do frontend — `describeActivity`, `mergeNarration`, `integrateNarrative`, `narrationState` e o markup.
 * Componentes: deltas em ordem, reconexão (replay e foto ao vivo), buraco, emoji, conclusão, interrupção, ordem
 *   entre narração e ferramentas, mesmo objeto por linha, ausência de temporizador e estilos por token de tema.
 * Dependências: node:test, node:fs; módulos `ui.js` e `components/narration.js` (com `Vue` e `store.js` substituídos).
 * Observações: não abre navegador; a regressão visual real fica no roteiro E2E (`tests/web/e2e.mjs`).
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { describeActivity, integrateNarrative, mergeActivity } from "../../web/static/assets/app/ui.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");

let seq = 0;
function env(type, data, extra = {}) {
  seq += 1;
  return { type, data, id: `e${seq}`, seq, task_id: "t-root", ...extra };
}

function apply(feed, envelope) {
  const entry = describeActivity(envelope);
  if (!entry) return;
  if (envelope.id) entry.eventId = envelope.id;
  mergeActivity(feed, entry);
}

const started = (id = "n1") => env("agent.narration.started", { narration_id: id, output_id: "o1" });
const delta = (text, offset, id = "n1") => env("agent.narration.delta", { narration_id: id, text, offset });
const completed = (content, status = "completed", id = "n1") =>
  env("agent.narration.completed", { narration_id: id, content, status });

test("cada fragmento acrescenta só o trecho novo, na ordem de chegada", () => {
  const feed = [];
  apply(feed, started());
  apply(feed, delta("Vou come", 0));
  assert.equal(feed[0].text, "Vou come");
  apply(feed, delta("çar pela API.", 8));
  assert.equal(feed[0].text, "Vou começar pela API.");
  assert.equal(feed[0].status, "running");
  assert.equal(feed.length, 1);
});

test("reconexão: fragmentos reenviados pelo anel não duplicam o texto", () => {
  const feed = [];
  apply(feed, started());
  apply(feed, delta("Encontrei ", 0));
  apply(feed, delta("os componentes", 10));
  // Reconexão com cursor antigo: o servidor reenvia tudo de novo.
  apply(feed, delta("Encontrei ", 0));
  apply(feed, delta("os componentes", 10));
  apply(feed, delta(" de gráfico.", 24));
  assert.equal(feed[0].text, "Encontrei os componentes de gráfico.");
});

test("foto ao vivo semeia o texto já publicado e o replay seguinte não repete", () => {
  const feed = [];
  mergeActivity(feed, { narrationId: "n9", taskId: "t1", seed: "Verificando os dados " });
  apply(feed, delta("os dados ", 12, "n9"));
  apply(feed, delta("recebidos.", 21, "n9"));
  assert.equal(feed[0].text, "Verificando os dados recebidos.");
});

test("buraco na sequência espera o texto final em vez de colar trecho fora de ordem", () => {
  const feed = [];
  apply(feed, started());
  apply(feed, delta("Vou ", 0));
  apply(feed, delta("testes.", 20));
  assert.equal(feed[0].text, "Vou ");
  assert.equal(feed[0].gap, true);
  apply(feed, completed("Vou executar os testes."));
  assert.equal(feed[0].text, "Vou executar os testes.");
  assert.equal(feed[0].gap, false);
  assert.equal(feed[0].status, "ok");
});

test("deslocamentos contam code points, como o servidor (emoji não abre buraco)", () => {
  const feed = [];
  apply(feed, started());
  apply(feed, delta("Pronto 🎉 ", 0));
  apply(feed, delta("feito.", 9));
  assert.equal(feed[0].text, "Pronto 🎉 feito.");
  assert.equal(feed[0].gap, false);
});

test("interrupção preserva o texto parcial e marca o estado", () => {
  const feed = [];
  apply(feed, started());
  apply(feed, delta("Identifiquei uma incons", 0));
  apply(feed, completed("Identifiquei uma incons", "interrupted"));
  assert.equal(feed[0].text, "Identifiquei uma incons");
  assert.equal(feed[0].status, "interrupted");
  // Fragmento atrasado depois do fim não muda o texto gravado.
  apply(feed, delta("istência", 23));
  assert.equal(feed[0].text, "Identifiquei uma incons");
});

test("narração e ferramentas ficam na linha do tempo na ordem real, sem esconder a fala", () => {
  const feed = [];
  apply(feed, started("a"));
  apply(feed, completed("Vou ler o componente.", "completed", "a"));
  apply(feed, env("tool.started", { call_id: "c1", tool: "read_file", args: { path: "chart.js" } }));
  apply(feed, env("work.explained", { category: "decision", text: "decisão do orquestrador" }));
  apply(feed, started("b"));
  apply(feed, completed("Agora vou corrigir.", "completed", "b"));
  apply(feed, env("tool.started", { call_id: "c2", tool: "edit_file", args: { path: "chart.js" } }));
  const rows = integrateNarrative(feed);
  assert.deepEqual(
    rows.map((row) => row.kind),
    ["narration", "tool", "narration", "tool"],
  );
  assert.equal(rows[0].text, "Vou ler o componente.");
  // A explicação do sistema continua no item seguinte, sem tomar o lugar da fala do modelo.
  assert.equal(rows[3].narrations[0].title, "decisão do orquestrador");
  // A linha de narração é o mesmo objeto do feed: um fragmento novo não recria a lista.
  assert.equal(rows[0], feed[0]);
});

test("execuções filhas: a narração guarda a etapa que fala", () => {
  const feed = [];
  apply(feed, env("agent.narration.started", { narration_id: "k", output_id: "o" }, { task_id: "t-filha" }));
  assert.equal(feed[0].taskId, "t-filha");
});

test("estado visível: em andamento só enquanto a mensagem trabalha", async () => {
  globalThis.Vue = { computed: (fn) => ({ get value() { return fn(); } }) };
  // O componente importa o estado; aqui só a função pura é exercitada.
  const source = read("web/static/assets/app/components/narration.js")
    .replace('import { state } from "../store.js";', "const state = { tasks: [] };")
    .replace('import { icon } from "../ui.js";', "const icon = () => '';");
  const mod = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
  assert.equal(mod.narrationState({ status: "running" }, true), "streaming");
  assert.equal(mod.narrationState({ status: "running" }, false), "interrupted");
  assert.equal(mod.narrationState({ status: "interrupted" }, true), "interrupted");
  assert.equal(mod.narrationState({ status: "error" }, false), "failed");
  assert.equal(mod.narrationState({ status: "ok" }, false), "done");
});

test("nenhuma simulação de digitação: sem temporizador no caminho da narração", () => {
  const component = read("web/static/assets/app/components/narration.js");
  assert.doesNotMatch(component, /setInterval|setTimeout|requestAnimationFrame/);
  const ui = read("web/static/assets/app/ui.js");
  const merge = ui.slice(ui.indexOf("export function mergeNarration"), ui.indexOf("export function activityStartsOpen"));
  assert.doesNotMatch(merge, /setInterval|setTimeout|requestAnimationFrame/);
});

test("a narração aparece na linha principal, fora da seção expansível", () => {
  const chat = read("web/static/assets/app/components/chat.js");
  const row = chat.indexOf('class="activity-row"');
  const narration = chat.indexOf("<NarrationEntry", row);
  const details = chat.indexOf('class="activity-details"', row);
  assert.ok(narration > row && narration < details, "NarrationEntry vem antes dos detalhes do item");
  assert.match(chat, /components: \{ NarrationEntry \}/);
});

test("estilos da narração usam os tokens do tema e respeitam movimento reduzido", () => {
  const css = read("web/static/assets/app/style.css");
  const block = css.slice(css.indexOf(".narration {"), css.indexOf(".scroll-bottom-label"));
  assert.match(block, /var\(--accent\)/);
  assert.match(block, /var\(--text\)/);
  assert.doesNotMatch(block, /#[0-9a-f]{3,6}\b/i, "sem cor fixa: claro e escuro vêm dos tokens");
  assert.match(block, /prefers-reduced-motion/);
  assert.match(block, /max-width: 640px/);
});

test("recarregar a página: só início e fim gravados reconstroem a fala na mesma posição", () => {
  const feed = [];
  // Replay de `/runs/{id}/observe`: os fragmentos não existem no banco.
  apply(feed, env("tool.started", { call_id: "r1", tool: "list_dir", args: { path: "." } }));
  apply(feed, started("h"));
  apply(feed, completed("Encontrei os componentes de gráfico.", "completed", "h"));
  apply(feed, env("tool.started", { call_id: "r2", tool: "read_file", args: { path: "charts.js" } }));
  const rows = integrateNarrative(feed);
  assert.deepEqual(rows.map((row) => row.kind), ["tool", "narration", "tool"]);
  assert.equal(rows[1].text, "Encontrei os componentes de gráfico.");
  assert.equal(rows[1].status, "ok");
});
