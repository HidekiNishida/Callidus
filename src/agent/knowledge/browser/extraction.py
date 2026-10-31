"""
Arquivo: src/agent/knowledge/browser/extraction.py
Nome: extraction.py
Propósito: extração de conteúdo útil de páginas web (artigos, código, documentação).
Responsabilidade: camada de infraestrutura — limpa HTML e extrai conteúdo semântico.
Componentes: ContentExtractor, extract_main_content, extract_code_blocks, extract_links.
Dependências: playwright, bs4 (opcional), re.
Observações: não executa JavaScript; foca em conteúdo já renderizado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page


@dataclass
class ExtractedContent:
    """Conteúdo extraído de uma página."""

    url: str
    title: str
    main_text: str
    code_blocks: list[dict[str, str]]
    links: list[dict[str, str]]
    headings: list[dict[str, str]]
    meta: dict[str, Any]
    raw_html: str


class ContentExtractor:
    """Extrator de conteúdo semântico de páginas web."""

    # Seletores para remover (ruído)
    NOISE_SELECTORS = [
        "nav", "header", "footer", "aside",
        ".sidebar", ".navigation", ".menu", ".breadcrumb",
        ".advertisement", ".ads", ".promo", ".banner",
        ".cookie-banner", ".consent", ".gdpr",
        ".social-share", ".share-buttons",
        ".comments", "#comments", ".comment-section",
        ".related-posts", ".recommended",
        "script", "style", "noscript",
        "[role='banner']", "[role='navigation']", "[role='complementary']",
    ]

    # Seletores para conteúdo principal (prioridade)
    CONTENT_SELECTORS = [
        "main",
        "article",
        "[role='main']",
        ".main-content",
        ".content",
        ".post-content",
        ".article-content",
        ".entry-content",
        ".documentation-content",
        "#content",
        "#main",
    ]

    def __init__(self, page: Page) -> None:
        self.page = page

    async def extract(self, url: str | None = None) -> ExtractedContent:
        """Extrai conteúdo completo da página atual."""
        if url:
            await self.page.goto(url, wait_until="domcontentloaded")

        # Obter HTML renderizado
        html = await self.page.content()
        current_url = self.page.url

        # Remover ruído via JavaScript
        await self._remove_noise()

        # Extrair título
        title = await self.page.title()

        # Extrair texto principal
        main_text = await self._extract_main_text()

        # Extrair blocos de código
        code_blocks = await self._extract_code_blocks()

        # Extrair links
        links = await self._extract_links(current_url)

        # Extrair headings
        headings = await self._extract_headings()

        # Extrair meta tags
        meta = await self._extract_meta()

        return ExtractedContent(
            url=current_url,
            title=title,
            main_text=main_text,
            code_blocks=code_blocks,
            links=links,
            headings=headings,
            meta=meta,
            raw_html=html,
        )

    async def _remove_noise(self) -> None:
        """Remove elementos de ruído do DOM."""
        for selector in self.NOISE_SELECTORS:
            try:
                await self.page.eval_on_selector_all(
                    selector,
                    "elements => elements.forEach(el => el.remove())"
                )
            except Exception:
                pass

    async def _extract_main_text(self) -> str:
        """Extrai texto do conteúdo principal."""
        # Tentar seletores de conteúdo por prioridade
        for selector in self.CONTENT_SELECTORS:
            try:
                text = await self.page.inner_text(selector)
                if text and len(text.strip()) > 200:
                    return self._clean_text(text)
            except Exception:
                continue

        # Fallback: body inteiro
        try:
            text = await self.page.inner_text("body")
            return self._clean_text(text)
        except Exception:
            return ""

    async def _extract_code_blocks(self) -> list[dict[str, str]]:
        """Extrai blocos de código com linguagem."""
        blocks = []

        try:
            # Múltiplos seletores para código
            code_elements = await self.page.query_selector_all(
                "pre code, pre.highlight code, .code-block code, "
                ".highlight pre, .language-python, .language-javascript, "
                ".language-typescript, .language-bash, .language-shell, "
                "[class*='language-'], [class*='lang-']"
            )

            for elem in code_elements:
                try:
                    code = await elem.inner_text()
                    if not code or len(code.strip()) < 10:
                        continue

                    # Tentar detectar linguagem
                    language = "unknown"
                    parent = await elem.evaluate_handle("el => el.parentElement")
                    if parent:
                        class_attr = await parent.get_attribute("class")
                        if class_attr:
                            # language-python, lang-py, etc.
                            match = re.search(r"(?:language|lang)-(\w+)", class_attr)
                            if match:
                                language = match.group(1)

                    blocks.append({
                        "language": language,
                        "code": code.strip(),
                    })
                except Exception:
                    continue
        except Exception:
            pass

        return blocks

    async def _extract_links(self, base_url: str) -> list[dict[str, str]]:
        """Extrai links relevantes da página."""
        links = []

        try:
            anchors = await self.page.query_selector_all("a[href]")
            for a in anchors:
                try:
                    href = await a.get_attribute("href")
                    text = await a.inner_text()
                    if not href or not text:
                        continue

                    # Resolver URL relativa
                    full_url = urljoin(base_url, href)

                    # Filtrar links internos/externos relevantes
                    parsed = urlparse(full_url)
                    if parsed.scheme not in ("http", "https"):
                        continue

                    links.append({
                        "url": full_url,
                        "text": text.strip()[:200],
                        "internal": parsed.netloc == urlparse(base_url).netloc,
                    })
                except Exception:
                    continue
        except Exception:
            pass

        # Deduplicar por URL
        seen = set()
        unique = []
        for link in links:
            if link["url"] not in seen:
                seen.add(link["url"])
                unique.append(link)

        return unique[:100]  # Limitar

    async def _extract_headings(self) -> list[dict[str, str]]:
        """Extrai estrutura de headings (h1-h6)."""
        headings = []

        try:
            for level in range(1, 7):
                elements = await self.page.query_selector_all(f"h{level}")
                for elem in elements:
                    try:
                        text = await elem.inner_text()
                        if text:
                            headings.append({
                                "level": level,
                                "text": text.strip(),
                            })
                    except Exception:
                        continue
        except Exception:
            pass

        return headings

    async def _extract_meta(self) -> dict[str, Any]:
        """Extrai meta tags relevantes."""
        meta = {}

        try:
            # Meta tags padrão
            meta_tags = await self.page.query_selector_all("meta[name], meta[property]")
            for tag in meta_tags:
                try:
                    name = await tag.get_attribute("name") or await tag.get_attribute("property")
                    content = await tag.get_attribute("content")
                    if name and content:
                        meta[name] = content
                except Exception:
                    continue
        except Exception:
            pass

        return meta

    def _clean_text(self, text: str) -> str:
        """Limpa texto removendo excesso de whitespace."""
        # Normalizar whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\r", "", text)
        return text.strip()


async def extract_from_url(page: Page, url: str) -> ExtractedContent:
    """Função helper para extrair conteúdo de uma URL."""
    extractor = ContentExtractor(page)
    return await extractor.extract(url)


async def extract_search_results(page: Page, query: str) -> list[dict[str, str]]:
    """Extrai resultados de uma página de busca (DuckDuckGo, Google, etc.)."""
    results = []

    try:
        # Seletores comuns para resultados de busca
        selectors = [
            "article[data-testid='result']",
            ".result",
            ".results .result",
            "[data-result]",
            ".organic-result",
            ".g",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    for elem in elements[:20]:
                        try:
                            # Tentar extrair título e link
                            title_elem = await elem.query_selector("h2, h3, .title, a")
                            link_elem = await elem.query_selector("a[href]")
                            snippet_elem = await elem.query_selector(".snippet, .description, .summary, p")

                            title = await title_elem.inner_text() if title_elem else ""
                            url = await link_elem.get_attribute("href") if link_elem else ""
                            snippet = await snippet_elem.inner_text() if snippet_elem else ""

                            if title and url:
                                results.append({
                                    "title": title.strip(),
                                    "url": url,
                                    "snippet": snippet.strip()[:300],
                                })
                        except Exception:
                            continue
                    break  # Usar primeiro seletor que funcionar
            except Exception:
                continue
    except Exception:
        pass

    return results