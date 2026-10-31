"""
Arquivo: tests/test_knowledge_providers.py
Nome: test_knowledge_providers.py
Propósito: testes dos provedores de busca.
Responsabilidade: camada de teste — verifica DuckDuckGo, GitHub, Documentation providers.
Dependências: pytest, agent.knowledge.providers.
Observações: usa mocks para evitar chamadas de rede reais.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from agent.knowledge.providers import (
    DuckDuckGoProvider,
    GitHubProvider,
    DocumentationProvider,
    SearchProviderError,
)
from agent.knowledge.providers.base import SearchResult


class TestDuckDuckGoProvider:
    """Testes do DuckDuckGoProvider."""

    @pytest.fixture
    def provider(self):
        return DuckDuckGoProvider()

    def test_name_and_source_kind(self, provider):
        assert provider.name == "duckduckgo"
        assert provider.source_kind == "web_search"

    @pytest.mark.asyncio
    async def test_search_empty_query(self, provider):
        """Query vazia deve lançar erro."""
        with pytest.raises(SearchProviderError) as exc:
            await provider.search("")
        assert "consulta vazia" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_search_success(self, provider):
        """Busca bem-sucedida retorna resultados normalizados."""
        mock_response = Mock()
        mock_response.text = """
        <html>
            <a class="result__a" href="https://example.com/page1">Title 1</a>
            <a class="result__a" href="https://example.com/page2">Title 2</a>
        </html>
        """
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await provider.search("test query", limit=2)

            assert len(results) == 2
            assert isinstance(results[0], SearchResult)
            assert results[0].title == "Title 1"
            assert results[0].url == "https://example.com/page1"
            assert results[0].source == "duckduckgo"
            assert results[0].credibility == 0.6

    @pytest.mark.asyncio
    async def test_search_http_error(self, provider):
        """Erro HTTP deve lançar SearchProviderError recuperável."""
        import httpx

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.HTTPError("Connection failed")

            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            assert exc.value.recoverable is True

    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        """Health check verifica disponibilidade."""
        mock_response = Mock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            healthy = await provider.health_check()
            assert healthy is True


class TestGitHubProvider:
    """Testes do GitHubProvider."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider(token="test_token")

    def test_name_and_source_kind(self, provider):
        assert provider.name == "github"
        assert provider.source_kind == "github"

    @pytest.mark.asyncio
    async def test_search_repositories(self, provider):
        """Busca de repositórios."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [
                {
                    "full_name": "user/repo1",
                    "html_url": "https://github.com/user/repo1",
                    "description": "Repo 1 description",
                    "created_at": "2024-01-01T00:00:00Z",
                    "owner": {"login": "user"},
                    "stargazers_count": 100,
                    "language": "Python",
                }
            ]
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await provider.search("python async", limit=1, type="repositories")

            assert len(results) == 1
            assert results[0].title == "user/repo1"
            assert results[0].url == "https://github.com/user/repo1"
            assert results[0].source == "github"
            assert results[0].credibility == 0.8
            assert results[0].meta is not None
            assert results[0].meta["stars"] == 100

    @pytest.mark.asyncio
    async def test_search_code(self, provider):
        """Busca de código."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [
                {
                    "name": "main.py",
                    "html_url": "https://github.com/user/repo/blob/main/main.py",
                    "path": "main.py",
                    "repository": {"full_name": "user/repo", "owner": {"login": "user"}},
                }
            ]
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await provider.search("async def", limit=1, type="code")

            assert len(results) == 1
            assert results[0].title == "main.py"
            assert "main.py" in results[0].description

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, provider):
        """Rate limit (403) deve lançar erro recuperável."""
        import httpx

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=Mock(), response=mock_response
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            assert exc.value.recoverable is True


class TestDocumentationProvider:
    """Testes do DocumentationProvider."""

    @pytest.fixture
    def provider(self):
        return DocumentationProvider()

    def test_name_and_source_kind(self, provider):
        assert provider.name == "documentation"
        assert provider.source_kind == "documentation"

    @pytest.mark.asyncio
    async def test_search_with_site_filter(self, provider):
        """Busca deve incluir filtro de sites de documentação."""
        mock_response = Mock()
        mock_response.text = """
        <html>
            <a class="result__a" href="https://docs.python.org/3/library/asyncio.html">asyncio — Asynchronous I/O</a>
        </html>
        """
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await provider.search("python asyncio", limit=1)

            assert len(results) == 1
            assert results[0].source == "documentation"
            assert results[0].credibility == 0.85
            # Verificar se URL incluiu site: filter (URL-encoded como site%3A)
            call_args = mock_get.call_args
            assert "site%3A" in call_args[0][0]  # URL is first positional arg

    @pytest.mark.asyncio
    async def test_custom_domains(self):
        """Provedor com domínios customizados."""
        custom = DocumentationProvider(custom_domains=["custom.docs.example.com"])
        assert "custom.docs.example.com" in custom.domains


class TestSearchResult:
    """Testes do SearchResult."""

    def test_to_dict(self):
        """Serialização para dict."""
        result = SearchResult(
            title="Test Title",
            url="https://example.com",
            description="Test description",
            source="test",
            published_at="2024-01-01",
            author="Author",
            credibility=0.8,
            raw_content="Content",
            meta={"key": "value"},
        )

        d = result.to_dict()
        assert d["title"] == "Test Title"
        assert d["url"] == "https://example.com"
        assert d["source"] == "test"
        assert d["credibility"] == 0.8
        assert d["meta"]["key"] == "value"


class TestSearchProviderError:
    """Testes do SearchProviderError."""

    def test_error_creation(self):
        error = SearchProviderError("Test error", "test_provider", recoverable=True)
        assert str(error) == "Test error"
        assert error.provider == "test_provider"
        assert error.recoverable is True

    def test_non_recoverable(self):
        error = SearchProviderError("Fatal error", "test_provider", recoverable=False)
        assert error.recoverable is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])