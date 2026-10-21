/**
 * Arquivo: web/static/assets/app/tools-report.js
 * Nome: tools-report.js
 * Propósito: resumir ferramentas, dependências ausentes, diagnóstico e skills para o painel.
 * Responsabilidade: frontend/apresentação — texto legível a partir das respostas da API.
 * Componentes: formatToolsReport.
 * Dependências: nenhuma.
 * Observações: não fala com a rede; o store busca os dados e passa o objeto pronto.
 */

/**
 * Resume o diagnóstico de ferramentas para a aba Ferramentas.
 *
 * @param {{tools?: object|null, availability?: object|null, diagnosis?: object|null, skills?: object|null}} report
 * @returns {string} Texto com famílias, dependências ausentes e skills.
 */
export function formatToolsReport(report) {
  const lines = [];
  const availability = report?.availability;
  const diagnosis = report?.diagnosis;
  const skills = report?.skills;
  const tools = report?.tools?.tools || [];
  if (typeof diagnosis?.summary === "string" && diagnosis.summary) {
    lines.push(diagnosis.summary);
    lines.push("");
  } else if (diagnosis?.system) {
    const system = diagnosis.system;
    lines.push(`Sistema: ${system.os || system.system || "desconhecido"}`.trim());
    lines.push("");
  }
  if (availability) {
    const total = availability.count ?? tools.length;
    lines.push(`Ferramentas: ${availability.available ?? "?"} disponíveis de ${total}.`);
    const missing = availability.missing || [];
    if (missing.length) {
      lines.push("Dependências ausentes:");
      for (const item of missing.slice(0, 12)) {
        const hint = (item.hints || [])[0] || (item.missing || []).join(", ");
        lines.push(`- ${item.tool}: ${hint || "requisito ausente"}`);
      }
      if (missing.length > 12) lines.push(`- … e mais ${missing.length - 12}`);
    } else {
      lines.push("Nenhuma dependência obrigatória ausente.");
    }
    lines.push("");
  }
  const byFamily = new Map();
  for (const spec of tools) {
    const family = spec.family || "outras";
    if (!byFamily.has(family)) byFamily.set(family, []);
    byFamily.get(family).push(spec.id);
  }
  if (byFamily.size) {
    lines.push("Famílias:");
    for (const family of [...byFamily.keys()].sort()) {
      lines.push(`- ${family}: ${byFamily.get(family).sort().join(", ")}`);
    }
    lines.push("");
  }
  if (skills) {
    const count = skills.count ?? (skills.skills || []).length;
    lines.push(`Skills instaladas: ${count} em ${skills.root || "data/skills"}.`);
    for (const skill of (skills.skills || []).slice(0, 8)) {
      lines.push(`- ${skill.name} ${skill.version || ""} (${skill.state || "sem estado"})`.replace(/\s+/g, " ").trim());
    }
  }
  if (!lines.length) return "Não foi possível ler as ferramentas do servidor.";
  return lines.join("\n").trim();
}
