"""
Arquivo: src/agent/knowledge/memory/store.py
Nome: store.py
Propósito: armazenamento persistente e recuperação de itens de conhecimento.
Responsabilidade: camada de aplicação — CRUD, busca textual (FTS5), deduplicação, versionamento.
Componentes: KnowledgeMemoryStore, KnowledgeIndexer, Deduplicator.
Dependências: agent.knowledge.models, agent.persistence.models, sqlalchemy, sqlite3 (FTS5).
Observações: usa SQLite FTS5 nativo para busca full-text; índices otimizados para recuperação contextual.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agent.knowledge.models import (
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeValidationStatus,
    KnowledgeKind,
)
from agent.persistence.models import ProjectModel


class KnowledgeIndexer:
    """Gerencia índice FTS5 para busca full-text de conhecimento."""

    FTS_TABLE = "knowledge_items_fts"

    def __init__(self, session: Session) -> None:
        self._session = session
        self._engine = session.get_bind()

    def create_fts_table(self) -> None:
        """Cria tabela virtual FTS5 se não existir."""
        # Verificar se FTS5 está disponível
        try:
            with self._engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS {self.FTS_TABLE} USING fts5(
                        item_id UNINDEXED,
                        title,
                        content,
                        summary,
                        technology,
                        version,
                        tags,
                        tokenize='porter unicode61'
                    )
                """))
                conn.commit()
        except Exception:
            # FTS5 pode não estar disponível em alguns builds do SQLite
            pass

    def index_item(self, item: KnowledgeItemModel) -> None:
        """Adiciona/atualiza item no índice FTS."""
        try:
            tags = " ".join(item.context_tags_json or [])
            with self._engine.connect() as conn:
                # Upsert: delete + insert
                conn.execute(text(f"DELETE FROM {self.FTS_TABLE} WHERE item_id = :id"), {"id": str(item.id)})
                conn.execute(text(f"""
                    INSERT INTO {self.FTS_TABLE} (item_id, title, content, summary, technology, version, tags)
                    VALUES (:id, :title, :content, :summary, :tech, :version, :tags)
                """), {
                    "id": str(item.id),
                    "title": item.title or "",
                    "content": item.content or "",
                    "summary": item.summary or "",
                    "tech": item.technology or "",
                    "version": item.version or "",
                    "tags": tags,
                })
                conn.commit()
        except Exception:
            pass

    def remove_item(self, item_id: uuid.UUID) -> None:
        """Remove item do índice."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text(f"DELETE FROM {self.FTS_TABLE} WHERE item_id = :id"), {"id": str(item_id)})
                conn.commit()
        except Exception:
            pass

    def search(self, project_id: uuid.UUID, query: str, limit: int = 20) -> list[dict]:
        """Busca full-text no índice FTS."""
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(f"""
                    SELECT item_id, rank
                    FROM {self.FTS_TABLE}
                    WHERE {self.FTS_TABLE} MATCH :query
                    ORDER BY rank
                    LIMIT :limit
                """), {"query": query, "limit": limit})
                return [{"item_id": row[0], "rank": row[1]} for row in result]
        except Exception:
            return []


class Deduplicator:
    """Deduplicação de itens de conhecimento baseada em hash de conteúdo."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def compute_content_hash(self, title: str, content: str, technology: str | None = None) -> str:
        """Calcula hash determinístico do conteúdo."""
        data = f"{title}|{content}|{technology or ''}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def find_duplicates(self, project_id: uuid.UUID, title: str, content: str, technology: str | None = None) -> list[KnowledgeItemModel]:
        """Encontra itens duplicados por hash de conteúdo."""
        content_hash = self.compute_content_hash(title, content, technology)
        # Buscar itens com mesmo hash nos metadados ou recomputar
        items = list(self._session.scalars(
            select(KnowledgeItemModel).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status != KnowledgeValidationStatus.FAILED.value,
            )
        ).all())

        duplicates = []
        for item in items:
            item_hash = self.compute_content_hash(item.title, item.content or "", item.technology)
            if item_hash == content_hash:
                duplicates.append(item)

        return duplicates

    def is_duplicate(self, project_id: uuid.UUID, title: str, content: str, technology: str | None = None) -> KnowledgeItemModel | None:
        """Verifica se já existe item duplicado."""
        duplicates = self.find_duplicates(project_id, title, content, technology)
        return duplicates[0] if duplicates else None


class KnowledgeMemoryStore:
    """Armazenamento persistente e recuperação de conhecimento."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._indexer = KnowledgeIndexer(session)
        self._deduplicator = Deduplicator(session)

    def initialize(self) -> None:
        """Inicializa estruturas (FTS, etc.)."""
        self._indexer.create_fts_table()

    def save(
        self,
        project_id: uuid.UUID,
        kind: str,
        title: str,
        content: str,
        summary: str | None = None,
        technology: str | None = None,
        version: str | None = None,
        context_tags: list[str] | None = None,
        confidence: float = 0.5,
        sources: list[dict] | None = None,
        validation_status: str = KnowledgeValidationStatus.UNVALIDATED.value,
        allow_duplicate: bool = False,
    ) -> KnowledgeItemModel:
        """Salva item de conhecimento com deduplicação e indexação."""
        # Verificar duplicata
        if not allow_duplicate:
            existing = self._deduplicator.is_duplicate(project_id, title, content, technology)
            if existing:
                # Atualizar item existente
                return self.update(existing.id, confidence=max(existing.confidence, confidence), sources=sources)

        # Criar novo item
        item = KnowledgeItemModel(
            project_id=project_id,
            kind=kind,
            title=title,
            content=content,
            summary=summary,
            technology=technology,
            version=version,
            context_tags_json=context_tags,
            confidence=confidence,
            validation_status=validation_status,
            source_count=len(sources) if sources else 0,
        )
        self._session.add(item)
        self._session.flush()

        # Salvar fontes
        if sources:
            for src in sources:
                source = KnowledgeSourceModel(
                    item_id=item.id,
                    source_kind=src.get("source_kind", "web_search"),
                    title=src.get("title"),
                    url=src.get("url"),
                    author=src.get("author"),
                    published_at=src.get("published_at"),
                    credibility=src.get("credibility", 0.5),
                    raw_content=src.get("raw_content"),
                    extracted_content=src.get("extracted_content"),
                    meta_json=src.get("meta"),
                )
                self._session.add(source)

        self._session.flush()

        # Indexar
        self._indexer.index_item(item)

        return item

    def update(
        self,
        item_id: uuid.UUID,
        title: str | None = None,
        content: str | None = None,
        summary: str | None = None,
        confidence: float | None = None,
        validation_status: str | None = None,
        sources: list[dict] | None = None,
    ) -> KnowledgeItemModel | None:
        """Atualiza item existente."""
        item = self._session.get(KnowledgeItemModel, item_id)
        if not item:
            return None

        # Versionamento: criar entrada na tabela de versões
        from agent.persistence.models import KnowledgeVersionModel
        version_entry = KnowledgeVersionModel(
            item_id=item.id,
            version_number=len(
                self._session.scalars(
                    select(KnowledgeVersionModel).where(KnowledgeVersionModel.item_id == item_id)
                ).all()
            ) + 1,
            title=item.title,
            content=item.content,
            summary=item.summary,
            change_reason="update",
            changed_by="knowledge_engine",
        )
        self._session.add(version_entry)

        # Atualizar campos
        if title is not None:
            item.title = title
        if content is not None:
            item.content = content
        if summary is not None:
            item.summary = summary
        if confidence is not None:
            item.confidence = confidence
        if validation_status is not None:
            item.validation_status = validation_status

        item.updated_at = datetime.now(UTC)
        self._session.flush()

        # Adicionar fontes se fornecidas
        if sources:
            for src in sources:
                source = KnowledgeSourceModel(
                    item_id=item.id,
                    source_kind=src.get("source_kind", "web_search"),
                    title=src.get("title"),
                    url=src.get("url"),
                    author=src.get("author"),
                    published_at=src.get("published_at"),
                    credibility=src.get("credibility", 0.5),
                    raw_content=src.get("raw_content"),
                    extracted_content=src.get("extracted_content"),
                    meta_json=src.get("meta"),
                )
                self._session.add(source)
            item.source_count = len(sources)

        self._session.flush()
        self._indexer.index_item(item)

        return item

    def get(self, item_id: uuid.UUID) -> KnowledgeItemModel | None:
        """Recupera item por ID."""
        return self._session.get(KnowledgeItemModel, item_id)

    def get_with_sources(self, item_id: uuid.UUID) -> dict | None:
        """Recupera item com fontes e validações."""
        item = self.get(item_id)
        if not item:
            return None

        sources = list(self._session.scalars(
            select(KnowledgeSourceModel).where(KnowledgeSourceModel.item_id == item_id)
        ).all())

        from agent.persistence.models import KnowledgeValidationModel
        validations = list(self._session.scalars(
            select(KnowledgeValidationModel).where(KnowledgeValidationModel.item_id == item_id)
        ).all())

        return {"item": item, "sources": sources, "validations": validations}

    def search(
        self,
        project_id: uuid.UUID,
        query: str,
        kind: str | None = None,
        technology: str | None = None,
        version: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
        use_fts: bool = True,
    ) -> list[KnowledgeItemModel]:
        """Busca itens de conhecimento com múltiplos filtros."""
        # Tentar FTS primeiro
        if use_fts and query:
            fts_results = self._indexer.search(project_id, query, limit=limit * 2)
            if fts_results:
                item_ids = [uuid.UUID(r["item_id"]) for r in fts_results]
                stmt = select(KnowledgeItemModel).where(
                    KnowledgeItemModel.project_id == project_id,
                    KnowledgeItemModel.id.in_(item_ids),
                )
                # Manter ordem do FTS
                items = {str(item.id): item for item in self._session.scalars(stmt).all()}
                ordered = [items[str(id)] for id in item_ids if str(id) in items]
                return ordered[:limit]

        # Fallback: busca SQL com ILIKE
        stmt = select(KnowledgeItemModel).where(
            KnowledgeItemModel.project_id == project_id,
            KnowledgeItemModel.validation_status != "failed",
        )

        if query:
            search_term = f"%{query}%"
            stmt = stmt.where(
                KnowledgeItemModel.title.ilike(search_term) |
                KnowledgeItemModel.content.ilike(search_term) |
                KnowledgeItemModel.summary.ilike(search_term)
            )
        if kind:
            stmt = stmt.where(KnowledgeItemModel.kind == kind)
        if technology:
            stmt = stmt.where(KnowledgeItemModel.technology == technology)
        if version:
            stmt = stmt.where(KnowledgeItemModel.version == version)
        if min_confidence > 0:
            stmt = stmt.where(KnowledgeItemModel.confidence >= min_confidence)

        stmt = stmt.order_by(
            KnowledgeItemModel.confidence.desc(),
            KnowledgeItemModel.updated_at.desc()
        ).limit(limit)

        return list(self._session.scalars(stmt).all())

    def search_by_context(
        self,
        project_id: uuid.UUID,
        context_tags: list[str],
        limit: int = 10,
    ) -> list[KnowledgeItemModel]:
        """Busca por tags de contexto (JSON contains)."""
        if not context_tags:
            return []

        stmt = select(KnowledgeItemModel).where(
            KnowledgeItemModel.project_id == project_id,
            KnowledgeItemModel.validation_status != "failed",
        )

        for tag in context_tags:
            # Use LIKE on JSON string for compatibility
            stmt = stmt.where(KnowledgeItemModel.context_tags_json.like(f'%"{tag}"%'))

        stmt = stmt.order_by(KnowledgeItemModel.confidence.desc()).limit(limit)
        return list(self._session.scalars(stmt).all())

    def get_recent(self, project_id: uuid.UUID, days: int = 7, limit: int = 20) -> list[KnowledgeItemModel]:
        """Itens recentes."""
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(days=days)

        stmt = select(KnowledgeItemModel).where(
            KnowledgeItemModel.project_id == project_id,
            KnowledgeItemModel.created_at >= cutoff,
        ).order_by(KnowledgeItemModel.created_at.desc()).limit(limit)

        return list(self._session.scalars(stmt).all())

    def get_most_used(self, project_id: uuid.UUID, limit: int = 20) -> list[KnowledgeItemModel]:
        """Itens mais utilizados."""
        stmt = select(KnowledgeItemModel).where(
            KnowledgeItemModel.project_id == project_id,
            KnowledgeItemModel.usage_count > 0,
        ).order_by(
            KnowledgeItemModel.usage_count.desc(),
            KnowledgeItemModel.last_used_at.desc().nullslast()
        ).limit(limit)

        return list(self._session.scalars(stmt).all())

    def get_stats(self, project_id: uuid.UUID) -> dict:
        """Estatísticas do armazenamento."""
        from sqlalchemy import func

        total = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(KnowledgeItemModel.project_id == project_id)
        ) or 0

        validated = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "validated",
            )
        ) or 0

        failed = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "failed",
            )
        ) or 0

        total_usage = self._session.scalar(
            select(func.sum(KnowledgeItemModel.usage_count)).where(
                KnowledgeItemModel.project_id == project_id
            )
        ) or 0

        return {
            "total_items": total,
            "validated": validated,
            "failed": failed,
            "unvalidated": total - validated - failed,
            "total_usage": total_usage,
        }

    def record_usage(
        self,
        item_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        outcome: str = "used",
        success: bool | None = None,
    ) -> None:
        """Registra uso de item."""
        from agent.persistence.models import KnowledgeUsageModel

        item = self.get(item_id)
        if not item:
            return

        usage = KnowledgeUsageModel(
            item_id=item_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            outcome=outcome,
            success=success,
        )
        self._session.add(usage)

        item.usage_count += 1
        item.last_used_at = datetime.now(UTC)

        if success is False:
            # Registrar validação de falha
            from agent.persistence.models import KnowledgeValidationModel
            validation = KnowledgeValidationModel(
                item_id=item_id,
                validation_kind="usage_failure",
                method="task_execution",
                passed=False,
                notes=f"Falha no uso: {outcome}",
            )
            self._session.add(validation)
            item.validation_status = "failed"

        self._session.flush()

    def delete(self, item_id: uuid.UUID) -> bool:
        """Remove item (soft delete - marca como failed)."""
        item = self.get(item_id)
        if not item:
            return False

        item.validation_status = "failed"
        self._indexer.remove_item(item_id)
        self._session.flush()
        return True

    def get_stats(self, project_id: uuid.UUID) -> dict:
        """Estatísticas do armazenamento."""
        from sqlalchemy import func

        total = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(KnowledgeItemModel.project_id == project_id)
        ) or 0

        validated = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "validated",
            )
        ) or 0

        failed = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "failed",
            )
        ) or 0

        total_usage = self._session.scalar(
            select(func.sum(KnowledgeItemModel.usage_count)).where(
                KnowledgeItemModel.project_id == project_id
            )
        ) or 0

        by_kind = {}
        for kind in KnowledgeKind:
            count = self._session.scalar(
                select(func.count(KnowledgeItemModel.id)).where(
                    KnowledgeItemModel.project_id == project_id,
                    KnowledgeItemModel.kind == kind.value,
                )
            ) or 0
            by_kind[kind.value] = count

        return {
            "total_items": total,
            "validated": validated,
            "failed": failed,
            "unvalidated": total - validated - failed,
            "total_usage": total_usage,
            "by_kind": by_kind,
        }