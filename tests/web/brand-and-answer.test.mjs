/**
 * Arquivo: tests/web/brand-and-answer.test.mjs
 * Nome: brand-and-answer.test.mjs
 * Propósito: verificar o símbolo por tema e a leitura da resposta final já persistida.
 * Responsabilidade: teste do frontend — brandSrc e visibleFinalAnswer.
 * Componentes: brandSrc, visibleFinalAnswer, referências nos componentes.
 * Dependências: node:test, node:fs, web/static/assets/app/ui.js.
 * Observações: não abre navegador e não lê o banco do usuário.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { brandSrc, visibleFinalAnswer } from "../../web/static/assets/app/ui.js";

const root = new URL("../../", import.meta.url);

test("tema claro usa tinta escura e o tema escuro mantém a tinta clara", () => {
  assert.equal(brandSrc("mark", "light"), "/assets/brand/callidus-mark-light.svg");
  assert.equal(brandSrc("lockup", "light"), "/assets/brand/callidus-lockup-light.svg");
  assert.equal(brandSrc("mark", "dark"), "/assets/brand/callidus-mark.svg");
  assert.equal(brandSrc("lockup", "dark"), "/assets/brand/callidus-lockup.svg");
  assert.equal(brandSrc("mark", undefined), "/assets/brand/callidus-mark.svg");
});

test("a interface troca o asset pelo tema, sem filtro no lockup", () => {
  const chat = fs.readFileSync(new URL("web/static/assets/app/components/chat.js", root), "utf8");
  const sidebar = fs.readFileSync(new URL("web/static/assets/app/components/sidebar.js", root), "utf8");
  const css = fs.readFileSync(new URL("web/static/assets/app/style.css", root), "utf8");
  assert.match(chat, /brandSrc\('mark', state\.theme\)/);
  assert.match(sidebar, /brandSrc\('lockup', state\.theme\)/);
  assert.doesNotMatch(css, /brand-lockup[\s\S]{0,180}brightness/);
});

test("a resposta da etapa final aparece quando a raiz ainda não a recebeu", () => {
  const message = {
    consolidated_result_json: null,
    status: "PLANNING",
  };
  const children = [
    {
      status: "PENDING",
      updated_at: "2026-10-21T16:58:49",
      metadata_json: { final_answer: true },
      consolidated_result_json: { markdown: "não deve aparecer" },
    },
    {
      status: "COMPLETED",
      updated_at: "2026-10-21T16:59:10",
      metadata_json: { final_answer: true, model_operation: true },
      consolidated_result_json: { final_answer: true, markdown: "  O jogo está na pasta.  " },
    },
  ];
  assert.equal(visibleFinalAnswer(message, children), "O jogo está na pasta.");
});

test("o texto já gravado na raiz tem precedência sobre o da etapa", () => {
  const message = { consolidated_result_json: { final_answer: "Texto da raiz" } };
  const children = [
    {
      status: "COMPLETED",
      metadata_json: { final_answer: true },
      consolidated_result_json: { markdown: "Texto da etapa" },
    },
  ];
  assert.equal(visibleFinalAnswer(message, children), "Texto da raiz");
  assert.equal(visibleFinalAnswer({ consolidated_result_json: { final_answer: true } }, []), "");
});
