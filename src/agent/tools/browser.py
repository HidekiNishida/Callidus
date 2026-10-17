# src/agent/tools/browser.py — navegador local, invisível ou em janela
from __future__ import annotations

import queue
import re
import threading
from urllib.parse import quote_plus

import httpx

_ALLOWED = ("http://", "https://")
_LINK = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I)
_TAG = re.compile(r"<[^>]+>")


def guard_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw.startswith(_ALLOWED):
        raise ValueError("só http e https")
    return raw


def parse_search_html(html: str, limit: int = 5) -> list[dict]:
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
    text = (query or "").strip()
    if not text:
        return {"success": False, "error": "consulta vazia"}
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(text)}"
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "agente-local"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"pesquisa indisponível: {exc}"}
    hits = parse_search_html(response.text, limit=limit)
    return {"success": True, "query": text, "results": hits, "mode": "headless"}


class BrowserSession:
    """Uma página só, numa thread, para o ciclo do agente não perder o site entre etapas."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="agent-browser", daemon=True)
        self._thread.start()

    def call(self, action: str, args: dict, *, headed: bool, timeout: float = 45) -> dict:
        box: queue.Queue = queue.Queue(maxsize=1)
        self._queue.put((action, args, headed, box))
        try:
            return box.get(timeout=timeout)
        except queue.Empty:
            return {"success": False, "error": "navegador demorou demais"}

    def _loop(self) -> None:
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
    options = {"headless": not headed}
    try:
        return playwright.chromium.launch(channel="chrome", **options)
    except Exception:
        return playwright.chromium.launch(**options)


def _act(page, action: str, args: dict, *, headed: bool) -> dict:
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
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session.call(action, args, headed=headed)
