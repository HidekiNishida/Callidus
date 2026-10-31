"""
Arquivo: src/agent/knowledge/processing/normalize.py
Nome: normalize.py
Propósito: normalização de resultados de diferentes fontes para estrutura comum.
Responsabilidade: camada de aplicação — transforma resultados brutos em KnowledgeSource normalizado.
Componentes: ResultNormalizer, normalize_search_result, deduplicate_sources.
Dependências: agent.knowledge.providers.base, dataclasses.
Observações: garante que todas as fontes tenham campos consistentes para processamento posterior.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from agent.knowledge.providers.base import SearchResult


@dataclass
class NormalizedSource:
    """Fonte normalizada pronta para processamento."""

    source_id: str
    source_kind: str
    title: str
    url: str
    description: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    retrieved_at: datetime
    credibility: float
    domain: str
    content_hash: str
    language: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "content": self.content,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "retrieved_at": self.retrieved_at.isoformat(),
            "credibility": self.credibility,
            "domain": self.domain,
            "content_hash": self.content_hash,
            "language": self.language,
            "meta": self.meta,
        }


class ResultNormalizer:
    """Normaliza resultados de diferentes provedores para estrutura comum."""

    def __init__(self) -> None:
        self.seen_hashes: set[str] = set()

    def normalize(self, result: SearchResult) -> NormalizedSource:
        """Normaliza um SearchResult para NormalizedSource."""
        # Gerar hash do conteúdo para deduplicação
        content_for_hash = (
            (result.title or "") + (result.url or "") + (result.description or "") + (result.raw_content or "")
        )
        content_hash = hashlib.sha256(content_for_hash.encode()).hexdigest()[:16]

        # Extrair domínio
        domain = ""
        if result.url:
            try:
                domain = urlparse(result.url).netloc
            except Exception:
                pass

        # Detectar linguagem básica
        language = self._detect_language(result)

        # Converter published_at string para datetime se necessário
        published_at = None
        if result.published_at:
            published_at = self._parse_datetime(result.published_at)

        return NormalizedSource(
            source_id=f"{result.source}_{content_hash}",
            source_kind=result.source,
            title=result.title or "Sem título",
            url=result.url or "",
            description=result.description,
            content=result.raw_content,
            author=result.author,
            published_at=published_at,
            retrieved_at=datetime.now(UTC),
            credibility=max(0.0, min(1.0, result.credibility)),
            domain=domain,
            content_hash=content_hash,
            language=language,
            meta=result.meta or {},
        )

    def normalize_batch(self, results: list[SearchResult]) -> list[NormalizedSource]:
        """Normaliza lote de resultados, removendo duplicatas por hash."""
        normalized = []
        for result in results:
            norm = self.normalize(result)
            if norm.content_hash not in self.seen_hashes:
                self.seen_hashes.add(norm.content_hash)
                normalized.append(norm)
        return normalized

    def _detect_language(self, result: SearchResult) -> str | None:
        """Detecta linguagem provável do conteúdo."""
        text = " ".join(filter(None, [
            result.title or "",
            result.description or "",
            result.raw_content or "",
        ])).lower()

        # Palavras-chave por linguagem
        lang_keywords = {
            "python": ["def ", "import ", "async def", "await ", "pip install", "python"],
            "javascript": ["function ", "const ", "let ", "npm install", "javascript", "node.js"],
            "typescript": ["interface ", "type ", ": string", "typescript", "tsconfig"],
            "rust": ["fn ", "let mut", "cargo ", "rust", "match "],
            "go": ["func ", "package ", "go mod", "golang"],
            "java": ["public class", "private ", "maven", "gradle", "java"],
            "sql": ["select ", "insert ", "create table", "sql"],
            "bash": ["#!/bin/bash", "curl ", "grep ", "awk ", "sed ", "bash"],
            "docker": ["dockerfile", "docker run", "docker build", "docker-compose"],
            "kubernetes": ["kubectl", "k8s", "deployment.yaml", "service.yaml"],
        }

        for lang, keywords in lang_keywords.items():
            if any(kw in text for kw in keywords):
                return lang

        return None

    def _parse_datetime(self, dt_str: str) -> datetime | None:
        """Tenta parsear string de data em datetime."""
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%b %d, %Y",
            "%B %d, %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None


def normalize_search_result(result: SearchResult) -> NormalizedSource:
    """Função helper para normalizar um resultado."""
    return ResultNormalizer().normalize(result)


def deduplicate_sources(sources: list[NormalizedSource]) -> list[NormalizedSource]:
    """Remove fontes duplicadas baseadas no hash de conteúdo."""
    seen = set()
    unique = []
    for src in sources:
        if src.content_hash not in seen:
            seen.add(src.content_hash)
            unique.append(src)
    return unique