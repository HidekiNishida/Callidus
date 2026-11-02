/**
 * Arquivo: scripts/check-web-syntax.js
 * Nome: check-web-syntax.js
 * Propósito: validação sintática e de integridade de importações dos módulos JavaScript
 *            do frontend do Callidus, usando apenas recursos internos do Node.js.
 * Responsabilidade: detecção automática de erros de sintaxe (ex.: chaves/colchetes
 *            desbalanceados, vírgulas ausentes) e de importações quebradas (caminhos
 *            relativos inexistentes), impedindo a introdução de novos erros que impeçam
 *            a inicialização da interface.
 * Componentes: checkSyntax (node --check), checkImports (resolução de caminhos relativos),
 *            walkFrontend (coleta de arquivos .js), main (orquestração e saída).
 * Dependências: apenas módulos internos do Node.js (fs, path, child_process).
 * Observações: retorna código de saída diferente de zero quando encontra problemas,
 *            adequado à integração em CI. Não introduz dependências externas.
 */

import { execSync } from "child_process";
import { readFileSync, existsSync } from "fs";
import { readdir } from "fs/promises";
import { join, resolve, dirname, extname, relative } from "path";

const ROOT = resolve(process.cwd(), "web/static");
let failures = 0;
const results = [];

function log(...args) {
  console.log(...args);
}

/**
 * Coleta recursivamente todos os arquivos .js do frontend.
 *
 * @param {string} dir Diretório a percorrer.
 * @returns {Promise<string[]>} Caminhos absolutos dos arquivos JavaScript.
 */
async function walkFrontend(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walkFrontend(full)));
    } else if (entry.isFile() && extname(entry.name) === ".js") {
      files.push(full);
    }
  }
  return files;
}

/**
 * Executa a validação sintática de um arquivo com `node --check`.
 *
 * @param {string} file Caminho absoluto do arquivo.
 * @returns {{file:string, line:number|null, col:number|null, message:string}|null}
 *            Erro encontrado ou `null` quando o arquivo é válido.
 */
function checkSyntax(file) {
  try {
    execSync(`node --check ${JSON.stringify(file)}`, { stdio: "pipe" });
    return null;
  } catch (err) {
    const raw = String(err.stderr || err.message || err);
    const firstLine = raw.trim().split("\n")[0];
    const lineMatch = raw.match(/:(\d+):(\d+):/);
    const line = lineMatch ? Number(lineMatch[1]) : null;
    const col = lineMatch ? Number(lineMatch[2]) : null;
    return { file, line, col, message: firstLine };
  }
}

/**
 * Verifica a integridade das importações relativas de um arquivo.
 *
 * @param {string} file Caminho absoluto do arquivo.
 * @returns {string[]} Lista de mensagens de problemas de importação.
 */
function checkImports(file) {
  const problems = [];
  const source = readFileSync(file, "utf8");
  const baseDir = dirname(file);

  // Captura: import ... from "caminho" e import("caminho") e require("caminho")
  const importRegex = /(?:import\s+(?:[^;]*?\s+from\s+)?["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|require\s*\(\s*["']([^"']+)["']\s*\))/g;
  let match;
  while ((match = importRegex.exec(source))) {
    const spec = match[1] || match[2] || match[3];
    if (!spec || spec.startsWith("http://") || spec.startsWith("https://")) continue;
    if (spec.startsWith(".") || spec.startsWith("/")) {
      let target = resolve(baseDir, spec);
      if (!target.endsWith(".js")) {
        // Tenta com .js anexado (módulos JS podem omitir a extensão).
        if (existsSync(target + ".js")) target = target + ".js";
        else if (existsSync(target + "/index.js")) target = target + "/index.js";
      }
      if (!existsSync(target)) {
        problems.push(
          `importação não resolvida: "${spec}" (de ${relative(ROOT, file)})`,
        );
      }
    }
  }
  return problems;
}

/**
 * Orquestra a validação de todos os módulos do frontend.
 *
 * @returns {Promise<number>} Código de saída (0 = sucesso, 1 = falhas).
 */
async function main() {
  const files = (await walkFrontend(ROOT)).sort();
  log(`Validando ${files.length} módulo(s) JavaScript do frontend em ${relative(process.cwd(), ROOT)}...\n`);

  for (const file of files) {
    const rel = relative(ROOT, file);
    const syntaxErr = checkSyntax(file);
    if (syntaxErr) {
      failures += 1;
      results.push({
        kind: "sintaxe",
        file: rel,
        line: syntaxErr.line,
        col: syntaxErr.col,
        message: syntaxErr.message,
      });
      continue; // arquivo inválido: não vale a pena checar importações
    }

    const importProblems = checkImports(file);
    for (const problem of importProblems) {
      failures += 1;
      results.push({ kind: "importacao", file: rel, line: null, col: null, message: problem });
    }
  }

  log("\n=== Resultado da validação do frontend ===");
  if (failures === 0) {
    log("OK: nenhum erro sintático nem de importação encontrado.");
    return 0;
  }

  log(`FALHAS: ${failures} problema(s) encontrado(s).\n`);
  for (const r of results) {
    const loc = r.line != null ? ` (linha ${r.line}${r.col != null ? ", coluna " + r.col : ""})` : "";
    log(`- [${r.kind}] ${r.file}${loc}: ${r.message}`);
  }
  return 1;
}

main().then((code) => process.exit(code)).catch((err) => {
  console.error("Erro inesperado na validação:", err);
  process.exit(2);
});
