"""
Arquivo: src/agent/knowledge/providers/github.py
Nome: github.py
Propósito: provedor de busca GitHub (repositórios, issues, código, documentação).
Responsabilidade: camada de infraestrutura — implementação do SearchProvider para GitHub API.
Componentes: GitHubProvider.
Dependências: httpx, agent.knowledge.providers.base, os.
Observações: usa GITHUB_TOKEN do ambiente se disponível para rate limit maior.
"""
from __future__ import annotations

import os
import httpx

from agent.knowledge.providers.base import SearchProvider, SearchResult, SearchProviderError


class GitHubProvider(SearchProvider):
    """Provedor de busca GitHub via REST API."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._headers = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    @property
    def name(self) -> str:
        return "github"

    @property
    def source_kind(self) -> str:
        return "github"

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

        # Determine search type from kwargs or default to repositories
        search_type = kwargs.get("type", "repositories")
        
        url_map = {
            "repositories": "https://api.github.com/search/repositories",
            "code": "https://api.github.com/search/code",
            "issues": "https://api.github.com/search/issues",
            "topics": "https://api.github.com/search/topics",
            "users": "https://api.github.com/search/users",
        }
        
        url = url_map.get(search_type, url_map["repositories"])
        params = {"q": text, "per_page": min(limit, 100)}

        try:
            async with httpx.AsyncClient(timeout=30, headers=self._headers) as client:
                response = await client.get(url, params=params)
                
                if response.status_code == 403:
                    # Rate limit
                    raise SearchProviderError("rate limit excedido", self.name, recoverable=True)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"pesquisa GitHub falhou: {exc}", self.name, recoverable=True) from exc

        data = response.json()
        items = data.get("items", [])
        
        hits: list[SearchResult] = []
        for item in items[:limit]:
            if search_type == "repositories":
                hits.append(SearchResult(
                    title=item.get("full_name", ""),
                    url=item.get("html_url", ""),
                    description=item.get("description"),
                    source=self.name,
                    published_at=item.get("created_at"),
                    author=item.get("owner", {}).get("login"),
                    credibility=0.8,
                    meta={"stars": item.get("stargazers_count"), "language": item.get("language")}
                ))
            elif search_type == "code":
                hits.append(SearchResult(
                    title=item.get("name", ""),
                    url=item.get("html_url", ""),
                    description=f"Path: {item.get('path', '')}",
                    source=self.name,
                    published_at=None,
                    author=item.get("repository", {}).get("owner", {}).get("login"),
                    credibility=0.7,
                    meta={"repository": item.get("repository", {}).get("full_name")}
                ))
            elif search_type == "issues":
                hits.append(SearchResult(
                    title=f"{item.get('repository_url', '').split('/')[-1]}#{item.get('number')}: {item.get('title', '')}",
                    url=item.get("html_url", ""),
                    description=item.get("body", "")[:200] if item.get("body") else None,
                    source=self.name,
                    published_at=item.get("created_at"),
                    author=item.get("user", {}).get("login"),
                    credibility=0.7,
                    meta={"state": item.get("state"), "labels": [l.get("name") for l in item.get("labels", [])]}
                ))
            else:
                hits.append(SearchResult(
                    title=item.get("full_name") or item.get("login") or item.get("name", ""),
                    url=item.get("html_url", ""),
                    description=item.get("description"),
                    source=self.name,
                    credibility=0.7
                ))
        return hits

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, headers=self._headers) as client:
                response = await client.get("https://api.github.com/rate_limit")
                return response.status_code == 200
        except Exception:
            return False