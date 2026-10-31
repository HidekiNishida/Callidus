"""
Arquivo: src/agent/knowledge/processing/synthesize.py
Nome: synthesize.py
Propósito: síntese final de conhecimento a partir de fontes comparadas.
Responsabilidade: camada de aplicação — gera resposta consolidada com citações e confiança.
Componentes: KnowledgeSynthesizer, SynthesisResult, generate_synthesis.
Dependências: agent.knowledge.processing.compare, agent.knowledge.processing.normalize.
Observações: separa fatos documentados, interpretações e hipóteses claramente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.knowledge.processing.compare import ComparisonResult
from agent.knowledge.processing.normalize import NormalizedSource


@dataclass
class Citation:
    """Citação de fonte na síntese."""

    source_id: str
    title: str
    url: str
    credibility: float
    excerpt: str


@dataclass
class SynthesisSection:
    """Seção da síntese final."""

    heading: str
    content: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.5
    type: str = "fact"  # fact, interpretation, hypothesis, warning


@dataclass
class SynthesisResult:
    """Resultado completo da síntese."""

    topic: str
    question: str
    summary: str
    sections: list[SynthesisSection] = field(default_factory=list)
    overall_confidence: float = 0.5
    sources_used: int = 0
    consensus_points: list[str] = field(default_factory=list)
    divergences_noted: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeSynthesizer:
    """Gera síntese final de conhecimento a partir de análise comparativa."""

    def __init__(
        self,
        min_credibility: float = 0.4,
        min_sources_for_fact: int = 2,
    ) -> None:
        self.min_credibility = min_credibility
        self.min_sources_for_fact = min_sources_for_fact

    def synthesize(
        self,
        question: str,
        sources: list[NormalizedSource],
        comparison: ComparisonResult | None = None,
    ) -> SynthesisResult:
        """Gera síntese completa a partir de fontes e comparação opcional."""
        if comparison is None:
            from agent.knowledge.processing.compare import SourceComparator
            comparator = SourceComparator()
            comparison = comparator.compare(sources, topic=question)

        # Filtrar fontes por credibilidade
        credible_sources = [s for s in sources if s.credibility >= self.min_credibility]

        # Gerar seções
        sections = []

        # 1. Resumo executivo
        executive_summary = self._generate_executive_summary(question, credible_sources, comparison)
        sections.append(SynthesisSection(
            heading="Resumo",
            content=executive_summary,
            citations=self._get_citations_for_text(executive_summary, credible_sources),
            confidence=0.7,
            type="fact",
        ))

        # 2. Pontos de consenso (fatos bem estabelecidos)
        if comparison.consensus_points:
            consensus_content = self._format_consensus(comparison.consensus_points, credible_sources)
            sections.append(SynthesisSection(
                heading="Consenso entre fontes",
                content=consensus_content,
                citations=self._get_citations_for_points(comparison.consensus_points, credible_sources),
                confidence=0.85,
                type="fact",
            ))

        # 3. Análise por tema/fonte
        thematic_sections = self._generate_thematic_sections(credible_sources, comparison)
        sections.extend(thematic_sections)

        # 4. Divergências e pontos de atenção
        if comparison.divergences or comparison.contradictions:
            divergence_content = self._format_divergences(comparison)
            sections.append(SynthesisSection(
                heading="Divergências e pontos de atenção",
                content=divergence_content,
                citations=[],
                confidence=0.6,
                type="warning",
            ))

        # 5. Insights únicos de fontes individuais
        if comparison.unique_insights:
            insights_content = self._format_unique_insights(comparison.unique_insights)
            sections.append(SynthesisSection(
                heading="Insights adicionais",
                content=insights_content,
                citations=self._get_citations_for_insights(comparison.unique_insights, credible_sources),
                confidence=0.5,
                type="interpretation",
            ))

        # Calcular confiança geral
        overall_confidence = self._calculate_overall_confidence(sections, comparison)

        # Identificar limitações
        limitations = self._identify_limitations(credible_sources, comparison)

        return SynthesisResult(
            topic=comparison.topic or "Tópico",
            question=question,
            summary=executive_summary,
            sections=sections,
            overall_confidence=overall_confidence,
            sources_used=len(credible_sources),
            consensus_points=comparison.consensus_points,
            divergences_noted=comparison.divergences + comparison.contradictions,
            limitations=limitations,
            metadata={
                "total_sources": len(sources),
                "credible_sources": len(credible_sources),
                "comparison_metadata": comparison.metadata,
            },
        )

    def _generate_executive_summary(
        self,
        question: str,
        sources: list[NormalizedSource],
        comparison: ComparisonResult,
    ) -> str:
        """Gera resumo executivo da síntese."""
        if not sources:
            return "Nenhuma fonte confiável encontrada para responder à pergunta."

        # Usar consenso se disponível
        if comparison.consensus_points:
            main_points = comparison.consensus_points[:3]
            summary = f"Em resposta a \"{question}\": "
            summary += " ".join(main_points)
            return summary

        # Caso contrário, usar fonte mais confiável
        best_source = max(sources, key=lambda s: s.credibility)
        excerpt = (best_source.description or best_source.content or best_source.title)[:300]
        return f"Baseado na fonte mais confiável ({best_source.title}): {excerpt}"

    def _format_consensus(self, points: list[str], sources: list[NormalizedSource]) -> str:
        """Formata pontos de consenso com numeração."""
        if not points:
            return "Nenhum consenso claro identificado."

        lines = ["Os seguintes pontos têm concordância entre múltiplas fontes:"]
        for i, point in enumerate(points, 1):
            lines.append(f"{i}. {point}")
        return "\n".join(lines)

    def _generate_thematic_sections(
        self,
        sources: list[NormalizedSource],
        comparison: ComparisonResult,
    ) -> list[SynthesisSection]:
        """Gera seções temáticas agrupando fontes por foco."""
        sections = []

        # Agrupar fontes por tecnologia/domain
        by_domain = {}
        for source in sources:
            domain = source.domain or source.technology or "geral"
            by_domain.setdefault(domain, []).append(source)

        for domain, domain_sources in by_domain.items():
            if len(domain_sources) == 0:
                continue

            content_parts = [f"Fontes sobre {domain}:"]
            citations = []

            for src in domain_sources:
                key_info = self._extract_key_info(src)
                if key_info:
                    content_parts.append(f"• {src.title}: {key_info}")
                    citations.append(Citation(
                        source_id=src.source_id,
                        title=src.title,
                        url=src.url,
                        credibility=src.credibility,
                        excerpt=key_info[:200],
                    ))

            if len(content_parts) > 1:
                sections.append(SynthesisSection(
                    heading=f"Análise: {domain}",
                    content="\n".join(content_parts),
                    citations=citations,
                    confidence=0.65,
                    type="fact",
                ))

        return sections

    def _extract_key_info(self, source: NormalizedSource) -> str:
        """Extrai informação-chave de uma fonte."""
        if source.description:
            return source.description[:300]
        if source.content:
            return source.content[:300]
        return source.title

    def _format_divergences(self, comparison: ComparisonResult) -> str:
        """Formata divergências e contradições."""
        lines = ["Foram identificadas diferenças entre as fontes consultadas:"]

        for div in comparison.divergences:
            lines.append(f"\n• **Divergência de foco**: {div.get('focus_a', 'Fonte A')} vs {div.get('focus_b', 'Fonte B')}")
            lines.append(f"  - Fonte A ({div['source_a']}): ênfase em {div.get('focus_a', 'N/A')}")
            lines.append(f"  - Fonte B ({div['source_b']}): ênfase em {div.get('focus_b', 'N/A')}")

        for contra in comparison.contradictions:
            lines.append(f"\n• **Possível contradição**: {contra.get('pattern', 'Padrão não identificado')}")
            lines.append(f"  - {contra['source_a']}: {contra['excerpt_a'][:150]}...")
            lines.append(f"  - {contra['source_b']}: {contra['excerpt_b'][:150]}...")

        lines.append("\n> **Recomendação**: Verificar documentação oficial ou testar na prática para resolver.")
        return "\n".join(lines)

    def _format_unique_insights(self, insights: list[dict]) -> str:
        """Formata insights únicos."""
        lines = ["As seguintes informações vêm de fontes individuais (não corroboradas):"]
        for insight in insights:
            lines.append(f"\n• **{insight['title']}** (credibilidade: {insight['credibility']:.0%})")
            lines.append(f"  {insight['key_point'][:300]}")
        return "\n".join(lines)

    def _get_citations_for_text(self, text: str, sources: list[NormalizedSource]) -> list[Citation]:
        """Encontra citações relevantes para um texto."""
        citations = []
        for src in sources:
            # Verificar se conteúdo da fonte aparece no texto
            src_text = (src.description or src.content or src.title)[:100]
            if any(word in text.lower() for word in src_text.lower().split() if len(word) > 4):
                citations.append(Citation(
                    source_id=src.source_id,
                    title=src.title,
                    url=src.url,
                    credibility=src.credibility,
                    excerpt=src_text,
                ))
        return citations[:5]

    def _get_citations_for_points(self, points: list[str], sources: list[NormalizedSource]) -> list[Citation]:
        """Citações para pontos de consenso."""
        citations = []
        for src in sources:
            src_text = (src.description or src.content or src.title)[:200]
            if any(p[:50] in src_text for p in points):
                citations.append(Citation(
                    source_id=src.source_id,
                    title=src.title,
                    url=src.url,
                    credibility=src.credibility,
                    excerpt=src_text,
                ))
        return citations[:10]

    def _get_citations_for_insights(self, insights: list[dict], sources: list[NormalizedSource]) -> list[Citation]:
        """Citações para insights únicos."""
        citations = []
        for insight in insights:
            for src in sources:
                if src.source_id == insight.get("source"):
                    citations.append(Citation(
                        source_id=src.source_id,
                        title=src.title,
                        url=src.url,
                        credibility=src.credibility,
                        excerpt=insight.get("key_point", "")[:200],
                    ))
                    break
        return citations

    def _calculate_overall_confidence(self, sections: list[SynthesisSection], comparison: ComparisonResult) -> float:
        """Calcula confiança geral da síntese."""
        if not sections:
            return 0.0

        # Média ponderada por tipo
        weights = {"fact": 1.0, "interpretation": 0.7, "hypothesis": 0.4, "warning": 0.5}
        total_weight = 0
        weighted_sum = 0

        for section in sections:
            weight = weights.get(section.type, 0.5)
            weighted_sum += section.confidence * weight
            total_weight += weight

        base_confidence = weighted_sum / total_weight if total_weight > 0 else 0.5

        # Ajustar por qualidade da comparação
        if comparison.sources_compared >= 3:
            base_confidence *= 1.1
        elif comparison.sources_compared == 1:
            base_confidence *= 0.8

        # Penalizar se há contradições
        if comparison.contradictions:
            base_confidence *= 0.8

        return min(1.0, max(0.0, base_confidence))

    def _identify_limitations(
        self,
        sources: list[NormalizedSource],
        comparison: ComparisonResult,
    ) -> list[str]:
        """Identifica limitações da síntese."""
        limitations = []

        if len(sources) < 3:
            limitations.append(f"Poucas fontes ({len(sources)}) - síntese pode não ser representativa")

        if comparison.contradictions:
            limitations.append(f"{len(comparison.contradictions)} contradição(ões) detectada(s) - recomenda-se verificação")

        low_cred = [s for s in sources if s.credibility < 0.5]
        if low_cred:
            limitations.append(f"{len(low_cred)} fonte(s) com credibilidade baixa (<50%)")

        domains = set(s.domain for s in sources)
        if len(domains) == 1:
            limitations.append("Todas as fontes do mesmo domínio - possível viés")

        return limitations


def generate_synthesis(
    question: str,
    sources: list[NormalizedSource],
    comparison: ComparisonResult | None = None,
) -> SynthesisResult:
    """Função helper para gerar síntese."""
    synthesizer = KnowledgeSynthesizer()
    return synthesizer.synthesize(question, sources, comparison)