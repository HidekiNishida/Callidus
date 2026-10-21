/**
 * Arquivo: web/static/assets/app/ui.js
 * Nome: ui.js
 * Propósito: ícones, markdown leve e formatadores compartilhados pelos componentes.
 * Responsabilidade: frontend/apresentação — funções puras de formatação e tradução de eventos.
 * Componentes: ICONS, icon(), escapeHtml(), renderMarkdown(), describeActivity(), summarizeActivity(),
 *   diffLines(), helpers de rótulo e tempo.
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

/**
 * Acopla explicações (`work.explained`, pensamento) ao item operacional seguinte.
 *
 * A narração chega no stream antes da ferramenta ou do modelo que ela descreve.
 * Mantém a ordem temporal dentro de `activity-items`, sem uma lista separada no topo.
 *
 * @param {Array<object>} activity Entradas já descritas, na ordem recebida.
 * @returns {Array<object>} Linhas do feed; cada operação pode carregar `narrations`.
 */
export function integrateNarrative(activity) {
  const rows = [];
  let pending = [];
  for (const item of activity || []) {
    if (!item) continue;
    if (NARRATIVE_KINDS.has(item.kind)) {
      pending.push(item);
      continue;
    }
    rows.push({ ...item, narrations: pending.length ? pending : [] });
    pending = [];
  }
  if (pending.length && rows.length) {
    const last = rows[rows.length - 1];
    last.narrations = [...(last.narrations || []), ...pending];
  } else if (pending.length) {
    for (const note of pending) {
      rows.push({
        ...note,
        kind: "narrative",
        icon: note.icon || "spark",
        narrations: [],
        narrativeOnly: true,
      });
    }
  }
  return rows;
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
        title: `Chamando o modelo ${data.model || ""}`.trim(),
        detail: data.streaming ? "resposta em tempo real" : "resposta completa",
        explanation: `inferência no ${data.provider || "provedor"}`,
      };
    case "agent.output.completed":
      return {
        ...base,
        kind: "model",
        icon: "check",
        title: `Resposta do modelo (${data.chars ?? 0} caracteres)`,
        detail: data.tool_calls?.length ? `${data.tool_calls.length} chamada(s) de ferramenta` : "",
        explanation: "o modelo respondeu",
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

