"""
Arquivo: src/agent/tools/browser.py
Nome: browser.py
Propósito: fornecer a navegação do agente, invisível por padrão e com janela quando pedido.
Responsabilidade: camada de infraestrutura — sessão de navegador em thread e pesquisa web por HTTP.
Componentes: guard_url, parse_search_html, search_web, BrowserSession, browser_call.
Dependências: httpx, playwright (opcional), agent.brand.
Observações: o Playwright é opcional; sem ele, a pesquisa em texto continua funcionando.
"""
from __future__ import annotations

import queue
import re
import threading
from urllib.parse import quote_plus

import httpx

from agent.brand import USER_AGENT

_ALLOWED = ("http://", "https://")
_LINK = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I)
_TAG = re.compile(r"<[^>]+>")


def guard_url(url: str) -> str:
    """Valida que a URL usa um esquema permitido.

    Args:
        url: URL a validar.

    Returns:
        A URL sem espaços nas pontas.

    Raises:
        ValueError: quando o esquema não é `http` nem `https`.
    """
    raw = (url or "").strip()
    if not raw.startswith(_ALLOWED):
        raise ValueError("só http e https")
    return raw


def parse_search_html(html: str, limit: int = 5) -> list[dict]:
    """Extrai os resultados da página de busca.

    Args:
        html: HTML devolvido pelo motor de busca.
        limit: quantidade máxima de resultados.

    Returns:
        A lista de resultados, cada um com título e URL.
    """
    found: list[dict] = []
    for href, label in _LINK.findall(html or ""):
        title = _TAG.sub("", label)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        found.append({"title": title, "url": href})
        if len(found) >= limit:
            break
    return found


def search_web(query: str, limit: int = 5) -> dict:
    """Executa uma pesquisa web sem navegador, direto por HTTP.

    Args:
        query: termo pesquisado.
        limit: quantidade máxima de resultados.

    Returns:
        Um dicionário com o sucesso, a consulta e os resultados; em falha, a mensagem de erro.
    """
    text = (query or "").strip()
    if not text:
        return {"success": False, "error": "consulta vazia"}
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(text)}"
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"pesquisa indisponível: {exc}"}
    hits = parse_search_html(response.text, limit=limit)
    return {"success": True, "query": text, "results": hits, "mode": "headless"}


class BrowserSession:
    """Uma página só, numa thread, para o ciclo do agente não perder o site entre etapas."""

    def __init__(self) -> None:
        """Monta a sessão do navegador com o modo e o diretório de trabalho."""
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="agent-browser", daemon=True)
        self._thread.start()

    def call(self, action: str, args: dict, *, headed: bool, timeout: float = 45) -> dict:
        """Enfileira uma ação do navegador e espera o resultado.

        Args:
            action: ação a executar (navegar, clicar, capturar, etc.).
            args: argumentos da ação.
            headed: quando `True`, o navegador abre em janela visível.
            timeout: tempo limite de espera, em segundos.

        Returns:
            O resultado da ação; em estouro de tempo, um dicionário com `success` falso.
        """
        box: queue.Queue = queue.Queue(maxsize=1)
        self._queue.put((action, args, headed, box))
        try:
            return box.get(timeout=timeout)
        except queue.Empty:
            return {"success": False, "error": "navegador demorou demais"}

    def _loop(self) -> None:
        """Laço da thread do navegador: abre a sessão sob demanda e executa as ações enfileiradas.

        Observações:
            Trocar entre modo visível e invisível reabre o navegador; erros são devolvidos como resultado.
        """
        playwright = None
        browser = None
        page = None
        headed_now: bool | None = None
        while True:
            action, args, headed, box = self._queue.get()
            try:
                if action == "close":
                    if browser is not None:
                        browser.close()
                    browser = None
                    page = None
                    box.put({"success": True, "closed": True})
                    continue
                if action == "search":
                    box.put(search_web(str(args.get("query") or args.get("text") or "")))
                    continue
                if playwright is None or browser is None or headed_now != headed:
                    if browser is not None:
                        browser.close()
                    from playwright.sync_api import sync_playwright

                    if playwright is None:
                        playwright = sync_playwright().start()
                    browser = _launch(playwright, headed)
                    page = browser.new_page()
                    headed_now = headed
                box.put(_act(page, action, args, headed=headed))
            except ModuleNotFoundError:
                box.put(
                    {
                        "success": False,
                        "error": "Instale o Playwright e o Chrome: pip install playwright. A pesquisa em texto continua disponível.",
                    }
                )
            except Exception as exc:
                box.put({"success": False, "error": str(exc)[:300]})


def _launch(playwright, headed: bool):
    """Abre o navegador Chromium, preferindo o Chrome instalado no sistema.

    Args:
        playwright: instância do Playwright.
        headed: quando `True`, abre janela visível.

    Returns:
        O navegador aberto.
    """
    options = {"headless": not headed}
    try:
        return playwright.chromium.launch(channel="chrome", **options)
    except Exception:
        return playwright.chromium.launch(**options)


def _act(page, action: str, args: dict, *, headed: bool) -> dict:
    """Executa uma ação sobre a página aberta.

    Args:
        page: página do Playwright.
        action: ação a executar.
        args: argumentos da ação.
        headed: quando `True`, a resposta indica o modo visível.

    Returns:
        O resultado da ação, com o modo usado; em falha, a mensagem de erro.
    """
    mode = "visible" if headed else "headless"
    if action == "navigate":
        url = guard_url(str(args.get("url") or ""))
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return {"success": True, "url": page.url, "title": page.title(), "mode": mode}
    if action == "snapshot":
        text = page.inner_text("body")[:4000]
        return {"success": True, "url": page.url, "title": page.title(), "text": text, "mode": mode}
    if action == "click":
        target = str(args.get("text") or args.get("selector") or "")
        if not target:
            return {"success": False, "error": "informe text ou selector"}
        if args.get("selector"):
            page.locator(str(args["selector"])).first.click(timeout=8000)
        else:
            page.get_by_text(target, exact=False).first.click(timeout=8000)
        return {"success": True, "clicked": target, "url": page.url, "mode": mode}
    if action == "type":
        value = str(args.get("text") or "")
        selector = str(args.get("selector") or "")
        if selector:
            page.locator(selector).first.fill(value, timeout=8000)
        else:
            page.keyboard.type(value)
        return {"success": True, "typed": len(value), "mode": mode}
    if action == "press":
        page.keyboard.press(str(args.get("key") or "Enter"))
        return {"success": True, "key": args.get("key") or "Enter", "mode": mode}
    if action == "scroll":
        page.mouse.wheel(0, int(args.get("delta") or 600))
        return {"success": True, "mode": mode}
    return {"success": False, "error": f"ação desconhecida: {action}"}


_session: BrowserSession | None = None


def browser_call(action: str, args: dict, *, headed: bool) -> dict:
    """Executa uma ação de navegador na sessão compartilhada do processo.

    Args:
        action: ação a executar.
        args: argumentos da ação.
        headed: quando `True`, o navegador abre em janela visível.

    Returns:
        O resultado da ação.
    """
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session.call(action, args, headed=headed)
