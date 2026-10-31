"""
Arquivo: src/agent/knowledge/processing/compare.py
Nome: compare.py
Propósito: comparação de fontes normalizadas para identificar concordâncias, divergências e contradições.
Responsabilidade: camada de aplicação — analisa múltiplas fontes sobre mesmo tópico.
Componentes: SourceComparator, ComparisonResult, find_consensus, find_divergences.
Dependências: agent.knowledge.processing.normalize, difflib, collections, re.
Observações: não decide verdade; apenas apresenta evidências para síntese posterior.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agent.knowledge.processing.normalize import NormalizedSource


@dataclass
class ComparisonResult:
    """Resultado da comparação entre fontes."""

    topic: str
    sources_compared: int
    consensus_points: list[str] = field(default_factory=list)
    divergences: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    unique_insights: list[dict[str, Any]] = field(default_factory=list)
    source_agreement: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceCluster:
    """Grupo de fontes similares."""

    representative: NormalizedSource
    members: list[NormalizedSource] = field(default_factory=list)
    similarity_threshold: float = 0.7


class SourceComparator:
    """Compara fontes normalizadas para encontrar padrões."""

    def __init__(self, similarity_threshold: float = 0.7) -> None:
        self.similarity_threshold = similarity_threshold

    def compare(self, sources: list[NormalizedSource], topic: str = "") -> ComparisonResult:
        """Compara lista de fontes e retorna análise."""
        if not sources:
            return ComparisonResult(topic=topic, sources_compared=0)

        # Clusterizar fontes similares
        clusters = self._cluster_sources(sources)

        # Analisar cada cluster
        consensus = []
        divergences = []
        contradictions = []
        unique_insights = []

        for cluster in clusters:
            if len(cluster.members) >= 2:
                # Múltiplas fontes concordam
                consensus_points = self._extract_consensus(cluster)
                consensus.extend(consensus_points)
            else:
                # Fonte única - insight único
                unique_insights.append({
                    "source": cluster.representative.source_id,
                    "title": cluster.representative.title,
                    "key_point": self._summarize_source(cluster.representative),
                    "credibility": cluster.representative.credibility,
                })

        # Detectar divergências entre clusters
        if len(clusters) >= 2:
            divergences, contradictions = self._find_divergences(clusters)

        # Calcular concordância por fonte
        source_agreement = self._calculate_agreement(sources, clusters)

        return ComparisonResult(
            topic=topic,
            sources_compared=len(sources),
            consensus_points=consensus,
            divergences=divergences,
            contradictions=contradictions,
            unique_insights=unique_insights,
            source_agreement=source_agreement,
            metadata={
                "clusters_found": len(clusters),
                "total_sources": len(sources),
                "threshold": self.similarity_threshold,
            },
        )

    def _cluster_sources(self, sources: list[NormalizedSource]) -> list[SourceCluster]:
        """Agrupa fontes similares por conteúdo."""
        clusters: list[SourceCluster] = []
        used = set()

        for source in sources:
            if source.source_id in used:
                continue

            cluster = SourceCluster(representative=source, similarity_threshold=self.similarity_threshold)
            cluster.members.append(source)
            used.add(source.source_id)

            # Comparar com outras fontes
            for other in sources:
                if other.source_id in used:
                    continue
                similarity = self._calculate_similarity(source, other)
                if similarity >= self.similarity_threshold:
                    cluster.members.append(other)
                    used.add(other.source_id)

            clusters.append(cluster)

        return clusters

    def _calculate_similarity(self, a: NormalizedSource, b: NormalizedSource) -> float:
        """Calcula similaridade entre duas fontes."""
        # Comparar títulos
        title_sim = difflib.SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()

        # Comparar descrições
        desc_a = a.description or ""
        desc_b = b.description or ""
        desc_sim = difflib.SequenceMatcher(None, desc_a.lower(), desc_b.lower()).ratio()

        # Comparar conteúdo (se disponível)
        content_a = a.content or ""
        content_b = b.content or ""
        content_sim = difflib.SequenceMatcher(None, content_a[:1000].lower(), content_b[:1000].lower()).ratio()

        # Peso: título 30%, descrição 40%, conteúdo 30%
        return (title_sim * 0.3) + (desc_sim * 0.4) + (content_sim * 0.3)

    def _extract_consensus(self, cluster: SourceCluster) -> list[str]:
        """Extrai pontos de consenso de um cluster."""
        if len(cluster.members) < 2:
            return []

        consensus = []
        # Extrair frases comuns nas descrições
        all_text = " ".join(
            filter(None, [m.description for m in cluster.members] + [m.content for m in cluster.members if m.content])
        )

        # Simples: frases que aparecem em múltiplas fontes
        sentences = [s.strip() for s in all_text.split(".") if len(s.strip()) > 20]
        sentence_counts = Counter(sentences)

        for sentence, count in sentence_counts.items():
            if count >= 2:  # Aparece em pelo menos 2 fontes
                consensus.append(sentence)

        return consensus[:5]  # Limitar

    def _summarize_source(self, source: NormalizedSource) -> str:
        """Cria resumo curto de uma fonte."""
        parts = []
        if source.description:
            parts.append(source.description[:200])
        elif source.content:
            parts.append(source.content[:200])
        return " ".join(parts) if parts else source.title

    def _find_divergences(self, clusters: list[SourceCluster]) -> tuple[list[dict], list[dict]]:
        """Encontra divergências e contradições entre clusters."""
        divergences = []
        contradictions = []

        # Comparar representantes de cada cluster
        for i, cluster_a in enumerate(clusters):
            for cluster_b in clusters[i+1:]:
                rep_a = cluster_a.representative
                rep_b = cluster_b.representative

                # Verificar contradições diretas
                contradiction = self._check_contradiction(rep_a, rep_b)
                if contradiction:
                    contradictions.append(contradiction)
                else:
                    # Verificar divergência de foco
                    divergence = self._check_divergence(rep_a, rep_b, cluster_a, cluster_b)
                    if divergence:
                        divergences.append(divergence)

        return divergences, contradictions

    def _check_contradiction(self, a: NormalizedSource, b: NormalizedSource) -> dict | None:
        """Verifica contradição direta entre duas fontes."""
        # Palavras de negação/oposição
        text_a = (a.description or "") + " " + (a.content or "")
        text_b = (b.description or "") + " " + (b.content or "")

        contradiction_patterns = [
            (r"não\s+\w+", r"\w+"),  # "não X" vs "X"
            (r"impossível", r"possível"),
            (r"errado", r"correto"),
            (r"deprecated", r"recommended"),
            (r"avoid", r"use"),
            (r"don't", r"do"),
            (r"never", r"always"),
        ]

        for neg_pattern, pos_pattern in contradiction_patterns:
            if re.search(neg_pattern, text_a, re.IGNORECASE) and re.search(pos_pattern, text_b, re.IGNORECASE):
                return {
                    "type": "contradiction",
                    "source_a": a.source_id,
                    "source_b": b.source_id,
                    "pattern": f"{neg_pattern} vs {pos_pattern}",
                    "excerpt_a": text_a[:200],
                    "excerpt_b": text_b[:200],
                }

        return None

    def _check_divergence(self, a: NormalizedSource, b: NormalizedSource,
                          cluster_a: SourceCluster, cluster_b: SourceCluster) -> dict | None:
        """Verifica divergência de foco/ênfase."""
        # Comparar palavras-chave principais
        keywords_a = self._extract_keywords(a)
        keywords_b = self._extract_keywords(b)

        common = keywords_a & keywords_b
        unique_a = keywords_a - keywords_b
        unique_b = keywords_b - keywords_a

        if len(unique_a) > 2 or len(unique_b) > 2:
            return {
                "type": "divergence",
                "source_a": a.source_id,
                "source_b": b.source_id,
                "cluster_a_size": len(cluster_a.members),
                "cluster_b_size": len(cluster_b.members),
                "common_keywords": list(common)[:10],
                "unique_a": list(unique_a)[:10],
                "unique_b": list(unique_b)[:10],
                "focus_a": " ".join(list(unique_a)[:5]),
                "focus_b": " ".join(list(unique_b)[:5]),
            }

        return None

    def _extract_keywords(self, source: NormalizedSource) -> set[str]:
        """Extrai palavras-chave de uma fonte."""
        text = " ".join(filter(None, [
            source.title,
            source.description or "",
            source.content or "",
        ])).lower()

        # Palavras significativas (3+ chars, não stopwords)
        stopwords = {"the", "and", "for", "with", "from", "this", "that", "have", "been", "will", "would", "could", "should"}
        words = re.findall(r"\b\w{3,}\b", text)
        return {w for w in words if w not in stopwords}

    def _calculate_agreement(self, sources: list[NormalizedSource], clusters: list[SourceCluster]) -> dict[str, float]:
        """Calcula score de concordância por fonte."""
        agreement = {}
        total_sources = len(sources)

        for source in sources:
            # Encontrar cluster da fonte
            source_cluster = None
            for cluster in clusters:
                if any(m.source_id == source.source_id for m in cluster.members):
                    source_cluster = cluster
                    break

            if source_cluster:
                # Concordância = tamanho do cluster / total
                agreement[source.source_id] = len(source_cluster.members) / total_sources
            else:
                agreement[source.source_id] = 1.0 / total_sources

        return agreement


def find_consensus(sources: list[NormalizedSource], threshold: float = 0.7) -> list[str]:
    """Encontra pontos de consenso entre fontes."""
    comparator = SourceComparator(similarity_threshold=threshold)
    result = comparator.compare(sources)
    return result.consensus_points


def find_divergences(sources: list[NormalizedSource], threshold: float = 0.7) -> list[dict]:
    """Encontra divergências entre fontes."""
    comparator = SourceComparator(similarity_threshold=threshold)
    result = comparator.compare(sources)
    return result.divergences + result.contradictions