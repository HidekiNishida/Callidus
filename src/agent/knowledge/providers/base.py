"""
Arquivo: src/agent/knowledge/providers/base.py
Nome: base.py
Propósito: definir a interface comum para provedores de busca do Knowledge Engine.
Responsabilidade: camada de infraestrutura — contrato SearchProvider.
Componentes: SearchProvider, SearchResult, SearchProviderError.
Dependências: abc, typing, pydantic.
Observações: arquitetura Strategy — nova implementação = novo arquivo, sem tocar o núcleo.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


class SearchProviderError(Exception):
    """Erro base para provedores de busca."""

    def __init__(self, message: str, provider: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.recoverable = recoverable


@dataclass
class SearchResult:
    """Resultado normalizado de uma busca."""

    title: str
    url: str
    description: str | None = None
    source: str = "unknown"
    published_at: str | None = None
    author: str | None = None
    credibility: float = 0.5
    raw_content: str | None = None
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "source": self.source,
            "published_at": self.published_at,
            "author": self.author,
            "credibility": self.credibility,
            "raw_content": self.raw_content,
            "meta": self.meta,
        }


class SearchProvider(abc.ABC):
    """
    Interface comum para provedores de busca.

    Implementações:
    - DuckDuckGoProvider (já existe em browser.py)
    - GoogleSearchProvider
    - BingSearchProvider
    - GitHubSearchProvider
    - DocumentationProvider
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Nome identificador do provedor (ex.: 'duckduckgo', 'google')."""
        pass

    @property
    @abc.abstractmethod
    def source_kind(self) -> str:
        """Tipo de fonte para KnowledgeSourceModel (ex.: 'web_search', 'github')."""
        pass

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """
        Executa a busca e retorna resultados normalizados.

        Args:
            query: termo de busca
            limit: máximo de resultados
            **kwargs: parâmetros específicos do provedor

        Returns:
            Lista de SearchResult normalizados

        Raises:
            SearchProviderError: em caso de erro (recoverable indica se pode tentar outro provedor)
        """
        pass

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Verifica se o provedor está disponível."""
        pass

    def normalize_result(self, raw: dict[str, Any]) -> SearchResult:
        """Normaliza resultado bruto do provedor para SearchResult. Override se necessário."""
        return SearchResult(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            description=raw.get("description") or raw.get("snippet"),
            source=self.name,
            published_at=raw.get("published_at") or raw.get("date"),
            author=raw.get("author"),
            credibility=raw.get("credibility", 0.5),
            raw_content=raw.get("content") or raw.get("raw_content"),
            meta=raw.get("meta"),
        )