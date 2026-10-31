"""
Arquivo: src/agent/knowledge/browser/session.py
Nome: session.py
Propósito: sessão de navegador persistente com perfis isolados para autenticação.
Responsabilidade: camada de infraestrutura — gerencia browser Playwright com perfis persistentes.
Componentes: BrowserProfile, AuthenticatedBrowserSession.
Dependências: playwright, pathlib, uuid.
Observações: perfis ficam em data/browser-profiles/<profile_id>/; suporta modo headless e visível.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class BrowserProfile:
    """Perfil persistente do navegador com cookies, storage e configurações."""

    def __init__(self, profile_id: str | None = None, base_dir: Path | None = None) -> None:
        self.profile_id = profile_id or uuid.uuid4().hex[:12]
        self.base_dir = base_dir or Path("data/browser-profiles")
        self.profile_dir = self.base_dir / self.profile_id
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def get_user_data_dir(self) -> str:
        return str(self.profile_dir)

    def exists(self) -> bool:
        return self.profile_dir.exists()


class AuthenticatedBrowserSession:
    """
    Sessão de navegador autenticada com perfil persistente.

    Permite:
    - Reutilizar sessões autenticadas (cookies, localStorage)
    - Múltiplos perfis isolados
    - Modo headless ou visível
    - Interação com serviços de IA (ChatGPT, Gemini, Claude)
    """

    def __init__(
        self,
        profile: BrowserProfile | None = None,
        *,
        headless: bool = True,
        viewport: dict[str, int] | None = None,
    ) -> None:
        self.profile = profile or BrowserProfile()
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 720}
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Inicializa o Playwright e abre o browser com o perfil persistente."""
        if self._initialized:
            return

        self._playwright = await async_playwright().start()

        # Usar canal Chrome se disponível para melhor compatibilidade
        try:
            self._browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile.get_user_data_dir(),
                headless=self.headless,
                viewport=self.viewport,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
        except Exception:
            # Fallback para Chromium padrão
            self._browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile.get_user_data_dir(),
                headless=self.headless,
                viewport=self.viewport,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                ],
            )

        self._context = self._browser
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._initialized = True

    async def new_page(self) -> Page:
        """Cria nova página no contexto atual."""
        if not self._initialized:
            await self.initialize()
        return await self._context.new_page()

    @property
    def page(self) -> Page:
        if not self._initialized:
            raise RuntimeError("Sessão não inicializada. Chame initialize() primeiro.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._initialized:
            raise RuntimeError("Sessão não inicializada. Chame initialize() primeiro.")
        return self._context

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout: float = 30000) -> None:
        """Navega para URL e aguarda carregamento."""
        await self.page.goto(url, wait_until=wait_until, timeout=timeout)

    async def wait_for_selector(self, selector: str, timeout: float = 10000) -> None:
        """Aguarda elemento aparecer."""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def click(self, selector: str, timeout: float = 5000) -> None:
        """Clica em elemento."""
        await self.page.click(selector, timeout=timeout)

    async def fill(self, selector: str, value: str, timeout: float = 5000) -> None:
        """Preenche campo."""
        await self.page.fill(selector, value, timeout=timeout)

    async def press(self, selector: str, key: str, timeout: float = 5000) -> None:
        """Pressiona tecla em elemento."""
        await self.page.press(selector, key, timeout=timeout)

    async def get_text(self, selector: str) -> str:
        """Obtém texto de elemento."""
        element = await self.page.query_selector(selector)
        if element:
            return await element.inner_text()
        return ""

    async def get_html(self, selector: str = "body") -> str:
        """Obtém HTML de elemento."""
        element = await self.page.query_selector(selector)
        if element:
            return await element.inner_html()
        return ""

    async def screenshot(self, path: str | None = None, full_page: bool = False) -> bytes:
        """Captura screenshot."""
        if path:
            await self.page.screenshot(path=path, full_page=full_page)
            return b""
        return await self.page.screenshot(full_page=full_page)

    async def evaluate(self, script: str, *args) -> Any:
        """Executa JavaScript na página."""
        return await self.page.evaluate(script, *args)

    async def wait_for_navigation(self, timeout: float = 30000) -> None:
        """Aguarda navegação completar."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)

    async def get_cookies(self) -> list[dict]:
        """Obtém cookies da sessão."""
        return await self.context.cookies()

    async def set_cookies(self, cookies: list[dict]) -> None:
        """Define cookies na sessão."""
        await self.context.add_cookies(cookies)

    async def close(self) -> None:
        """Fecha browser e limpa recursos."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._initialized = False

    async def __aenter__(self) -> "AuthenticatedBrowserSession":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()