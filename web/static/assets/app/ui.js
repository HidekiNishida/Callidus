/**
 * Arquivo: web/static/assets/app/ui.js
 * Nome: ui.js
 * Propósito: ícones, markdown leve e formatadores compartilhados pelos componentes.
 * Responsabilidade: frontend/apresentação — funções puras de formatação e tradução de eventos.
 * Componentes: ICONS, icon(), escapeHtml(), renderMarkdown(), describeActivity(), integrateNarrative(),
 *   mergeActivity(), mergeNarration(), summarizeActivity(), diffLines(), brandSrc(), visibleFinalAnswer(), inferenceView(),
 *   runStatusOf(), runIsActive(), liveRunFor(),
 *   helpers de rótulo e tempo.
 * Dependências: nenhuma (módulo puro, sem DOM e sem API).
 * Observações: o HTML do markdown é escapado antes de qualquer marcação — o conteúdo do modelo
 * nunca vira HTML cru.
 */

/** Ícones em SVG (viewBox 0 0 16 16) usados pela interface. */
export const ICONS = {
  plus: '<path d="M8 3v10M3 8h10"/>',
  play: '<path d="M5 3.5v9l8-4.5-8-4.5z"/>',
  pause: '<path d="M5 3.5h2.2v9H5zM8.8 3.5H11v9H8.8z"/>',
  stop: '<rect x="4" y="4" width="8" height="8" rx="1"/>',
  panel: '<rect x="2.5" y="3" width="11" height="10" rx="1"/><path d="M8 3v10"/>',
  paperclip: '<path d="M6 8.5l4.2-4.2a2 2 0 0 1 2.8 2.8L7.2 13a3 3 0 0 1-4.2-4.2l5.6-5.6"/>',
  wrench: '<path d="M10.5 3.2a2.4 2.4 0 0 0-3.2 3.2L3.2 10.5 5.5 12.8l4.1-4.1a2.4 2.4 0 0 0 3.2-3.2L11 7.3 8.7 5l1.8-1.8z"/>',
  send: '<path d="M8 13V3M4 7l4-4 4 4"/>',
  file: '<path d="M4 2.5h5l3 3V13.5H4z"/><path d="M9 2.5V6h3"/>',
  refresh: '<path d="M13 8a5 5 0 1 1-1.4-3.4"/><path d="M13 2.5V5.5H10"/>',
  check: '<path d="M3 8.5l3.2 3.2L13 4.5"/>',
  diff: '<path d="M4 3h8M4 8h8M4 13h5"/>',
  layers: '<path d="M8 2.5l6 3-6 3-6-3 6-3zM2 8l6 3 6-3M2 11.5l6 3 6-3"/>',
  chart: '<path d="M3 13V8M8 13V3M13 13V6"/>',
  share: '<circle cx="4" cy="8" r="1.4"/><circle cx="12" cy="4" r="1.4"/><circle cx="12" cy="12" r="1.4"/><path d="M5.3 7.2l5.4-2.4M5.3 8.8l5.4 2.4"/>',
  plug: '<path d="M6 2.5v3M10 2.5v3M4.5 6h7v2.2a3.5 3.5 0 0 1-7 0zM8 11.7V14"/>',
  spark: '<path d="M8 1.8l1.2 3.6L13 6.6 9.2 8l-1.2 3.6L6.8 8 3 6.6l3.8-1.2z"/>',
  terminal: '<path d="M3 4l4 4-4 4M8 12h5"/>',
  search: '<circle cx="7" cy="7" r="3.2"/><path d="M9.5 9.5L13 13"/>',
  pencil: '<path d="M10 3.5l2.5 2.5L6 12.5H3.5V10z"/>',
  folder: '<path d="M2.5 4.5h4l1.2 1.5H13.5v7H2.5z"/>',
  alert: '<path d="M8 2.5l6 11H2zM8 7v3M8 12h.01"/>',
  circle: '<circle cx="8" cy="8" r="3"/>',
  clock: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2 1.2"/>',
  chat: '<path d="M2.5 3.5h11v7h-6l-3.2 2.6V10.5H2.5z"/>',
  cog: '<circle cx="8" cy="8" r="2.4"/><path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7L3.6 3.6"/>',
  moon: '<path d="M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5z"/>',
  sun: '<circle cx="8" cy="8" r="3.2"/><path d="M8 1.2v1.4M8 13.4v1.4M14.8 8h-1.4M2.6 8H1.2M12.8 3.2l-1 1M4.2 11.8l-1 1M12.8 12.8l-1-1M4.2 4.2l-1-1"/>',
  key: '<circle cx="5.5" cy="6" r="2.8"/><path d="M7.6 8.1L13 13.5M11 11.5l1.2-1.2M9.4 9.9l1.2-1.2"/>',
  trash: '<path d="M3 4.5h10M6 4.5V3h4v1.5M4.5 4.5l.6 9h5.8l.6-9"/>',
  keyboard: '<rect x="1.5" y="4" width="13" height="8" rx="1.5"/><path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M4 9.5h.01M6.5 9.5h.01M9 9.5h.01M11.5 9.5h.01M5 11h6"/>',
  info: '<circle cx="8" cy="8" r="6"/><path d="M8 7.2v4M8 5h.01"/>',
  plug2: '<path d="M6 2.5v3M10 2.5v3M4.5 6h7v2.2a3.5 3.5 0 0 1-7 0zM8 11.7V14"/>',
  globe: '<circle cx="8" cy="8" r="5.6"/><path d="M2.6 8h10.8M8 2.4c1.6 1.7 2.4 3.6 2.4 5.6S9.6 12 8 13.6C6.4 12 5.6 10 5.6 8s.8-4 2.4-5.6z"/>',
  chevron: '<path d="M6 4l4 4-4 4"/>',
  down: '<path d="M4 6l4 4 4-4"/>',
  upload: '<path d="M8 3v10M4 7l4-4 4 4"/>',
  branch: '<circle cx="4.5" cy="4" r="1.6"/><circle cx="4.5" cy="12" r="1.6"/><circle cx="11.5" cy="8" r="1.6"/><path d="M4.5 5.6v4.8M6.1 4.7c3 .3 4 1.4 4 2.2M6.1 11.3c3-.3 4-1.4 4-2.2"/>',
  server: '<rect x="2.5" y="3" width="11" height="4" rx="1"/><rect x="2.5" y="9" width="11" height="4" rx="1"/><path d="M5 5h.01M5 11h.01"/>',
  layout: '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>',
  activity: '<path d="M3 10l3-3 2 2 3-4 2 4"/><path d="M13 10V6"/><path d="M3 10v-4"/>',
  "bar-chart": '<rect x="3" y="9" width="3" height="4" rx="0.5"/><rect x="7" y="5" width="3" height="8" rx="0.5"/><rect x="11" y="2" width="3" height="11" rx="0.5"/>',
  "alert-circle": '<circle cx="8" cy="8" r="6"/><path d="M8 4v5M8 11h.01"/>',
  history: '<path d="M8 2.5l6 11H2zM8 7v3M8 11h.01"/><path d="M8 12.5A4.5 4.5 0 0 0 12.5 8"/>',
};

/**
 * Monta o SVG de um ícone.
 *
 * @param {string} name Nome do ícone em `ICONS`.
 * @param {number} [size] Lado do quadrado do SVG, em pixels.
 * @returns {string} O HTML do ícone; cai no ícone "circle" quando o nome não existe.
 */
export function icon(name, size = 16) {
  const path = ICONS[name] || ICONS.circle;
  return `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

/**
 * Escapa um texto para ser inserido em HTML.
 *
 * @param {*} text Texto a escapar.
 * @returns {string} O texto escapado (nulo e indefinido viram string vazia).
 */
export function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Converte o markdown da resposta do agente em HTML.
 *
 * @param {string} text Markdown de origem.
 * @returns {string} O HTML correspondente (títulos, listas, tabelas, código, citações, links).
 * Observações: o HTML é escapado antes de qualquer marcação — o conteúdo do modelo nunca vira HTML cru.
 */
export function renderMarkdown(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    // Bloco de código
    if (/^\s*```/.test(line)) {
      const lang = line.trim().slice(3).trim();
      const buffer = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        buffer.push(lines[index]);
        index += 1;
      }
      index += 1;
      out.push(
        `<pre class="md-code"${lang ? ` data-lang="${escapeHtml(lang)}"` : ""}><code>${escapeHtml(buffer.join("\n"))}</code></pre>`,
      );
      continue;
    }

    // Tabela (cabeçalho + separador)
    if (isTableRow(line) && isTableSeparator(lines[index + 1] || "")) {
      const header = splitTableRow(line);
      const align = splitTableRow(lines[index + 1]).map((cell) => {
        const left = cell.startsWith(":");
        const right = cell.endsWith(":");
        if (left && right) return "center";
        if (right) return "right";
        return "left";
      });
      index += 2;
      const rows = [];
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      const head = header
        .map((cell, position) => `<th style="text-align:${align[position] || "left"}">${inline(cell)}</th>`)
        .join("");
      const body = rows
        .map(
          (row) =>
            `<tr>${row
              .map((cell, position) => `<td style="text-align:${align[position] || "left"}">${inline(cell)}</td>`)
              .join("")}</tr>`,
        )
        .join("");
      out.push(`<div class="md-table-wrap"><table class="md-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
      continue;
    }

    // Título
    const heading = line.match(/^\s*(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      const level = Math.min(6, heading[1].length + 2);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    // Linha horizontal
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      out.push("<hr />");
      index += 1;
      continue;
    }

    // Citação
    if (/^\s*>\s?/.test(line)) {
      const buffer = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        buffer.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      out.push(`<blockquote>${renderMarkdown(buffer.join("\n"))}</blockquote>`);
      continue;
    }

    // Lista (com aninhamento por indentação)
    if (isListItem(line)) {
      const items = [];
      while (index < lines.length && (isListItem(lines[index]) || (lines[index].trim() && items.length && /\s{2,}/.test(lines[index])))) {
        const current = lines[index];
        const match = current.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (match) {
          items.push({ indent: match[1].length, ordered: /\d/.test(match[2]), text: match[3] });
        } else if (items.length) {
          items[items.length - 1].text += ` ${current.trim()}`;
        }
        index += 1;
      }
      out.push(renderList(items));
      continue;
    }

    // Parágrafo
    const buffer = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isListItem(lines[index]) &&
      !/^\s*(#{1,6})\s+/.test(lines[index]) &&
      !/^\s*```/.test(lines[index]) &&
      !/^\s*>\s?/.test(lines[index]) &&
      !isTableRow(lines[index])
    ) {
      buffer.push(lines[index]);
      index += 1;
    }
    if (buffer.length) {
      out.push(`<p>${inline(buffer.join("\n")).replace(/\n/g, "<br />")}</p>`);
    } else {
      index += 1;
    }
  }

  return out.join("");
}

/**
 * Reconhece um item de lista (com marcador `-`, `*`, `+` ou numeração).
 *
 * @param {string} line Linha de markdown.
 * @returns {boolean} `true` quando a linha começa um item de lista.
 */
function isListItem(line) {
  return /^\s*([-*+]|\d+[.)])\s+/.test(line);
}

/**
 * Reconhece uma linha de tabela do markdown.
 *
 * @param {string} line Linha de markdown.
 * @returns {boolean} `true` quando a linha contém pipes e tem conteúdo suficiente.
 */
function isTableRow(line) {
  return line.includes("|") && line.trim().length > 2;
}

/**
 * Reconhece a linha separadora de uma tabela do markdown.
 *
 * @param {string} line Linha de markdown.
 * @returns {boolean} `true` quando a linha separa as colunas de um cabeçalho.
 */
function isTableSeparator(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
}

/**
 * Divide uma linha de tabela em suas células.
 *
 * @param {string} line Linha de markdown.
 * @returns {string[]} As células, já sem os pipes das bordas e sem espaços.
 */
function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

/**
 * Renderiza uma lista do markdown respeitando o aninhamento por indentação.
 *
 * @param {Array<{indent: number, ordered: boolean, text: string}>} items Itens já extraídos.
 * @returns {string} O HTML da lista.
 */
function renderList(items) {
  if (!items.length) return "";
  let index = 0;

  // Níveis por indentação: cada subnível entra dentro do <li> do item anterior.
  function level(indent) {
    let html = "";
    let tag = null;
    while (index < items.length) {
      const item = items[index];
      if (item.indent < indent) break;
      if (item.indent > indent) {
        const nested = level(item.indent);
        if (nested) html = html.replace(/<\/li>$/, `${nested}</li>`);
        continue;
      }
      const wanted = item.ordered ? "ol" : "ul";
      if (tag && tag !== wanted) {
        html += `</${tag}>`;
        tag = null;
      }
      if (!tag) {
        tag = wanted;
        html += `<${tag}>`;
      }
      html += `<li>${inline(item.text)}`;
      index += 1;
      if (index < items.length && items[index].indent > item.indent) {
        html += level(items[index].indent);
      }
      html += `</li>`;
    }
    if (tag) html += `</${tag}>`;
    return html;
  }

  const base = Math.min(...items.map((item) => item.indent));
  return `<div class="md-list">${level(base)}</div>`;
}

/**
 * Aplica as marcações dentro de uma linha (código, links, imagens, ênfase, riscado).
 *
 * @param {string} text Texto já escapado ou a escapar.
 * @returns {string} O HTML da linha.
 */
function inline(text) {
  const codes = [];
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, (_match, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1" loading="lazy" />');
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  out = out.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  out = out.replace(/(^|[\s(])_([^_\n]+)_/g, "$1<em>$2</em>");
  out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  out = out.replace(/\u0000(\d+)\u0000/g, (_match, position) => `<code>${codes[Number(position)]}</code>`);
  return out;
}

/**
 * Formata um carimbo de tempo como hora local curta.
 *
 * @param {string} iso Carimbo ISO do servidor.
 * @returns {string} A hora (hh:mm), ou string vazia quando o carimbo é ausente ou inválido.
 */
export function stamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Resume quanto tempo atrás aconteceu algo ("agora", "5 min", "3 h", "2 d").
 *
 * @param {string} iso Carimbo ISO do servidor.
 * @returns {string} O tempo relativo, ou string vazia quando o carimbo é ausente ou inválido.
 */
export function ago(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  if (diff < 60) return "agora";
  if (diff < 3600) return `${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h`;
  return `${Math.floor(diff / 86400)} d`;
}

/** Status em que a tarefa ainda está sendo trabalhada. */
export const BUSY_STATUSES = ["PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"];

/** Rótulos em português dos status de tarefa. */
export const STATUS_LABEL = {
  PENDING: "Pendente",
  PLANNING: "Planejando",
  READY: "Pronto",
  RUNNING: "Executando",
  VERIFYING: "Verificando",
  RETRY_PENDING: "Repetindo",
  BLOCKED: "Bloqueado",
  COMPLETED: "Concluído",
  FAILED: "Falhou",
  CANCELLED: "Cancelado",
};

/** Ícone associado a cada status de tarefa. */
export const STATUS_ICON = {
  PLANNING: "spark",
  READY: "clock",
  RUNNING: "play",
  VERIFYING: "refresh",
  RETRY_PENDING: "refresh",
  BLOCKED: "alert",
  COMPLETED: "check",
  FAILED: "alert",
  CANCELLED: "stop",
  PENDING: "circle",
};

/** Ícone associado a cada ferramenta do agente. */
export const TOOL_ICON = {
  read_file: "file",
  write_file: "pencil",
  edit_file: "pencil",
  search_grep: "search",
  list_dir: "folder",
  glob_files: "search",
  run_command: "terminal",
  run_script: "terminal",
  run_tests: "check",
  browser: "globe",
  remember: "layers",
  mcp_tool: "plug",
  verification: "check",
  modelo: "spark",
};

/**
 * Descobre a ferramenta associada a uma tarefa.
 *
 * @param {object} task Tarefa do servidor.
 * @returns {string} O nome da ferramenta, ou string vazia quando a tarefa não é de ferramenta.
 */
export function toolOf(task) {
  const meta = task?.metadata_json || {};
  if (meta.tool) return meta.tool;
  if (meta.verification) return "verification";
  if (meta.model_operation) return "modelo";
  return "";
}

/**
 * Devolve o título de exibição de uma tarefa.
 *
 * @param {object} task Tarefa do servidor.
 * @returns {string} O `display_title` ou, na falta dele, o `title`.
 */
export function titleOf(task) {
  return task?.display_title || task?.title || "";
}

/**
 * Traduz o status de uma tarefa para o rótulo em português.
 *
 * @param {string} status Status do servidor.
 * @returns {string} O rótulo, ou "—" quando o status é desconhecido.
 */
export function statusLabel(status) {
  return STATUS_LABEL[status] || status || "—";
}

/**
 * Monta o rótulo de modelo e provedor usado na conversa.
 *
 * @param {object} task Tarefa do servidor (pode ser nulo).
 * @param {object|null} [live] Retrato `live` do stream (pode ser nulo).
 * @returns {string} "provedor · modelo", apenas o modelo, ou string vazia quando não há modelo.
 */
export function modelLabel(task, live) {
  const modelId = (task?.metadata_json || {}).model_id || live?.model?.model_id || "";
  const provider = live?.model?.provider || (task?.metadata_json || {}).provider || "";
  if (!modelId) return "";
  return provider ? `${provider} · ${modelId}` : modelId;
}

/**
 * Escolhe o plural correto para uma contagem.
 *
 * @param {number} n Quantidade.
 * @param {string} one Forma no singular.
 * @param {string} many Forma no plural.
 * @returns {string} O texto "n forma".
 */
export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// ── Atividade em tempo real (traduzida para português) ─────────────────────

/** Rótulo em português de cada ferramenta, como o usuário lê no feed. */
export const TOOL_LABEL = {
  read_file: "Leitura de arquivo",
  write_file: "Escrita de arquivo",
  edit_file: "Edição de arquivo",
  delete_file: "Remoção de arquivo",
  move_file: "Movimentação de arquivo",
  make_dir: "Criação de pasta",
  list_dir: "Listagem de pasta",
  glob_files: "Busca de arquivos",
  search_grep: "Busca no código",
  run_command: "Comando",
  run_script: "Script",
  run_tests: "Testes",
  run_pytest: "Testes",
  browser: "Navegador",
  remember: "Memória",
  mcp_tool: "Ferramenta MCP",
  verification: "Verificação",
  modelo: "Modelo",
};

/** Ícone em português de cada ferramenta, usado no feed de atividade. */
export const TOOL_ICON_PT = {
  read_file: "file",
  write_file: "pencil",
  edit_file: "pencil",
  delete_file: "trash",
  move_file: "folder",
  make_dir: "folder",
  list_dir: "folder",
  glob_files: "search",
  search_grep: "search",
  run_command: "terminal",
  run_script: "terminal",
  run_tests: "check",
  run_pytest: "check",
  browser: "globe",
  remember: "layers",
  mcp_tool: "plug",
  verification: "check",
};

/**
 * Resume os argumentos de uma ferramenta em uma linha curta.
 *
 * @param {string} tool Nome da ferramenta.
 * @param {object} args Argumentos informados pelo servidor.
 * @returns {string} O comando, o caminho ou o padrão (truncado em 140 caracteres), ou string vazia.
 */
export function toolArgsSummary(tool, args) {
  if (!args || typeof args !== "object") return "";
  if (tool === "run_command" || tool === "run_script" || tool === "run_tests") {
    const cmd = args.command;
    const text = Array.isArray(cmd) ? cmd.join(" ") : String(cmd || "");
    return text.length > 140 ? `${text.slice(0, 140)}…` : text;
  }
  if (args.path) return String(args.path);
  if (args.pattern) return String(args.pattern);
  return "";
}

/** Tipos que explicam o trabalho. A resposta do modelo e as ferramentas ficam de fora. */
export const NARRATIVE_KINDS = new Set(["activity", "decision", "result", "alert", "error", "thought"]);

const NARRATIVE_LABEL = {
  activity: "Atividade",
  decision: "Decisão",
  result: "Resultado",
  alert: "Alerta",
  error: "Erro",
  thought: "Pensamento",
};

/**
 * Acopla a narração ao item operacional seguinte.
 *
 * `note_thought` grava a mesma frase em `agent.thought` e, em seguida, em
 * `work.explained`. As duas entradas são o mesmo relato: fica a explicação.
 * Um pensamento sem explicação correspondente continua no item.
 *
 * @param {Array<object>} activity Entradas já descritas, na ordem recebida.
 * @returns {Array<object>} Linhas do feed; cada uma pode carregar `narrations`.
 */
export function integrateNarrative(activity) {
  const rows = [];
  let pending = [];
  for (const item of activity || []) {
    if (!item) continue;
    if (item.kind === "narration") {
      // A fala do agente é uma linha própria da linha do tempo. O objeto vai sem cópia: o
      // texto que cresce a cada fragmento é lido só pelo componente da narração.
      rows.push(item);
      continue;
    }
    if (NARRATIVE_KINDS.has(item.kind)) {
      const prev = pending[pending.length - 1];
      if (prev?.kind === "thought" && item.kind !== "thought" && prev.title === item.title) pending.pop();
      pending.push(item);
      continue;
    }
    rows.push({ ...item, narrations: pending.length ? pending.slice() : item.narrations || [] });
    pending = [];
  }
  const host = [...rows].reverse().find((row) => row.kind !== "narration");
  if (pending.length && host) {
    const last = host;
    const existing = last.narrations || [];
    const seen = new Set(existing.map((note) => note.eventId || note.id));
    last.narrations = [...existing, ...pending.filter((note) => !seen.has(note.eventId || note.id))];
  } else if (pending.length) {
    for (const note of pending) {
      rows.push({
        ...note,
        kind: "narrative",
        icon: note.icon || "spark",
        title: NARRATIVE_LABEL[note.kind] || "Narração",
        explanation: "",
        narrations: [note],
      });
    }
  }
  return rows;
}

/**
 * Inclui uma entrada no feed da mensagem, atualizando a que já existe.
 *
 * O mesmo `eventId` substitui o conteúdo. A saída de comando acumula no comando
 * em andamento. Identidades diferentes continuam lado a lado.
 *
 * @param {Array<object>} feed Feed já existente da mensagem.
 * @param {object|null} entry Entrada descrita.
 * @returns {void}
 */
export function mergeActivity(feed, entry) {
  if (!entry) return;
  if (entry.narrationId) {
    mergeNarration(feed, entry);
    return;
  }
  if (entry.eventId) {
    const index = feed.findIndex((item) => item.eventId === entry.eventId && item.kind === entry.kind);
    if (index >= 0) {
      const prev = feed[index];
      feed.splice(index, 1, { ...prev, ...entry, id: prev.id });
      return;
    }
  }
  if (entry.callId) {
    const index = feed.findIndex((item) => item.callId === entry.callId && item.kind === entry.kind);
    if (index >= 0 && entry.kind !== "command-output") {
      const prev = feed[index];
      feed.splice(index, 1, { ...prev, ...entry, id: prev.id });
      return;
    }
    if (entry.kind === "command-output") {
      const target = feed.find((item) => item.callId === entry.callId && item.kind === "command");
      if (target) {
        target.output = `${target.output || ""}${entry.detail || ""}`;
        return;
      }
    }
  }
  feed.push(entry);
}

/**
 * Comprimento em code points — a unidade dos deslocamentos do servidor (Python).
 * `String.length` conta unidades UTF-16 e erraria a conta em emojis.
 *
 * @param {string} text Texto.
 * @returns {number} Número de code points.
 */
function codePoints(text) {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/**
 * Aplica um evento de narração à linha correspondente, sem recriar a linha.
 *
 * O texto cresce no próprio objeto (só o componente da narração redesenha). O
 * deslocamento de cada fragmento decide o que é novo: trecho já recebido (reconexão,
 * replay do anel) é ignorado e nada se duplica; um buraco espera o texto do fim.
 *
 * @param {Array<object>} feed Feed da mensagem.
 * @param {object} entry Entrada de narração descrita por `describeActivity`.
 * @returns {object} A linha de narração atualizada.
 */
export function mergeNarration(feed, entry) {
  let row = feed.find((item) => item.kind === "narration" && item.narrationId === entry.narrationId);
  if (!row) {
    row = {
      id: `narration-${entry.narrationId}`,
      kind: "narration",
      narrationId: entry.narrationId,
      icon: "spark",
      title: "Narração",
      text: "",
      received: 0,
      gap: false,
      status: "running",
      narrativeOnly: true,
      taskId: entry.taskId || null,
      streamed: true,
    };
    feed.push(row);
    // O objeto guardado no feed reativo é o que deve mudar daqui em diante.
    row = feed[feed.length - 1];
  }
  if (entry.delta != null) {
    if (row.status !== "running") return row;
    const offset = Number(entry.offset) || 0;
    const text = String(entry.delta || "");
    if (offset > row.received) {
      row.gap = true;
      return row;
    }
    const skip = row.received - offset;
    const fresh = skip > 0 ? Array.from(text).slice(skip).join("") : text;
    if (fresh) {
      row.text += fresh;
      row.received += codePoints(fresh);
    }
    return row;
  }
  if (entry.taskId && !row.taskId) row.taskId = entry.taskId;
  if (entry.streamed === false) row.streamed = false;
  if (entry.seed != null && row.status === "running" && codePoints(entry.seed) > row.received) {
    // Texto já publicado antes desta conexão (foto ao vivo do servidor).
    row.text = entry.seed;
    row.received = codePoints(entry.seed);
    row.gap = false;
  }
  if (entry.final != null) {
    row.text = entry.final;
    row.received = codePoints(entry.final);
    row.gap = false;
    row.status = entry.status || "ok";
    row.truncated = Boolean(entry.truncated);
  }
  return row;
}

/**
 * O item nasce como a preferência do feed manda.
 *
 * `"aberto"` mostra a seção de todos os itens. `"fechado"` deixa todos recolhidos.
 * Uma linha só narrativa não abre: ela não tem seção expansível.
 *
 * @param {object} entry Entrada do feed.
 * @param {string} [mode] `"aberto"` ou `"fechado"`.
 * @returns {boolean} `true` quando a seção expansível começa visível.
 */
export function activityStartsOpen(entry, mode = "fechado") {
  if (entry?.narrativeOnly) return false;
  return mode === "aberto";
}

/**
 * Estado de expansão de um item, com a escolha do usuário acima do padrão.
 *
 * @param {object} entry Entrada do feed.
 * @param {Set<string>} openIds Ids que o usuário abriu.
 * @param {Set<string>} closedIds Ids que o usuário fechou.
 * @param {string} [mode] `"aberto"` ou `"fechado"`.
 * @returns {boolean} `true` quando a seção expansível está visível.
 */
export function activityIsOpen(entry, openIds, closedIds, mode = "fechado") {
  if (!entry) return false;
  if (closedIds?.has(entry.id)) return false;
  if (openIds?.has(entry.id)) return true;
  return activityStartsOpen(entry, mode);
}

/**
 * Abre ou fecha a seção do item sem alterar a narração guardada.
 *
 * @param {object} entry Entrada do feed.
 * @param {Set<string>} openIds Ids que o usuário abriu.
 * @param {Set<string>} closedIds Ids que o usuário fechou.
 * @param {string} [mode] `"aberto"` ou `"fechado"`.
 * @returns {void}
 */
export function toggleActivity(entry, openIds, closedIds, mode = "fechado") {
  if (!entry) return;
  if (activityIsOpen(entry, openIds, closedIds, mode)) {
    closedIds.add(entry.id);
    openIds.delete(entry.id);
  } else {
    openIds.add(entry.id);
    closedIds.delete(entry.id);
  }
}

/**
 * Tira da faixa de pensamentos o texto que já é narração do item.
 *
 * @param {Array<object>} thoughts Pensamentos da visão ao vivo.
 * @param {Iterable<string>} narrationTitles Textos já acoplados ao feed.
 * @returns {Array<object>} Pensamentos que não repetem a narração.
 */
export function thoughtsOutsideNarration(thoughts, narrationTitles) {
  const shown = narrationTitles instanceof Set ? narrationTitles : new Set(narrationTitles || []);
  const noisy = /^(Planejando|Pronta para executar|Concluída sem teste|Liberada|Aguardando|Começando)/;
  return (thoughts || []).filter((item) => {
    const text = item?.text || "";
    return !noisy.test(text) && !shown.has(text);
  });
}

/**
 * @deprecated Prefer `integrateNarrative`. Mantido para testes de classificação de tipos.
 */
export function splitFeed(activity) {
  const narrative = [];
  const operations = [];
  for (const item of activity || []) {
    if (item && NARRATIVE_KINDS.has(item.kind)) narrative.push(item);
    else if (item) operations.push(item);
  }
  return { narrative, operations };
}

/**
 * Converte um evento do stream em uma entrada de atividade (título, detalhe, estado).
 *
 * @param {object} event Envelope do stream.
 * @returns {object|null} A entrada de atividade, ou `null` quando o evento não é de atividade.
 */
export function describeActivity(event) {
  const data = event?.data || {};
  const type = event?.type || "";
  const id = `${type}-${data.call_id || data.output_id || data.path || Math.random().toString(36).slice(2)}`;
  const base = { id, status: "ok", kind: "tool", icon: "wrench", title: "", detail: "", explanation: "" };

  switch (type) {
    case "agent.narration.started":
      return {
        ...base,
        narrationId: data.narration_id,
        taskId: event.task_id || null,
        streamed: data.streamed !== false,
      };
    case "agent.narration.delta":
      return {
        ...base,
        narrationId: data.narration_id,
        taskId: event.task_id || null,
        delta: String(data.text || ""),
        offset: Number(data.offset) || 0,
      };
    case "agent.narration.completed":
      return {
        ...base,
        narrationId: data.narration_id,
        taskId: event.task_id || null,
        final: String(data.content || ""),
        truncated: Boolean(data.truncated),
        status: data.status === "completed" ? "ok" : data.status === "interrupted" ? "interrupted" : "error",
      };
    case "agent.thought": {
      const text = data.text || data.thought || "Pensando";
      return { ...base, kind: "thought", icon: "spark", title: text, explanation: "raciocínio do agente" };
    }
    case "work.explained": {
      const category = ["activity", "decision", "result", "alert", "error"].includes(data.category)
        ? data.category
        : "activity";
      const text = data.text || "";
      if (!text) return null;
      return {
        ...base,
        kind: category,
        icon: category === "error" || category === "alert" ? "alert" : category === "result" ? "check" : "spark",
        title: text,
        detail: data.phase || "",
        explanation: text,
        status: category === "error" ? "error" : "ok",
      };
    }
    case "agent.started":
      return {
        ...base,
        kind: "model",
        icon: "spark",
        output_id: data.output_id,
        inference_id: data.inference_id,
        title: `Chamando o modelo ${data.model || ""}`.trim(),
        detail: data.streaming ? "resposta em tempo real" : "resposta completa",
        explanation: `inferência no ${data.provider || "provedor"}`,
      };
    case "agent.output.completed":
      return {
        ...base,
        kind: "model",
        icon: "check",
        output_id: data.output_id,
        inference_id: data.inference_id,
        title: `Resposta do modelo (${data.chars ?? 0} caracteres)`,
        detail: data.tool_calls?.length ? `${data.tool_calls.length} chamada(s) de ferramenta` : "",
        explanation: "o modelo respondeu",
      };
    case "agent.output.failed":
      return {
        ...base,
        kind: "model",
        icon: "alert",
        output_id: data.output_id,
        inference_id: data.inference_id,
        status: "error",
        title: `Falha na inferência${data.error ? ": " + data.error : ""}`,
        detail: data.error || "",
        explanation: data.cancelled ? "cancelada" : "falhou",
      };
    case "tool.started": {
      const label = TOOL_LABEL[data.tool] || data.tool || "Ferramenta";
      const detail = toolArgsSummary(data.tool, data.args);
      return {
        ...base,
        kind: "tool",
        icon: TOOL_ICON_PT[data.tool] || "wrench",
        title: label,
        detail,
        explanation: detail ? `${label} em ${detail}` : label,
        callId: data.call_id,
        status: "running",
      };
    }
    case "tool.completed": {
      const label = TOOL_LABEL[data.tool] || data.tool || "Ferramenta";
      const summary = data.summary || {};
      const bits = [];
      if (summary.lines != null) bits.push(`${summary.lines} linha(s)`);
      if (summary.bytes != null) bits.push(`${summary.bytes} byte(s)`);
      if (summary.added != null) bits.push(`+${summary.added} −${summary.removed ?? 0}`);
      return {
        ...base,
        kind: "tool",
        icon: "check",
        title: `${label} concluída`,
        detail: bits.join(" · "),
        explanation: bits.length ? `${label}: ${bits.join(", ")}` : `${label} concluída`,
        callId: data.call_id,
        duration: data.duration_ms,
      };
    }
    case "tool.failed": {
      const label = TOOL_LABEL[data.tool] || data.tool || "Ferramenta";
      return {
        ...base,
        kind: "tool",
        icon: "alert",
        title: `${label} falhou`,
        detail: data.error || "",
        explanation: data.error ? `erro: ${data.error}` : "falhou",
        callId: data.call_id,
        status: "error",
      };
    }
    case "command.started":
      return {
        ...base,
        kind: "command",
        icon: "terminal",
        title: "Comando",
        detail: data.command || "",
        explanation: data.command ? `rodou \`${data.command}\`${data.cwd ? ` em ${data.cwd}` : ""}` : "comando",
        callId: data.call_id,
        status: "running",
      };
    case "command.output":
      return {
        ...base,
        kind: "command-output",
        icon: "terminal",
        title: "Saída do comando",
        detail: data.text || "",
        callId: data.call_id,
        status: "running",
      };
    case "command.completed":
      return {
        ...base,
        kind: "command",
        icon: "check",
        title: "Comando concluído",
        detail: data.exit_code === 0 ? "código de saída 0" : `código de saída ${data.exit_code}`,
        explanation: data.exit_code === 0 ? "terminou bem" : `terminou com erro ${data.exit_code}`,
        callId: data.call_id,
        duration: data.duration_ms,
        status: data.exit_code === 0 ? "ok" : "error",
      };
    case "command.failed":
      return {
        ...base,
        kind: "command",
        icon: "alert",
        title: "Comando falhou",
        detail: data.error || "",
        explanation: data.error || "falhou",
        callId: data.call_id,
        status: "error",
      };
    case "test.started":
      return {
        ...base,
        kind: "command",
        icon: "check",
        title: "Testes",
        detail: data.command || "",
        explanation: data.command ? `rodou \`${data.command}\`` : "rodou os testes",
        callId: data.call_id,
        status: "running",
      };
    case "test.completed": {
      const counts = data.counts || {};
      const bits = [];
      if (counts.passed != null) bits.push(`${counts.passed} passou`);
      if (counts.failed != null) bits.push(`${counts.failed} falhou`);
      if (counts.skipped != null) bits.push(`${counts.skipped} pulou`);
      return {
        ...base,
        kind: "command",
        icon: "check",
        title: "Testes concluídos",
        detail: bits.join(" · "),
        explanation: bits.length ? `testes: ${bits.join(", ")}` : "testes concluídos",
        callId: data.call_id,
        duration: data.duration_ms,
      };
    }
    case "test.failed":
      return {
        ...base,
        kind: "command",
        icon: "alert",
        title: "Testes falharam",
        detail: data.error || "",
        explanation: data.error || "os testes falharam",
        callId: data.call_id,
        status: "error",
      };
    case "file.read":
      return {
        ...base,
        kind: "file",
        icon: "file",
        title: "Leu arquivo",
        detail: data.path || "",
        explanation: data.lines != null ? `leu ${data.lines} linha(s) de ${data.path}` : `leu ${data.path}`,
        stats: data.total_lines != null ? `${data.lines ?? 0} de ${data.total_lines} linhas` : "",
      };
    case "file.created":
      return {
        ...base,
        kind: "file",
        icon: "pencil",
        title: "Criou arquivo",
        detail: data.path || "",
        explanation: data.added != null ? `criou ${data.path} (+${data.added} −${data.removed ?? 0})` : `criou ${data.path}`,
        diff: data.diff ? { text: data.diff, added: data.added, removed: data.removed, truncated: data.truncated } : null,
        sensitive: Boolean(data.sensitive),
        stats: data.added != null ? `+${data.added} −${data.removed ?? 0}` : "",
      };
    case "file.changed":
      return {
        ...base,
        kind: "file",
        icon: "pencil",
        title: "Alterou arquivo",
        detail: data.path || "",
        explanation: data.added != null ? `alterou ${data.path} (+${data.added} −${data.removed ?? 0})` : `alterou ${data.path}`,
        diff: data.diff ? { text: data.diff, added: data.added, removed: data.removed, truncated: data.truncated } : null,
        sensitive: Boolean(data.sensitive),
        stats: data.added != null ? `+${data.added} −${data.removed ?? 0}` : "",
      };
    case "file.deleted":
      return {
        ...base,
        kind: "file",
        icon: "trash",
        title: "Removeu arquivo",
        detail: data.path || "",
        explanation: `removeu ${data.path}`,
        stats: data.moved_to ? `movido para ${data.moved_to}` : "",
      };
    case "verification.started":
      return {
        ...base,
        kind: "verify",
        icon: "refresh",
        title: `Verificação ${data.verifier || ""}`.trim(),
        explanation: `rodou a verificação ${data.verifier || ""}`,
        status: "running",
      };
    case "verification.passed":
      return {
        ...base,
        kind: "verify",
        icon: "check",
        title: `Verificação ${data.verifier || ""} aprovada`,
        explanation: "a verificação passou",
        detail: data.summary || "",
      };
    case "verification.failed":
      return {
        ...base,
        kind: "verify",
        icon: "alert",
        title: `Verificação ${data.verifier || ""} reprovada`,
        detail: data.summary || "",
        explanation: data.summary ? `reprovou: ${data.summary}` : "reprovou",
        status: "error",
      };
    default:
      return null;
  }
}

/**
 * Resume o que foi feito no turno: contagens por tipo de ação.
 *
 * @param {Array<object>} entries Entradas de atividade do turno.
 * @returns {object} Contagem de leituras, escritas, comandos, testes, ferramentas, arquivos e pensamentos.
 */
export function summarizeActivity(entries) {
  const summary = { leituras: 0, escritas: 0, comandos: 0, testes: 0, ferramentas: 0, arquivos: 0, thoughts: 0 };
  for (const entry of entries || []) {
    if (entry.kind === "file") {
      if (entry.title.startsWith("Leu")) summary.leituras += 1;
      else summary.escritas += 1;
      summary.arquivos += 1;
    } else if (entry.kind === "command") {
      if (entry.title.toLowerCase().includes("teste")) summary.testes += 1;
      else summary.comandos += 1;
    } else if (entry.kind === "tool") {
      summary.ferramentas += 1;
    } else if (entry.kind === "thought") {
      summary.thoughts += 1;
    }
  }
  return summary;
}

/**
 * Quebra um diff em linhas com marcação de acréscimo, remoção, hunk ou contexto.
 *
 * @param {string} text Diff cru (formato unified).
 * @returns {Array<{type: string, text: string}>} As linhas classificadas.
 */
const MEASUREMENT_LABELS = {
  exact: "informado pelo provedor",
  estimate: "estimativa",
  partial: "parcial",
  unavailable: "indisponível",
};

/**
 * Nome legível da qualidade de uma contagem de tokens.
 *
 * @param {string} measurement `exact`, `estimate`, `partial` ou `unavailable`.
 * @returns {string} O rótulo em português.
 */
export function measurementLabel(measurement) {
  return MEASUREMENT_LABELS[measurement] || MEASUREMENT_LABELS.unavailable;
}

/**
 * Formata uma contagem que pode estar ausente.
 *
 * @param {{value?: number|null, measurement?: string}|number|null} entry Valor embalado ou número cru.
 * @returns {string} O texto para a interface. Ausência não vira zero.
 */
export function formatTokenCount(entry) {
  if (entry == null) return "indisponível";
  if (typeof entry === "number") return String(entry);
  if (entry.value == null) return measurementLabel(entry.measurement);
  return `${entry.value} (${measurementLabel(entry.measurement)})`;
}

/**
 * Percentual de ocupação, ou texto de indisponível quando a base não existe.
 *
 * @param {number|null|undefined} ratio Fração entre 0 e 1.
 * @returns {string} Percentual inteiro ou "indisponível".
 */
export function formatRatio(ratio) {
  if (ratio == null || Number.isNaN(Number(ratio))) return "indisponível";
  return `${Math.round(Number(ratio) * 100)}%`;
}

/**
 * Faixa de consumo para o alerta do painel.
 *
 * @param {string} level `normal`, `elevated`, `reduce`, `stop` ou `unavailable`.
 * @returns {string} Frase curta, ou string vazia quando não há alerta.
 */
export function budgetAlert(level) {
  if (level === "elevated") return "Consumo elevado da execução.";
  if (level === "reduce") return "Consumo alto: o contexto das próximas chamadas será reduzido.";
  if (level === "stop") return "Orçamento operacional esgotado. A reserva de conclusão permanece protegida.";
  return "";
}

/** Símbolo e lockup: o tema claro usa tinta escura; o escuro, tinta clara. A estrela permanece azul. */
const BRAND_SRC = {
  mark: {
    dark: "/assets/brand/callidus-mark.svg",
    light: "/assets/brand/callidus-mark-light.svg",
  },
  lockup: {
    dark: "/assets/brand/callidus-lockup.svg",
    light: "/assets/brand/callidus-lockup-light.svg",
  },
};

/**
 * Caminho do asset de marca para o tema ativo.
 *
 * @param {string} kind `"mark"` (símbolo) ou `"lockup"` (símbolo + nome).
 * @param {string} theme `"light"` ou `"dark"`.
 * @returns {string} URL servida em `/assets/brand/`.
 * Observações: `<img>` não herda `currentColor`; cada tema tem o seu SVG.
 */
export function brandSrc(kind, theme) {
  const pair = BRAND_SRC[kind] || BRAND_SRC.mark;
  return theme === "light" ? pair.light : pair.dark;
}

/**
 * Texto da resposta final visível na conversa.
 *
 * @param {object} root Tarefa raiz da mensagem.
 * @param {Array<object>} [children] Subtarefas diretas da raiz.
 * @returns {string} Markdown da resposta, ou string vazia quando ainda não há uma.
 * Observações: a raiz guarda o texto em `final_answer`. Se o run parou antes de
 * copiar, a etapa concluída de resposta final ainda tem o texto em `markdown`.
 */
export function visibleFinalAnswer(root, children = []) {
  const direct = root?.consolidated_result_json?.final_answer;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const ready = (children || []).filter((task) => {
    if (task?.status !== "COMPLETED") return false;
    if (!task.metadata_json?.final_answer) return false;
    const markdown = task.consolidated_result_json?.markdown;
    return typeof markdown === "string" && markdown.trim();
  });
  ready.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  return ready.length ? ready[0].consolidated_result_json.markdown.trim() : "";
}

export function diffLines(text) {
  return String(text || "")
    .split("\n")
    .map((line) => ({
      type: line.startsWith("+") && !line.startsWith("+++")
        ? "add"
        : line.startsWith("-") && !line.startsWith("---")
          ? "del"
          : line.startsWith("@@")
            ? "hunk"
            : "ctx",
      text: line,
    }));
}


/** Cores dos segmentos da barra de composição do contexto, por ordem de categoria. */
export const INFERENCE_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

/**
 * Achata a composição do contexto, venha ela como lista ou agrupada por categoria.
 *
 * @param {Array|object|null} raw `components` do detalhe (lista) ou a resposta de
 *   `/inferences/{id}/components` (`{categories: [{components: [...]}]}`).
 * @returns {Array<object>} Os componentes, um por item de contexto.
 */
export function flattenInferenceComponents(raw) {
  if (Array.isArray(raw)) return raw.filter(Boolean);
  if (raw && Array.isArray(raw.categories)) {
    return raw.categories.flatMap((group) =>
      Array.isArray(group?.components) && group.components.length
        ? group.components
        : [{ category: group?.category, tokens: group?.tokens || 0 }],
    );
  }
  return [];
}

/**
 * Monta o que o chat mostra de uma inferência: metadados, tokens e a distribuição do contexto.
 *
 * @param {object|null} detail Resposta de `/api/intelligence/inferences/{id}`.
 * @param {Array|object|null} [components] Composição carregada à parte (opcional).
 * @returns {object} Campos achatados, `components`, `segments` (um por categoria, com
 *   tokens, percentual da janela e cor) e `free` (o que sobra da janela de contexto).
 * Observações: a barra soma por categoria — o detalhe traz um componente por item, e
 * vários itens da mesma categoria virariam fatias iguais na barra. Com a janela
 * conhecida, as fatias são proporcionais a ela e o restante aparece como espaço
 * livre; sem janela, as fatias dividem a barra entre si e `free` é `null`. Tokens
 * ausentes do provedor caem na estimativa local, marcada como tal.
 */
export function inferenceView(detail, components = null) {
  const data = detail || {};
  const comps = flattenInferenceComponents(components ?? data.components);
  const byCategory = new Map();
  for (const comp of comps) {
    const key = comp.category || "outros";
    const group = byCategory.get(key) || { category: key, tokens: 0, measurements: new Set() };
    group.tokens += comp.tokens || 0;
    group.measurements.add(comp.measurement || "estimate");
    byCategory.set(key, group);
  }
  const total = comps.reduce((sum, comp) => sum + (comp.tokens || 0), 0);
  const window = data.context_window_size || 0;
  // A base é a janela; se o contexto passou dela (estimativa errada), a barra cheia é o total.
  const base = window ? Math.max(window, total) : total;
  const share = (tokens) => (base ? (tokens / base) * 100 : 0);
  const segments = Array.from(byCategory.values()).map((group, index) => ({
    category: group.category,
    tokens: group.tokens,
    width: share(group.tokens),
    pct: Math.round(share(group.tokens)),
    color: INFERENCE_COLORS[index % INFERENCE_COLORS.length],
    measurement: group.measurements.size === 1 ? [...group.measurements][0] : "partial",
  }));
  const freeTokens = window ? Math.max(0, window - total) : null;
  const free =
    freeTokens == null || !comps.length
      ? null
      : { tokens: freeTokens, width: share(freeTokens), pct: Math.round(share(freeTokens)) };
  const promptExact = data.prompt_tokens != null;
  const completionExact = data.completion_tokens != null;
  return {
    purpose: data.purpose || null,
    inference_type: data.inference_type || null,
    model: data.model || null,
    provider: data.provider || null,
    status: data.status || null,
    failure_reason: data.failure_reason || null,
    duration_ms: data.duration_ms ?? null,
    measurement: data.measurement || (comps.length ? "estimate" : "unavailable"),
    prompt_tokens: promptExact
      ? { value: data.prompt_tokens, measurement: "exact" }
      : { value: data.estimated_prompt_tokens ?? null, measurement: data.estimated_prompt_tokens != null ? "estimate" : "unavailable" },
    completion_tokens: completionExact
      ? { value: data.completion_tokens, measurement: "exact" }
      : { value: data.estimated_completion_tokens ?? null, measurement: data.estimated_completion_tokens != null ? "estimate" : "unavailable" },
    context_window_size: data.context_window_size ?? null,
    occupancy:
      data.context_window_size && (data.prompt_tokens ?? data.estimated_prompt_tokens)
        ? (data.prompt_tokens ?? data.estimated_prompt_tokens) / data.context_window_size
        : null,
    total_tokens: total,
    components: comps,
    segments,
    free,
  };
}


/**
 * Estado de uma run em maiúsculas, qualquer que seja a grafia recebida.
 *
 * @param {object|null} run Run como a API devolve (`status: "active"`).
 * @returns {string} `ACTIVE`, `PAUSED`, … ou vazio sem run.
 * Observações: a API serializa o `RunStatus` em minúsculas; a interface comparava com
 * `"ACTIVE"` e nunca achava a run em curso — sem controles e sem acompanhamento.
 */
export function runStatusOf(run) {
  return String(run?.status || "").toUpperCase();
}

/**
 * Diz se a run ainda está em curso (ativa).
 *
 * @param {object|null} run Run da API ou da interface.
 * @returns {boolean} `true` para run ativa.
 */
export function runIsActive(run) {
  return runStatusOf(run) === "ACTIVE";
}

/**
 * Run em curso (ativa ou pausada) de uma das mensagens da conversa.
 *
 * @param {Array<object>} runs Runs do workspace.
 * @param {Iterable<string>} rootIds Tarefas raiz (mensagens) da conversa aberta.
 * @returns {object|null} A mais recente, preferindo a ativa; `null` sem nenhuma.
 */
export function liveRunFor(runs, rootIds) {
  const roots = new Set(rootIds || []);
  const live = (runs || [])
    .filter((run) => roots.has(run.root_task_id) && ["ACTIVE", "PAUSED"].includes(runStatusOf(run)))
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  return live.find(runIsActive) || live[0] || null;
}
