/**
 * Arquivo: tests/web/tools-report.test.mjs
 * Nome: tools-report.test.mjs
 * Propósito: verificar o resumo da aba de ferramentas: famílias, dependências ausentes e skills.
 * Responsabilidade: camada de testes — texto produzido a partir de respostas sintéticas da API.
 * Componentes: formatToolsReport.
 * Dependências: web/static/assets/app/tools-report.js, node:test.
 * Observações: não sobe servidor e não fala com a rede.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatToolsReport } from "../../web/static/assets/app/tools-report.js";

test("resume famílias, dependência ausente e skill", () => {
  const text = formatToolsReport({
    diagnosis: { summary: "macos com sessão gráfica (aqua): automação de desktop e de navegador viável." },
    availability: {
      count: 2,
      available: 1,
      missing: [{ tool: "desktop_screenshot", hints: ["conceda Gravação de Tela"], missing: ["session:gui"] }],
    },
    tools: {
      tools: [
        { id: "read_file", family: "file" },
        { id: "desktop_elements", family: "desktop" },
      ],
    },
    skills: { count: 1, root: "/tmp/skills", skills: [{ name: "revisar-diff", version: "1.0.0", state: "active" }] },
  });
  assert.match(text, /sessão gráfica/);
  assert.match(text, /desktop_screenshot: conceda Gravação de Tela/);
  assert.match(text, /desktop: desktop_elements/);
  assert.match(text, /revisar-diff 1.0.0 \(active\)/);
});

test("explica quando a API não responde", () => {
  assert.equal(formatToolsReport(null), "Não foi possível ler as ferramentas do servidor.");
});
