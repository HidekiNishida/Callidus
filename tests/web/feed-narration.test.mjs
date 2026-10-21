/**
 * Arquivo: tests/web/feed-narration.test.mjs
 * Nome: feed-narration.test.mjs
 * Propósito: a narração fica uma vez, dentro do item expansível, com a tipografia da resposta ao vivo.
 * Responsabilidade: teste do frontend — feed, expansão e markup do chat.
 * Componentes: integrateNarrative, mergeActivity, activityIsOpen, activityStartsOpen, toggleActivity, thoughtsOutsideNarration.
 * Dependências: node:test, node:fs, fixture `fixtures/observe-with-narration.json`.
 * Observações: não abre navegador; o markup é o contrato da seção expansível.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  activityIsOpen,
  activityStartsOpen,
  describeActivity,
  integrateNarrative,
  mergeActivity,
  thoughtsOutsideNarration,
  toggleActivity,
} from "../../web/static/assets/app/ui.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../..");
const fixturePath = path.join(__dirname, "fixtures", "observe-with-narration.json");
const chatPath = path.join(root, "web/static/assets/app/components/chat.js");
const cssPath = path.join(root, "web/static/assets/app/style.css");

function feedFrom(events) {
  const feed = [];
  for (const envelope of events || []) {
    const entry = describeActivity(envelope);
    if (!entry) continue;
    if (envelope.id) entry.eventId = envelope.id;
    mergeActivity(feed, entry);
  }
  return feed;
}

function narrationTitles(rows) {
  return rows.flatMap((row) => (row.narrations || []).map((note) => note.title));
}

function thought(text) {
  return describeActivity({ type: "agent.thought", data: { text, phase: "thinking" } });
}

function explained(text, category = "decision") {
  return describeActivity({ type: "work.explained", data: { category, text, phase: "plan" } });
}

function tool(callId) {
  return describeActivity({
    type: "tool.started",
    data: { call_id: callId, tool: "read_file", args: { path: "a.py" } },
  });
}

test("o item nasce recolhido e a narração só entra na seção aberta", () => {
  const note = explained("Vou olhar o arquivo.");
  const entry = tool("c1");
  const [row] = integrateNarrative([note, entry]);
  const openIds = new Set();
  const closedIds = new Set();
  assert.equal(activityIsOpen(row, openIds, closedIds), false);
  assert.equal(row.narrations.length, 1);
  assert.equal(row.title.includes("Vou olhar"), false);

  const chat = fs.readFileSync(chatPath, "utf8");
  const detailsAt = chat.indexOf('class="activity-details"');
  const narrationAt = chat.indexOf('class="activity-narrations"');
  const toggleAt = chat.indexOf('class="activity-toggle"');
  assert.ok(detailsAt > toggleAt, "a narração precisa ficar depois do botão, na seção expansível");
  assert.ok(narrationAt > detailsAt, "a narração precisa ficar dentro de activity-details");
  const details = chat.slice(detailsAt, chat.indexOf("</Transition>", detailsAt));
  assert.match(details, /v-if="isOpen\(entry\) && !entry\.narrativeOnly"/);
  assert.match(details, /class="activity-detail activity-narration"/);
  assert.match(details, /class="activity-explanation"/);
  assert.match(details, /class="activity-output"/);
  assert.match(details, /class="activity-diff"/);
  assert.equal(chat.slice(0, detailsAt).includes('class="activity-narrations"'), false);
});

test("a narração usa a tipografia de resposta em tempo real", () => {
  const chat = fs.readFileSync(chatPath, "utf8");
  const ui = fs.readFileSync(path.join(root, "web/static/assets/app/ui.js"), "utf8");
  const css = fs.readFileSync(cssPath, "utf8");
  assert.match(ui, /detail: data\.streaming \? "resposta em tempo real"/);
  assert.match(chat, /class="activity-detail" v-if="entry\.detail/);
  assert.match(chat, /class="activity-detail activity-narration"/);
  const rule = css.slice(css.indexOf(".activity-detail {"), css.indexOf("}", css.indexOf(".activity-detail {")));
  assert.match(rule, /font-family:\s*var\(--mono\)/);
  assert.match(rule, /font-size:\s*11px/);
  assert.match(rule, /color:\s*var\(--muted\)/);
  assert.match(rule, /word-break:\s*break-all/);
  const narration = css.slice(css.indexOf(".activity-narration {"), css.indexOf("}", css.indexOf(".activity-narration {")));
  assert.doesNotMatch(narration, /font-size|font-family|background|border/);
  const block = css.slice(css.indexOf(".activity-narrations {"), css.indexOf("}", css.indexOf(".activity-narrations {")));
  assert.doesNotMatch(block, /background|border/);
  const wrap = css.slice(css.indexOf(".activity-details .activity-narration {"), css.indexOf("}", css.indexOf(".activity-details .activity-narration {")));
  assert.match(wrap, /white-space:\s*pre-wrap/);
  assert.match(wrap, /word-break:\s*break-word/);
  assert.doesNotMatch(wrap, /background|border|font-size/);
});

test("thought e work.explained da mesma frase viram uma narração", () => {
  const rows = integrateNarrative([
    thought("Vou investigar onde o erro aparece."),
    explained("Vou investigar onde o erro aparece."),
    tool("c1"),
  ]);
  assert.equal(rows.length, 1);
  assert.deepEqual(narrationTitles(rows), ["Vou investigar onde o erro aparece."]);
  assert.equal(rows[0].narrations[0].kind, "decision");
});

test("narrações diferentes continuam lado a lado", () => {
  const rows = integrateNarrative([
    thought("Primeiro olho o teste."),
    explained("Depois corrijo o arquivo."),
    tool("c1"),
    explained("O comando falhou.", "alert"),
    tool("c2"),
  ]);
  assert.deepEqual(narrationTitles(rows), ["Primeiro olho o teste.", "Depois corrijo o arquivo.", "O comando falhou."]);
});

test("duas explicações com o mesmo texto não se apagam", () => {
  const rows = integrateNarrative([
    explained("Vou repetir o passo."),
    explained("Vou repetir o passo."),
    tool("c1"),
  ]);
  assert.deepEqual(narrationTitles(rows), ["Vou repetir o passo.", "Vou repetir o passo."]);
});

test("atualizar e repetir o mesmo evento não copia a narração", () => {
  const feed = [];
  const first = explained("Vou");
  first.eventId = "e1";
  mergeActivity(feed, first);
  const longer = explained("Vou investigar o teste.");
  longer.eventId = "e1";
  mergeActivity(feed, longer);
  mergeActivity(feed, { ...longer, id: "outro" });
  assert.equal(feed.length, 1);
  assert.equal(feed[0].title, "Vou investigar o teste.");
  assert.equal(feed[0].title.includes("VouVou"), false);

  const other = explained("Outra decisão.");
  other.eventId = "e2";
  mergeActivity(feed, other);
  const host = tool("c9");
  mergeActivity(feed, host);
  const rows = integrateNarrative(feed);
  assert.deepEqual(narrationTitles(rows), ["Vou investigar o teste.", "Outra decisão."]);
});

test("a preferência abre ou fecha todos os itens", () => {
  const plain = { id: "plain" };
  const diff = { id: "diff", diff: { text: "+ linha" } };
  const openIds = new Set();
  const closedIds = new Set();
  assert.equal(activityStartsOpen(plain, "fechado"), false);
  assert.equal(activityStartsOpen(diff, "fechado"), false);
  assert.equal(activityStartsOpen(plain, "aberto"), true);
  assert.equal(activityStartsOpen(diff, "aberto"), true);
  assert.equal(activityIsOpen(diff, openIds, closedIds, "aberto"), true);
  toggleActivity(diff, openIds, closedIds, "aberto");
  assert.equal(activityIsOpen(diff, openIds, closedIds, "aberto"), false);
  assert.equal(activityIsOpen(plain, openIds, closedIds, "aberto"), true);
  const chat = fs.readFileSync(chatPath, "utf8");
  const settings = fs.readFileSync(path.join(root, "web/static/assets/app/components/settings.js"), "utf8");
  assert.match(chat, /setFeedOpen\('aberto'\)/);
  assert.match(chat, /setFeedOpen\('fechado'\)/);
  assert.match(settings, /setFeedOpen\('aberto'\)/);
  assert.match(settings, /setFeedOpen\('fechado'\)/);
});

test("abrir e fechar o item não duplica a narração", () => {
  const [row] = integrateNarrative([explained("Texto estável."), tool("c1")]);
  const openIds = new Set();
  const closedIds = new Set();
  assert.equal(activityIsOpen(row, openIds, closedIds), false);
  toggleActivity(row, openIds, closedIds);
  assert.equal(activityIsOpen(row, openIds, closedIds), true);
  toggleActivity(row, openIds, closedIds);
  toggleActivity(row, openIds, closedIds);
  assert.equal(activityIsOpen(row, openIds, closedIds), true);
  assert.deepEqual(narrationTitles(integrateNarrative([explained("Texto estável."), tool("c1")])), ["Texto estável."]);
  assert.equal(row.narrations.length, 1);
});

test("histórico reaplicado e troca de tarefa não misturam nem copiam", () => {
  const snapshot = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  const once = integrateNarrative(feedFrom(snapshot.events));
  const twice = integrateNarrative(feedFrom([...snapshot.events, ...snapshot.events]));
  const notes = once.flatMap((row) => row.narrations || []);
  const explained = snapshot.events.filter((event) => event.type === "work.explained");
  assert.deepEqual(narrationTitles(once), narrationTitles(twice));
  for (const event of explained) {
    assert.equal(notes.filter((note) => note.eventId === event.id).length, 1);
  }
  for (let index = 0; index < snapshot.events.length - 1; index += 1) {
    const current = snapshot.events[index];
    const next = snapshot.events[index + 1];
    if (current.type !== "agent.thought" || next.type !== "work.explained") continue;
    if (String(current.data?.text || "").trim() !== String(next.data?.text || "").trim()) continue;
    assert.equal(notes.some((note) => note.eventId === current.id), false);
  }
  for (const row of once) {
    const titles = (row.narrations || []).map((note) => note.title);
    assert.equal(new Set(titles).size, titles.length);
  }

  const other = feedFrom([
    { id: "x", type: "work.explained", data: { category: "result", text: "Narração da outra tarefa.", phase: "result" } },
    { id: "y", type: "tool.started", data: { call_id: "z", tool: "grep", args: { pattern: "q" } } },
  ]);
  assert.equal(narrationTitles(integrateNarrative(other)).includes("Narração da outra tarefa."), true);
  assert.equal(narrationTitles(once).includes("Narração da outra tarefa."), false);
});

test("a faixa de pensamentos não repete a narração do item", () => {
  const rows = integrateNarrative([explained("Vou investigar onde o erro aparece."), tool("c1")]);
  const visible = thoughtsOutsideNarration(
    [
      { text: "Vou investigar onde o erro aparece.", phase: "thinking" },
      { text: "Planejando a etapa", phase: "step" },
      { text: "O comando ainda está rodando.", phase: "step" },
    ],
    narrationTitles(rows),
  );
  assert.deepEqual(visible.map((item) => item.text), ["O comando ainda está rodando."]);
  const chat = fs.readFileSync(chatPath, "utf8");
  assert.match(chat, /message\.id === thoughtHostId/);
  assert.doesNotMatch(chat, /<ol class="narrative"/);
});
