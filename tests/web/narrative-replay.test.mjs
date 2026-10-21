/**
 * Arquivo: tests/web/narrative-replay.test.mjs
 * Nome: narrative-replay.test.mjs
 * Propósito: regressão do feed — eventos reais de `/observe` viram linhas com narração acoplada.
 * Responsabilidade: teste do frontend — `describeActivity` + `integrateNarrative` sobre fixture persistida.
 * Componentes: describeActivity, integrateNarrative, NARRATIVE_KINDS.
 * Dependências: node:test, node:fs, fixture `fixtures/observe-with-narration.json`.
 * Observações: não usa rede; a fixture veio de uma run com `work.explained` no banco local.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describeActivity, integrateNarrative, NARRATIVE_KINDS } from "../../web/static/assets/app/ui.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.join(__dirname, "fixtures", "observe-with-narration.json");

function buildFeed(events) {
  const feed = [];
  for (const envelope of events || []) {
    const entry = describeActivity(envelope);
    if (entry) feed.push(entry);
  }
  return feed;
}

test("fixture observe: narrações ficam acopladas, sem linhas narrativas soltas no topo", () => {
  const raw = fs.readFileSync(fixturePath, "utf8");
  const snapshot = JSON.parse(raw);
  const feed = buildFeed(snapshot.events);
  const rows = integrateNarrative(feed);

  for (const row of rows) {
    if (NARRATIVE_KINDS.has(row.kind) && !row.narrativeOnly) {
      assert.fail(`entrada narrativa solta no feed: ${row.kind} ${row.title}`);
    }
  }

  const explained = (snapshot.events || []).filter((e) => e.type === "work.explained");
  assert.ok(explained.length >= 1, "fixture deve conter work.explained");
  for (const envelope of explained) {
    const text = String(envelope.data?.text || "").trim();
    if (!text) continue;
    const found = rows.some(
      (row) =>
        row.title === text ||
        (row.narrations || []).some((note) => note.title === text),
    );
    assert.ok(found, `texto de narração ausente das linhas: ${text.slice(0, 80)}`);
  }
});
