"""
Arquivo: src/agent/knowledge/providers/duckduckgo.py
Nome: duckduckgo.py
Propósito: provedor de busca DuckDuckGo usando HTTP direto (sem API key).
Responsabilidade: camada de infraestrutura — implementação do SearchProvider para DuckDuckGo.
Componentes: DuckDuckGoProvider.
Dependências: httpx, agent.knowledge.providers.base, urllib.parse.
Observações: reutiliza a lógica existente em browser.py para parsing HTML.
"""
from __future__ import annotations

import httpx
from urllib.parse import quote_plus

from agent.brand import USER_AGENT
from agent.knowledge.providers.base import SearchProvider, SearchResult, SearchProviderError

_LINK = __import__("re").compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', __import__("re").IGNORECASE)
_TAG = __import__("re").compile(r"<[^>]+>")


class DuckDuckGoProvider(SearchProvider):
    """Provedor de busca DuckDuckGo via HTML scraping."""

    @property
    def name(self) -> str:
        return "duckduckgo"

    @property
    def source_kind(self) -> str:
        return "web_search"

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        **kwargs,
    ) -> list[SearchResult]:
        text = (query or "").strip()
        if not text:
            raise SearchProviderError("consulta vazia", self.name)

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(text)}"
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"pesquisa indisponível: {exc}", self.name, recoverable=True) from exc

        hits: list[SearchResult] = []
        for href, label in _LINK.findall(response.text or ""):
            title = _TAG.sub("", label)
            title = __import__("re").sub(r"\s+", " ", title).strip()
            if not title:
                continue
            hits.append(SearchResult(title=title, url=href, source=self.name, credibility=0.6))
            if len(hits) >= limit:
                break
        return hits

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get("https://html.duckduckgo.com/html/?q=test")
                return response.status_code == 200
        except Exception:
            return False