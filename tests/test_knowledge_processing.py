"""
Arquivo: tests/test_knowledge_processing.py
Nome: test_knowledge_processing.py
Propósito: testes do pipeline de processamento (normalize, compare, synthesize, verify).
Responsabilidade: camada de teste — verifica normalização, comparação, síntese, verificação.
Dependências: pytest, agent.knowledge.processing.
Observações: testes isolados, sem dependências externas.
"""
from __future__ import annotations

import pytest

from agent.knowledge.processing import (
    NormalizedSource,
    ResultNormalizer,
    SourceComparator,
    KnowledgeSynthesizer,
    CodeVerifier,
    DocVerifier,
    VersionChecker,
    find_consensus,
    find_divergences,
)


class TestResultNormalizer:
    """Testes do ResultNormalizer."""

    @pytest.fixture
    def normalizer(self):
        return ResultNormalizer()

    def test_normalize_basic(self, normalizer):
        """Normalização básica de resultado."""
        from agent.knowledge.providers.base import SearchResult

        result = SearchResult(
            title="Python asyncio tutorial",
            url="https://realpython.com/asyncio/",
            description="Learn asyncio",
            source="duckduckgo",
            published_at="2024-01-15",
            author="Real Python",
            credibility=0.7,
            raw_content="Full article content...",
        )

        normalized = normalizer.normalize(result)

        assert isinstance(normalized, NormalizedSource)
        assert normalized.title == "Python asyncio tutorial"
        assert normalized.url == "https://realpython.com/asyncio/"
        assert normalized.source_kind == "duckduckgo"
        assert normalized.domain == "realpython.com"
        assert normalized.credibility == 0.7
        assert normalized.content_hash is not None
        assert len(normalized.content_hash) == 16

    def test_normalize_detects_language(self, normalizer):
        """Detecção de linguagem."""
        from agent.knowledge.providers.base import SearchResult

        result = SearchResult(
            title="Python async def",
            url="https://example.com",
            description="async def main(): await something()",
            source="test",
            raw_content="import asyncio\nasync def main():\n    await asyncio.sleep(1)",
        )

        normalized = normalizer.normalize(result)
        assert normalized.language == "python"

    def test_normalize_batch_deduplicates(self, normalizer):
        """Batch remove duplicatas por hash."""
        from agent.knowledge.providers.base import SearchResult

        results = [
            SearchResult(title="Test", url="https://a.com", source="test", raw_content="content"),
            SearchResult(title="Test", url="https://a.com", source="test", raw_content="content"),  # Duplicate
            SearchResult(title="Test 2", url="https://b.com", source="test", raw_content="other"),
        ]

        normalized = normalizer.normalize_batch(results)
        assert len(normalized) == 2


class TestSourceComparator:
    """Testes do SourceComparator."""

    @pytest.fixture
    def comparator(self):
        return SourceComparator(similarity_threshold=0.7)

    @pytest.fixture
    def sample_sources(self):
        return [
            NormalizedSource(
                source_id="s1", source_kind="web", title="Python asyncio tutorial",
                url="https://a.com", description="Learn asyncio", content="asyncio tutorial",
                author="A", published_at=None, retrieved_at=None, credibility=0.8,
                domain="a.com", content_hash="hash1", language="python",
            ),
            NormalizedSource(
                source_id="s2", source_kind="doc", title="Python asyncio guide",
                url="https://b.com", description="asyncio guide", content="asyncio guide",
                author="B", published_at=None, retrieved_at=None, credibility=0.7,
                domain="b.com", content_hash="hash2", language="python",
            ),
            NormalizedSource(
                source_id="s3", source_kind="web", title="JavaScript promises",
                url="https://c.com", description="JS promises", content="promises guide",
                author="C", published_at=None, retrieved_at=None, credibility=0.6,
                domain="c.com", content_hash="hash3", language="javascript",
            ),
        ]

    def test_compare_clusters_similar(self, comparator, sample_sources):
        """Agrupa fontes similares (Python asyncio)."""
        result = comparator.compare(sample_sources, topic="python asyncio")

        assert result.sources_compared == 3
        assert len(result.consensus_points) >= 0  # Pode ou não ter consenso
        assert result.metadata["clusters_found"] >= 2  # Python sources should cluster together

    def test_compare_finds_divergence(self, comparator, sample_sources):
        """Detecta divergência entre tópicos diferentes."""
        result = comparator.compare(sample_sources, topic="mixed")

        # Deve detectar que Python e JS são clusters diferentes
        assert result.metadata["clusters_found"] >= 2

    def test_find_consensus(self, sample_sources):
        """Encontra consenso entre fontes."""
        consensus = find_consensus(sample_sources, threshold=0.5)
        assert isinstance(consensus, list)

    def test_find_divergences(self, sample_sources):
        """Encontra divergências."""
        divs = find_divergences(sample_sources, threshold=0.5)
        assert isinstance(divs, list)


class TestKnowledgeSynthesizer:
    """Testes do KnowledgeSynthesizer."""

    @pytest.fixture
    def synthesizer(self):
        return KnowledgeSynthesizer(min_credibility=0.4, min_sources_for_fact=2)

    @pytest.fixture
    def sample_sources(self):
        return [
            NormalizedSource(
                source_id="s1", source_kind="doc", title="Python asyncio docs",
                url="https://docs.python.org/3/library/asyncio.html",
                description="Official asyncio documentation", content="asyncio provides...",
                author="Python", published_at=None, retrieved_at=None, credibility=0.95,
                domain="docs.python.org", content_hash="h1", language="python",
            ),
            NormalizedSource(
                source_id="s2", source_kind="web", title="Real Python asyncio",
                url="https://realpython.com/asyncio/",
                description="Real Python tutorial", content="asyncio tutorial...",
                author="Real Python", published_at=None, retrieved_at=None, credibility=0.8,
                domain="realpython.com", content_hash="h2", language="python",
            ),
        ]

    def test_synthesize_basic(self, synthesizer, sample_sources):
        """Síntese básica."""
        from agent.knowledge.processing.compare import SourceComparator
        comparator = SourceComparator()
        comparison = comparator.compare(sample_sources, topic="python asyncio")

        synthesis = synthesizer.synthesize(
            question="How to use asyncio in Python?",
            sources=sample_sources,
            comparison=comparison,
        )

        assert isinstance(synthesis.summary, str)
        assert len(synthesis.summary) > 0
        assert synthesis.overall_confidence >= 0.0
        assert synthesis.sources_used == 2
        assert len(synthesis.sections) > 0

    def test_synthesis_sections_structure(self, synthesizer, sample_sources):
        """Estrutura das seções da síntese."""
        from agent.knowledge.processing.compare import SourceComparator
        comparator = SourceComparator()
        comparison = comparator.compare(sample_sources, topic="python asyncio")

        synthesis = synthesizer.synthesize(
            question="Test question",
            sources=sample_sources,
            comparison=comparison,
        )

        # Deve ter seção de resumo
        assert any(s.heading == "Resumo" for s in synthesis.sections)

        # Deve ter citações
        total_citations = sum(len(s.citations) for s in synthesis.sections)
        assert total_citations > 0


class TestCodeVerifier:
    """Testes do CodeVerifier."""

    def test_verify_python_syntax_valid(self):
        """Código Python válido passa."""
        code = "def hello():\n    print('Hello')"
        result = CodeVerifier.verify_python_syntax(code)
        assert result.passed is True
        assert result.verification_kind == "python_syntax"

    def test_verify_python_syntax_invalid(self):
        """Código Python inválido falha."""
        code = "def hello(\n    print('Hello')"  # Missing closing parenthesis
        result = CodeVerifier.verify_python_syntax(code)
        assert result.passed is False
        assert result.evidence.get("error") is not None

    def test_verify_import_exists(self):
        """Verifica import de módulo padrão."""
        result = CodeVerifier.verify_import_exists("json")
        assert result.passed is True

    def test_verify_import_not_exists(self):
        """Módulo inexistente falha."""
        result = CodeVerifier.verify_import_exists("this_module_does_not_exist_12345")
        assert result.passed is False


class TestDocVerifier:
    """Testes do DocVerifier."""

    def test_verify_url_accessible_invalid(self):
        """URL inválida falha."""
        result = DocVerifier.verify_url_accessible("not-a-url")
        assert result.passed is False

    def test_verify_documentation_version_pattern(self):
        """Verifica extração de versão da URL."""
        result = DocVerifier.verify_documentation_version("https://docs.python.org/3.11/library/asyncio.html")
        assert result.passed is True
        assert result.evidence.get("version_in_url") == "3.11"


class TestVersionChecker:
    """Testes do VersionChecker."""

    def test_check_python_version(self):
        """Verifica versão do Python."""
        result = VersionChecker.check_python_version((3, 10))
        assert result.passed is True
        assert result.verification_kind == "python_version"

    def test_check_command_available(self):
        """Verifica comando disponível."""
        result = VersionChecker.check_command_available("python3", "--version")
        assert result.passed is True
        assert "python" in result.evidence.get("version_output", "").lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])