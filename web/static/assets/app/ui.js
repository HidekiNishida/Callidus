// web/static/assets/app/ui.js — ícones, markdown leve e formatadores

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
  plug2: '<path d="M6 2.5v3M10 2.5v3M4.5 6h7v2.2a3.5 3.5 0 0 1-7 0zM8 11.7V14"/>',
  globe: '<circle cx="8" cy="8" r="5.6"/><path d="M2.6 8h10.8M8 2.4c1.6 1.7 2.4 3.6 2.4 5.6S9.6 12 8 13.6C6.4 12 5.6 10 5.6 8s.8-4 2.4-5.6z"/>',
  chevron: '<path d="M6 4l4 4-4 4"/>',
  down: '<path d="M4 6l4 4 4-4"/>',
  upload: '<path d="M8 3v10M4 7l4-4 4 4"/>',
  branch: '<circle cx="4.5" cy="4" r="1.6"/><circle cx="4.5" cy="12" r="1.6"/><circle cx="11.5" cy="8" r="1.6"/><path d="M4.5 5.6v4.8M6.1 4.7c3 .3 4 1.4 4 2.2M6.1 11.3c3-.3 4-1.4 4-2.2"/>',
  server: '<rect x="2.5" y="3" width="11" height="4" rx="1"/><rect x="2.5" y="9" width="11" height="4" rx="1"/><path d="M5 5h.01M5 11h.01"/>',
};

export function icon(name, size = 16) {
  const path = ICONS[name] || ICONS.circle;
  return `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

export function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Markdown leve para a resposta final do agente (sem HTML cru). */
export function renderMarkdown(text) {
  const blocks = String(text ?? "").split(/\n{2,}/);
  const out = [];
  for (const block of blocks) {
    const raw = block.trim();
    if (!raw) continue;
    const heading = raw.match(/^(#{1,4})\s+(.*)$/s);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level + 2}>${inline(heading[2])}</h${level + 2}>`);
      continue;
    }
    if (/^[-*]\s+/m.test(raw) && raw.split("\n").every((line) => /^[-*]\s+/.test(line.trim()) || !line.trim())) {
      const items = raw
        .split("\n")
        .filter((line) => line.trim())
        .map((line) => `<li>${inline(line.replace(/^[-*]\s+/, ""))}</li>`)
        .join("");
      out.push(`<ul>${items}</ul>`);
      continue;
    }
    if (/^```/.test(raw)) {
      const code = raw.replace(/^```[a-z]*\n?/i, "").replace(/```$/, "");
      out.push(`<pre class="md-code"><code>${escapeHtml(code)}</code></pre>`);
      continue;
    }
    out.push(`<p>${inline(raw).replace(/\n/g, "<br>")}</p>`);
  }
  return out.join("");
}

function inline(text) {
  let value = escapeHtml(text);
  value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/(^|\s)\*([^*]+)\*/g, "$1<em>$2</em>");
  value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return value;
}

export function stamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ago(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  if (diff < 60) return "agora";
  if (diff < 3600) return `${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h`;
  return `${Math.floor(diff / 86400)} d`;
}

export const BUSY_STATUSES = ["PLANNING", "READY", "RUNNING", "VERIFYING", "RETRY_PENDING"];

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

export function toolOf(task) {
  const meta = task?.metadata_json || {};
  if (meta.tool) return meta.tool;
  if (meta.verification) return "verification";
  if (meta.model_operation) return "modelo";
  return "";
}

export function titleOf(task) {
  return task?.display_title || task?.title || "";
}

export function statusLabel(status) {
  return STATUS_LABEL[status] || status || "—";
}

/** Modelo e provedor usados na conversa (para o cabeçalho da resposta). */
export function modelLabel(task, live) {
  const modelId = (task?.metadata_json || {}).model_id || live?.model?.model_id || "";
  const provider = live?.model?.provider || (task?.metadata_json || {}).provider || "";
  if (!modelId) return "";
  return provider ? `${provider} · ${modelId}` : modelId;
}

export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}
