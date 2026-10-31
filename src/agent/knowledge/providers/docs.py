"""
Arquivo: src/agent/knowledge/providers/docs.py
Nome: docs.py
Propósito: provedor de busca em documentação técnica (ReadTheDocs, GitHub Pages, etc.).
Responsabilidade: camada de infraestrutura — implementação do SearchProvider para documentação.
Componentes: DocumentationProvider.
Dependências: httpx, agent.knowledge.providers.base, urllib.parse.
Observações: usa DuckDuckGo com site: filter para buscar em domínios de documentação conhecidos.
"""
from __future__ import annotations

import httpx
from urllib.parse import quote_plus

from agent.brand import USER_AGENT
from agent.knowledge.providers.base import SearchProvider, SearchResult, SearchProviderError

_LINK = __import__("re").compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', __import__("re").IGNORECASE)
_TAG = __import__("re").compile(r"<[^>]+>")


class DocumentationProvider(SearchProvider):
    """Provedor de busca em documentação técnica via DuckDuckGo com filtros de site."""

    # Domínios de documentação conhecidos
    DOC_DOMAINS = [
        "readthedocs.io",
        "docs.python.org",
        "developer.mozilla.org",
        "docs.djangoproject.com",
        "fastapi.tiangolo.com",
        "sqlalchemy.org",
        "pydantic.dev",
        "pytest.org",
        "numpy.org",
        "pandas.pydata.org",
        "scikit-learn.org",
        "tensorflow.org",
        "pytorch.org",
        "kubernetes.io",
        "docs.docker.com",
        "docs.aws.amazon.com",
        "cloud.google.com/docs",
        "docs.microsoft.com",
        "developer.apple.com",
    ]

    def __init__(self, custom_domains: list[str] | None = None) -> None:
        self.domains = custom_domains or self.DOC_DOMAINS

    @property
    def name(self) -> str:
        return "documentation"

    @property
    def source_kind(self) -> str:
        return "documentation"

    def _build_query(self, query: str) -> str:
        """Constrói query com filtro de sites de documentação."""
        site_filters = " OR ".join(f"site:{d}" for d in self.domains)
        return f"({query}) AND ({site_filters})"

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

        full_query = self._build_query(text)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(full_query)}"
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
            hits.append(SearchResult(
                title=title,
                url=href,
                source=self.name,
                credibility=0.85,
            ))
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