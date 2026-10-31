"""
Arquivo: src/agent/knowledge/providers/__init__.py
Nome: __init__.py
Propósito: exportar a API de provedores de busca.
Responsabilidade: camada de infraestrutura — interface e implementações de SearchProvider.
"""
from agent.knowledge.providers.base import SearchProvider, SearchResult, SearchProviderError
from agent.knowledge.providers.duckduckgo import DuckDuckGoProvider
from agent.knowledge.providers.github import GitHubProvider
from agent.knowledge.providers.docs import DocumentationProvider

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchProviderError",
    "DuckDuckGoProvider",
    "GitHubProvider",
    "DocumentationProvider",
]