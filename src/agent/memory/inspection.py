"""
Arquivo: src/agent/memory/inspection.py
Nome: inspection.py
Propósito: índice de inspeção de arquivos com hash, versão e relevância, para evitar releituras.
Responsabilidade: camada de aplicação — rastreia o que já foi lido, com conteúdo, hash e resumo,
e informa se um arquivo mudou desde a última inspeção.
Componentes: FileInspection, InspectionIndex, record_inspection, is_stale, relevance_score, CacheEntry.
Dependências: hashlib, pathlib, re, typing.
Observações: não cria novas tabelas; guarda o índice em `task.metadata_json["inspection"]`,
reaproveitando o campo já usado pelo bloco de inspeção do contexto. A invalidação por hash
impede releituras desnecessárias quando o arquivo não mudou. Cache genérico para resultados
de ferramentas, buscas e consultas com invalidação por hash.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SNIPPET_CHARS = 300


@dataclass
class FileInspection:
    """Registro de uma inspeção de arquivo.

    Atributos:
        path: caminho relativo ao projeto.
        hash: SHA-256 do conteúdo lido.
        size: tamanho em bytes.
        lines: quantidade de linhas.
        summary: resumo curto do conteúdo (primeiras linhas não vazias).
        snippets: trechos relevantes extraídos na inspeção.
        collected_at: instante da coleta.
        relevance: pontuação de relevância para o objetivo atual (0 a 100).
    """

    path: str
    hash: str
    size: int = 0
    lines: int = 0
    summary: str = ""
    snippets: list[str] = field(default_factory=list)
    collected_at: str = ""
    relevance: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário gravável nos metadados da tarefa."""
        return {
            "path": self.path,
            "hash": self.hash,
            "size": self.size,
            "lines": self.lines,
            "summary": self.summary,
            "snippets": self.snippets,
            "collected_at": self.collected_at,
            "relevance": self.relevance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileInspection:
        """Reconstrói a partir do dicionário gravado."""
        return cls(
            path=str(data.get("path", "")),
            hash=str(data.get("hash", "")),
            size=int(data.get("size", 0)),
            lines=int(data.get("lines", 0)),
            summary=str(data.get("summary", "")),
            snippets=list(data.get("snippets") or []),
            collected_at=str(data.get("collected_at", "")),
            relevance=int(data.get("relevance", 0)),
        )


# Cache genérico para resultados de ferramentas e consultas
@dataclass
class CacheEntry:
    """Entrada de cache genérica com hash de validação."""

    key: str
    value: Any
    hash: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "hash": self.hash,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        return cls(
            key=str(data.get("key", "")),
            value=data.get("value"),
            hash=str(data.get("hash", "")),
            created_at=str(data.get("created_at", "")),
            metadata=data.get("metadata", {}),
        )


class InspectionIndex:
    """Índice de inspeções de uma tarefa, indexado por caminho.

    Atributos:
        _items: dicionário de caminho para `FileInspection`.
        _cache: dicionário de chave para `CacheEntry` (resultados de ferramentas, buscas, etc.).
    """

    def __init__(
        self,
        items: dict[str, FileInspection] | None = None,
        cache: dict[str, CacheEntry] | None = None,
    ) -> None:
        """Cria o índice a partir de itens existentes.

        Args:
            items: dicionário de caminho para inspeção, ou vazio.
            cache: dicionário de cache genérico, ou vazio.
        """
        self._items: dict[str, FileInspection] = dict(items or {})
        self._cache: dict[str, CacheEntry] = dict(cache or {})

    @classmethod
    def from_metadata(cls, meta: dict[str, Any] | None) -> InspectionIndex:
        """Constrói o índice a partir dos metadados da tarefa.

        Args:
            meta: metadados da tarefa, que podem conter `inspection` e `cache`.

        Returns:
            O índice reconstruído, ou vazio quando não há inspeções.
        """
        meta = meta or {}
        raw = meta.get("inspection") or []
        items: dict[str, FileInspection] = {}
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                try:
                    insp = FileInspection.from_dict(entry)
                    if insp.path:
                        items[insp.path] = insp
                except Exception:
                    continue

        cache_raw = meta.get("cache") or []
        cache: dict[str, CacheEntry] = {}
        if isinstance(cache_raw, list):
            for entry in cache_raw:
                if not isinstance(entry, dict):
                    continue
                try:
                    ce = CacheEntry.from_dict(entry)
                    if ce.key:
                        cache[ce.key] = ce
                except Exception:
                    continue

        return cls(items=items, cache=cache)

    def to_metadata(self) -> list[dict[str, Any]]:
        """Serializa para gravação nos metadados da tarefa (compatibilidade com versão anterior).

        Returns:
            Lista de inspeções serializadas (formato legado).
        """
        return [item.to_dict() for item in self._items.values()]

    def to_metadata_extended(self) -> dict[str, Any]:
        """Serializa para gravação nos metadados da tarefa (formato estendido com cache).

        Returns:
            Dicionário com `inspection` e `cache`.
        """
        return {
            "inspection": [item.to_dict() for item in self._items.values()],
            "cache": [entry.to_dict() for entry in self._cache.values()],
        }

    def get(self, path: str) -> FileInspection | None:
        """Devolve a inspeção de um caminho, se existir."""
        return self._items.get(path)

    def set(self, inspection: FileInspection) -> None:
        """Registra ou atualiza a inspeção de um arquivo."""
        self._items[inspection.path] = inspection

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> list[FileInspection]:
        """Devolve todas as inspeções, mais recentes primeiro."""
        return sorted(self._items.values(), key=lambda i: i.collected_at, reverse=True)

    # Cache genérico
    def cache_get(self, key: str) -> CacheEntry | None:
        """Obtém entrada do cache se não estiver obsoleta."""
        return self._cache.get(key)

    def cache_set(self, key: str, value: Any, hash: str, metadata: dict[str, Any] | None = None) -> CacheEntry:
        """Armazena valor no cache com hash para validação."""
        entry = CacheEntry(
            key=key,
            value=value,
            hash=hash,
            created_at=_now_iso(),
            metadata=metadata or {},
        )
        self._cache[key] = entry
        return entry

    def cache_invalidate(self, key: str) -> bool:
        """Invalida entrada do cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def cache_invalidate_prefix(self, prefix: str) -> int:
        """Invalida todas as entradas com chave começando com prefixo."""
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._cache[k]
        return len(keys_to_remove)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    """SHA-256 do conteúdo de um arquivo, ou string vazia quando não pode ser lido."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def sha256_content(content: str) -> str:
    """SHA-256 de conteúdo textual."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_inspection(
    index: InspectionIndex,
    path: str,
    root_path: str,
    content: str,
    *,
    objective: str = "",
) -> FileInspection:
    """Registra (ou atualiza) a inspeção de um arquivo.

    Args:
        index: índice de inspeções da tarefa.
        path: caminho relativo ao projeto.
        root_path: raiz do projeto, para resolver o caminho absoluto.
        content: conteúdo do arquivo (já lido).
        objective: objetivo da etapa, usado para pontuar a relevância.

    Returns:
        O `FileInspection` registrado.
    """
    full = Path(root_path) / path
    try:
        size = full.stat().st_size
    except OSError:
        size = len(content.encode("utf-8"))
    lines = content.count("\n") + 1 if content else 0
    summary = "\n".join(line for line in content.splitlines() if line.strip())[:_SNIPPET_CHARS]
    snippets = _extract_snippets(content, objective)
    relevance = relevance_score(objective, content, snippets)
    inspection = FileInspection(
        path=path,
        hash=sha256_file(full),
        size=size,
        lines=lines,
        summary=summary,
        snippets=snippets,
        collected_at=_now_iso(),
        relevance=relevance,
    )
    index.set(inspection)
    return inspection


def is_stale(index: InspectionIndex, path: str, root_path: str) -> bool:
    """Diz se um arquivo mudou desde a última inspeção.

    Args:
        index: índice de inspeções.
        path: caminho relativo ao projeto.
        root_path: raiz do projeto.

    Returns:
        `True` quando não há inspeção registrada ou o hash do disco difere do gravado.
    """
    insp = index.get(path)
    if insp is None:
        return True
    current = sha256_file(Path(root_path) / path)
    return current != insp.hash


def is_cache_stale(index: InspectionIndex, key: str, current_hash: str) -> bool:
    """Verifica se uma entrada de cache está obsoleta comparando hashes.

    Args:
        index: índice de inspeção com cache.
        key: chave do cache.
        current_hash: hash atual do conteúdo.

    Returns:
        `True` se não há entrada ou o hash difere.
    """
    entry = index.cache_get(key)
    if entry is None:
        return True
    return entry.hash != current_hash


def relevance_score(objective: str, content: str, snippets: list[str]) -> int:
    """Pontua a relevância de um conteúdo para o objetivo (0 a 100).

    Args:
        objective: objetivo da etapa.
        content: conteúdo do arquivo.
        snippets: trechos relevantes extraídos.

    Returns:
        Pontuação de 0 (sem relação) a 100 (altamente relevante).
    """
    if not content or not objective:
        return 0
    obj_words = {w.lower() for w in re.findall(r"\w{4,}", objective)}
    if not obj_words:
        return 0
    content_words = {w.lower() for w in re.findall(r"\w{4,}", content)}
    overlap = len(obj_words & content_words)
    base = min(50, overlap * 10)
    snippet_bonus = min(30, len(snippets) * 10)
    symbol_bonus = 20 if any(s in content for s in ("def ", "class ", "function ", "interface ")) else 0
    return min(100, base + snippet_bonus + symbol_bonus)


def _extract_snippets(content: str, objective: str) -> list[str]:
    """Extrai trechos do conteúdo que conversam com o objetivo.

    Args:
        content: conteúdo do arquivo.
        objective: objetivo da etapa.

    Returns:
        Lista de até 3 trechos curtos (até 120 caracteres cada).
    """
    if not content or not objective:
        return []
    obj_words = {w.lower() for w in re.findall(r"\w{4,}", objective)}
    snippets: list[str] = []
    for line in content.splitlines():
        low = line.lower()
        if any(w in low for w in obj_words):
            snippets.append(line.strip()[:120])
            if len(snippets) >= 3:
                break
    return snippets


def rank_by_relevance(index: InspectionIndex, limit: int = 10) -> list[FileInspection]:
    """Devolve as inspeções ordenadas por relevância decrescente.

    Args:
        index: índice de inspeções.
        limit: máximo de itens devolvidos.

    Returns:
        Lista de inspeções, mais relevantes primeiro.
    """
    return sorted(index.items(), key=lambda i: i.relevance, reverse=True)[:limit]
