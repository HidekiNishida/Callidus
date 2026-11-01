/**
 * Arquivo: tests/web/e2e.mjs
 * Nome: e2e.mjs
 * Propósito: teste end-to-end da interface com navegador real (Playwright) e servidor FastAPI isolado.
 * Responsabilidade: validar que a interface monta e funciona com backend disponível, indisponível,
 * parcial e lento, sem travamento nem carregamento infinito.
 * Componentes: servidor uvicorn subprocesso, navegador Chromium, Vue injetado via CDN,
 * cenários A (normal), B (offline), C (parcial), D (timeout), E (storage bloqueado), F (navegação).
 * Dependências: playwright (chromium), uvicorn (subprocesso), fetch (Node).
 * Observações: roda o servidor com banco SQLite temporário; não toca no agent.db real do usuário.
 * Não faz parte de `node --test tests/web/*.test.mjs` (roda servidor e navegador).
 */
import { chromium } from "playwright";
import { spawn } from "child_process";
import { rmSync, mkdirSync, writeFileSync, appendFileSync } from "fs";
import { join } from "path";

const PORT = Number(process.env.E2E_PORT || 8799);
const ROOT = process.cwd();
const DB_PATH = join(ROOT, "tests", "web", "e2e-agent.db");
const BASE_URL = `http://127.0.0.1:${PORT}`;
const VUE_URL = "https://unpkg.com/vue@3.5.44/dist/vue.global.prod.js";
const LOG = "/tmp/e2e-progress.txt";

let server = null;
let vueSource = null;
let failures = 0;

async function fetchVue() {
  const res = await fetch(VUE_URL);
  const ab = await res.arrayBuffer();
  vueSource = Buffer.from(ab);
  plog(`vue carregado: ${vueSource.length} bytes`);
}

function plog(msg) {
  try { appendFileSync(LOG, `[${new Date().toISOString()}] ${msg}\n`); } catch {}
}

function report(name, ok, detail = "") {
  const mark = ok ? "✔" : "✖";
  if (!ok) failures += 1;
  console.log(`${mark} ${name}${detail ? ` — ${detail}` : ""}`);
}

async function waitForServer(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${BASE_URL}/health`);
      if (res.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`Servidor não subiu em ${BASE_URL} após ${timeoutMs}ms`);
}

async function startServer() {
  plog("startServer: iniciando uvicorn");
  rmSync(DB_PATH, { force: true });
  mkdirSync(join(ROOT, "tests", "web"), { recursive: true });
  const uvicornBin = process.env.VIRTUAL_ENV
    ? join(process.env.VIRTUAL_ENV, "bin", "uvicorn")
    : "uvicorn";
  server = spawn(uvicornBin, ["agent.api.main:app", "--host", "127.0.0.1", "--port", String(PORT)], {
    cwd: ROOT,
    env: {
      ...process.env,
      PYTHONPATH: join(ROOT, "src"),
      CALLIDUS_DATABASE_URL: `sqlite:///${DB_PATH}`,
      CALLIDUS_API_PORT: String(PORT),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stderr.on("data", (d) => process.stderr.write(`[uvicorn] ${d}`));
  await waitForServer();
  plog("startServer: uvicorn pronto");
}

async function stopServer() {
  if (server) {
    try { server.kill("SIGTERM"); } catch {}
    try { await new Promise((r) => setTimeout(r, 500)); } catch {}
    if (!server.killed) server.kill("SIGKILL");
    server = null;
  }
  try { rmSync(DB_PATH, { force: true }); } catch {}
}

/**
 * Lê o estado de inicialização exposto em `window.__callidus.state`.
 */
async function readInitState(page) {
  return await page.evaluate(() => {
    const w = window.__callidus;
    if (!w || !w.state) return null;
    const i = w.state.initialization || {};
    return {
      bootstrap: i.bootstrap,
      api: i.api,
      degraded: i.degraded,
      errors: i.errors,
      interface: i.interface,
      projects: i.projects,
      providers: i.providers,
      health: i.health,
      ready: w.state.ready,
    };
  });
}

/**
 * Injeta o Vue 3 no lugar do arquivo vendored inexistente no repositório.
 */
function injectVue(page) {
  page.route(`${BASE_URL}/assets/vendor/vue.global.prod.js`, async (route) => {
    await route.fulfill({ body: vueSource, contentType: "application/javascript" });
  });
}

/**
 * Aborta requisições de API (mesma origem), simulando backend fora do ar.
 */
function blockApiRoutes(page) {
  for (const p of ["/projects", "/conversations", "/config/ui-defaults", "/health", "/providers", "/providers/config"]) {
    page.route(`${BASE_URL}${p}`, (route) => route.abort());
  }
}

/**
 * Demora a resposta de uma rota para forçar timeout do cliente.
 */
function delayRoute(page, path, ms) {
  page.route(`${BASE_URL}${path}`, async (route) => {
    await new Promise((r) => setTimeout(r, ms));
    await route.continue();
  });
}

/**
 * Aguarda a montagem da Vue e devolve o estado de inicialização.
 */
async function mountAndCheck(page) {
  await page.waitForFunction(() => {
    const app = document.querySelector("#app");
    return app && (app.querySelector(".shell") || app.querySelector(".boot.error") || app.querySelector(".boot"));
  }, { timeout: 15000 });
  return await readInitState(page);
}

async function scenarioANormal() {
  const browser = await chromium.launch({ headless: true });
  plog("A: browser lançado");
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  plog("A: page criada, vue injetado");
  let ok = true;
  let detail = "";
  try {
    plog("A: goto");
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    plog("A: goto ok");
    const init = await mountAndCheck(page);
    plog("A: mountAndCheck ok");
    const loading = await page.locator(".boot").first().isVisible().catch(() => false);
    if (loading) { ok = false; detail = "ainda em carregamento após montagem"; }
    const shell = await page.locator(".shell").isVisible().catch(() => false);
    if (!shell) { ok = false; detail = "interface shell não montada"; }
    if (init && init.bootstrap !== "ready" && init.bootstrap !== "degraded") {
      ok = false; detail = `bootstrap inesperado: ${init.bootstrap}`;
    }
    if (init && init.ready !== true) { ok = false; detail = `state.ready não é true: ${init.ready}`; }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("A — backend disponível: interface monta e inicializa", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function scenarioBOffline() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  blockApiRoutes(page);
  let ok = true;
  let detail = "";
  try {
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    const init = await mountAndCheck(page);
    const loading = await page.locator(".boot").first().isVisible().catch(() => false);
    if (loading) { ok = false; detail = "ficou travada em carregamento com API offline"; }
    const shell = await page.locator(".shell").isVisible().catch(() => false);
    if (!shell) { ok = false; detail = "interface não montada com API offline"; }
    if (init && init.bootstrap !== "degraded" && init.bootstrap !== "error") {
      ok = false; detail = `bootstrap esperado degraded/error, obteve ${init.bootstrap}`;
    }
    if (init && init.api !== "offline" && init.api !== "partial") {
      ok = false; detail = `api esperado offline/partial, obteve ${init.api}`;
    }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("B — backend indisponível: interface monta, modo offline/degradado", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function scenarioCPartial() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  page.route(`${BASE_URL}/projects`, (route) => route.abort());
  let ok = true;
  let detail = "";
  try {
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    const init = await mountAndCheck(page);
    const loading = await page.locator(".boot").first().isVisible().catch(() => false);
    if (loading) { ok = false; detail = "travada em carregamento com API parcial"; }
    if (init && init.bootstrap !== "degraded" && init.bootstrap !== "ready") {
      ok = false; detail = `bootstrap inesperado (parcial): ${init.bootstrap}`;
    }
    if (init && init.providers !== "ready" && init.providers !== "empty") {
      ok = false; detail = `provedores não preservados (parcial): ${init.providers}`;
    }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("C — API parcial: projetos falham, provedores preservados", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function scenarioDTimeout() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  delayRoute(page, "/projects", 30000);
  let ok = true;
  let detail = "";
  try {
    const start = Date.now();
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    await mountAndCheck(page);
    const elapsed = Date.now() - start;
    if (elapsed > 12000) { ok = false; detail = `bootstrap demorou ${elapsed}ms (timeout não aplicado)`; }
    const loading = await page.locator(".boot").first().isVisible().catch(() => false);
    if (loading) { ok = false; detail = "carregamento infinito apesar de timeout"; }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("D — timeout: bootstrap conclui em tempo limitado", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function scenarioEStorageBlocked() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  let ok = true;
  let detail = "";
  try {
    await page.addInitScript(() => {
      const blocked = new Proxy({}, {
        get() { throw new SecurityError("bloqueado"); },
        set() { throw new SecurityError("bloqueado"); },
      });
      Object.defineProperty(window, "localStorage", { value: blocked, configurable: true });
    });
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    const init = await mountAndCheck(page);
    const loading = await page.locator(".boot").first().isVisible().catch(() => false);
    if (loading) { ok = false; detail = "travada em carregamento com storage bloqueado"; }
    const shell = await page.locator(".shell").isVisible().catch(() => false);
    if (!shell) { ok = false; detail = "interface não montada com storage bloqueado"; }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("E — storage bloqueado: interface monta normalmente", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function scenarioFNavigation() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[console] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[page] ${e.message}`));
  injectVue(page);
  let ok = true;
  let detail = "";
  try {
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    await mountAndCheck(page);
    const providersNav = page.locator(".bottom-nav button").filter((el) => el.innerText().includes("Provedores")).first();
    if ((await providersNav.count()) > 0) {
      await providersNav.click();
      await page.waitForTimeout(1000);
    }
    const shell = await page.locator(".shell").isVisible().catch(() => false);
    if (!shell) { ok = false; detail = "interface sumiu após navegação"; }
  } catch (e) {
    ok = false; detail = e.message;
  }
  await browser.close();
  report("F — navegação: telas principais abrem sem erro", ok, detail ? `${detail} | console: ${consoleErrors.join("; ")}` : `console: ${consoleErrors.join("; ")}`);
  return ok;
}

async function main() {
  console.log(`\n🧪 E2E Callidus — servidor em ${BASE_URL}\n`);
  plog("main: iniciando");
  await fetchVue();
  await startServer();
  try {
    plog("main: cenario A");
    await scenarioANormal();
    plog("main: cenario B");
    await scenarioBOffline();
    plog("main: cenario C");
    await scenarioCPartial();
    plog("main: cenario D");
    await scenarioDTimeout();
    plog("main: cenario E");
    await scenarioEStorageBlocked();
    plog("main: cenario F");
    await scenarioFNavigation();
  } finally {
    await stopServer();
  }
  console.log(`\n${failures === 0 ? "✅" : "❌"} E2E: ${failures === 0 ? "todos os cenários passaram" : `${failures} cenário(s) falharam`}\n`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error("E2E falhou inesperadamente:", e);
  (async () => { await stopServer(); })();
  process.exit(1);
});
