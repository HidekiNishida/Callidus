"""
Arquivo: tests/test_knowledge_memory.py
Nome: test_knowledge_memory.py
Propósito: testes da memória do Knowledge Engine (store, reuse).
Responsabilidade: camada de teste — verifica CRUD, busca, recuperação contextual.
Dependências: pytest, agent.knowledge.memory.
Observações: usa banco SQLite em memória.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.knowledge.memory import (
    KnowledgeMemoryStore,
    KnowledgeReuser,
    ContextualRetriever,
    BudgetAwareInjector,
)
from agent.knowledge.models import KnowledgeValidationStatus
from agent.persistence.models import Base


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def store(db_session: Session) -> KnowledgeMemoryStore:
    return KnowledgeMemoryStore(db_session)


class TestKnowledgeMemoryStore:
    """Testes do KnowledgeMemoryStore."""

    def test_save_and_get(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Salva e recupera item."""
        store.initialize()

        item = store.save(
            project_id=project_id,
            kind="solution",
            title="Test Solution",
            content="Solution content",
            summary="Summary",
            technology="python",
            version="3.11",
            confidence=0.85,
            sources=[{"source_kind": "documentation", "title": "Doc", "credibility": 0.9}],
        )

        assert item.id is not None
        assert item.title == "Test Solution"

        # Recuperar
        retrieved = store.get(item.id)
        assert retrieved is not None
        assert retrieved.title == "Test Solution"

    def test_save_with_deduplication(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Deduplicação impede itens idênticos."""
        store.initialize()

        # Primeiro item
        item1 = store.save(
            project_id=project_id,
            kind="fact",
            title="Same Title",
            content="Same content",
            technology="python",
            confidence=0.8,
        )

        # Segundo item idêntico
        item2 = store.save(
            project_id=project_id,
            kind="fact",
            title="Same Title",
            content="Same content",
            technology="python",
            confidence=0.7,
        )

        # Deve ser o mesmo item (deduplicado)
        assert item1.id == item2.id
        # Confiança deve ser a maior
        assert item1.confidence == 0.8

    def test_update_creates_version(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Atualização cria versão histórica."""
        store.initialize()

        item = store.save(
            project_id=project_id,
            kind="solution",
            title="Original Title",
            content="Original content",
        )

        original_id = item.id

        # Atualizar
        updated = store.update(item_id=original_id, title="Updated Title")

        assert updated.id == original_id
        assert updated.title == "Updated Title"

        # Verificar versão criada
        from agent.persistence.models import KnowledgeVersionModel
        versions = store._session.query(KnowledgeVersionModel).filter(
            KnowledgeVersionModel.item_id == original_id
        ).all()
        assert len(versions) == 1
        assert versions[0].title == "Original Title"

    def test_search_with_filters(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Busca com múltiplos filtros."""
        store.initialize()

        store.save(project_id=project_id, kind="fact", title="Fact 1", content="C1", technology="python", confidence=0.9)
        store.save(project_id=project_id, kind="solution", title="Sol 1", content="C2", technology="python", confidence=0.8)
        store.save(project_id=project_id, kind="solution", title="Sol 2", content="C3", technology="javascript", confidence=0.7)

        # Busca por tecnologia
        python_results = store.search(project_id, "", technology="python")
        assert len(python_results) == 2

        js_results = store.search(project_id, "", technology="javascript")
        assert len(js_results) == 1

        # Busca por kind
        fact_results = store.search(project_id, "", kind="fact")
        assert len(fact_results) == 1

        # Busca por confiança mínima
        high_conf = store.search(project_id, "", min_confidence=0.85)
        assert len(high_conf) == 1

    def test_search_by_context_tags(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Busca por tags de contexto."""
        store.initialize()

        store.save(
            project_id=project_id,
            kind="fact",
            title="Tagged",
            content="Content",
            context_tags=["api", "rest"],
        )
        store.save(
            project_id=project_id,
            kind="fact",
            title="Untagged",
            content="Content",
        )

        tagged = store.search_by_context(project_id, ["api"])
        assert len(tagged) == 1
        assert tagged[0].title == "Tagged"

    def test_record_usage(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Registra uso."""
        store.initialize()

        item = store.save(project_id=project_id, kind="fact", title="Test", content="Content")

        store.record_usage(item.id, outcome="used", success=True)

        item_refreshed = store.get(item.id)
        assert item_refreshed.usage_count == 1
        assert item_refreshed.last_used_at is not None

    def test_record_usage_failure(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Falha no uso marca item como failed."""
        store.initialize()

        item = store.save(project_id=project_id, kind="solution", title="Test", content="Content")

        store.record_usage(item.id, outcome="failed", success=False)

        item_refreshed = store.get(item.id)
        assert item_refreshed.validation_status == "failed"

    def test_get_stats(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Estatísticas."""
        store.initialize()

        store.save(project_id=project_id, kind="fact", title="F1", content="C", confidence=0.9)
        store.save(project_id=project_id, kind="solution", title="S1", content="C", confidence=0.8)
        store.save(project_id=project_id, kind="solution", title="S2", content="C", confidence=0.7)

        stats = store.get_stats(project_id)
        assert stats["total_items"] == 3
        assert stats["by_kind"]["fact"] == 1
        assert stats["by_kind"]["solution"] == 2
        assert stats["unvalidated"] == 3

    def test_delete_marks_failed(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Delete marca como failed (soft delete)."""
        store.initialize()

        item = store.save(project_id=project_id, kind="fact", title="Test", content="Content")

        result = store.delete(item.id)
        assert result is True

        item_refreshed = store.get(item.id)
        assert item_refreshed.validation_status == "failed"

    def test_get_with_sources(self, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Recupera item com fontes."""
        store.initialize()

        item = store.save(
            project_id=project_id,
            kind="fact",
            title="Test",
            content="Content",
            sources=[{"source_kind": "documentation", "title": "Doc", "credibility": 0.9}],
        )

        data = store.get_with_sources(item.id)
        assert data is not None
        assert "item" in data
        assert "sources" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0].title == "Doc"


class TestContextualRetriever:
    """Testes do ContextualRetriever."""

    @pytest.fixture
    def store(self, db_session: Session) -> KnowledgeMemoryStore:
        return KnowledgeMemoryStore(db_session)

    @pytest.fixture
    def retriever(self, store: KnowledgeMemoryStore) -> ContextualRetriever:
        store.initialize()
        return ContextualRetriever(store)

    @pytest.fixture
    def project_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def test_retrieve_for_task(self, retriever: ContextualRetriever, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Recupera conhecimento para task."""
        store.save(project_id=project_id, kind="solution", title="AsyncIO Pattern", content="Use asyncio.gather", technology="python", confidence=0.9)
        store.save(project_id=project_id, kind="fact", title="Python version", content="3.11", technology="python", confidence=0.8)
        store.save(project_id=project_id, kind="fact", title="JS Promises", content="Use Promise.all", technology="javascript", confidence=0.7)

        results = retriever.retrieve_for_task(
            project_id=project_id,
            task_objective="Como fazer requisições HTTP concorrentes em Python?",
            task_technology="python",
            max_items=3,
        )

        assert len(results) > 0
        # Python items should rank higher due to technology match
        python_results = [r for r in results if r.technology == "python"]
        assert len(python_results) >= 1
        # First result should be Python (higher score due to tech match)
        assert results[0].technology == "python"

    def test_retrieve_prioritizes_validated(self, retriever: ContextualRetriever, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Prioriza itens validados."""
        item1 = store.save(project_id=project_id, kind="solution", title="Validated", content="Content", technology="python", confidence=0.8)
        item2 = store.save(project_id=project_id, kind="solution", title="Unvalidated", content="Content", technology="python", confidence=0.8)

        # Validar o primeiro item usando o service
        from agent.knowledge.service import KnowledgeEngineService
        from agent.knowledge.models import KnowledgeValidationStatus
        service = KnowledgeEngineService(store._session)
        service.add_validation(
            item_id=item1.id,
            validation_kind="test",
            passed=True,
            validated_by="test",
        )

        results = retriever.retrieve_for_task(
            project_id=project_id,
            task_objective="Test",
            task_technology="python",
            prefer_validated=True,
        )

        # Validado deve vir primeiro
        assert results[0].title == "Validated"


class TestBudgetAwareInjector:
    """Testes do BudgetAwareInjector."""

    def test_inject_within_budget(self):
        """Injeção dentro do orçamento."""
        from agent.knowledge.memory.reuse import RetrievedKnowledge

        injector = BudgetAwareInjector(max_tokens=1000)

        items = [
            RetrievedKnowledge(
                item_id=uuid.uuid4(), title="Item 1", summary="S1", key_content="Content 1",
                technology="python", confidence=0.9, validation_status="validated",
                usage_count=1, citation="C1", tokens_estimate=100,
            ),
            RetrievedKnowledge(
                item_id=uuid.uuid4(), title="Item 2", summary="S2", key_content="Content 2",
                technology="python", confidence=0.8, validation_status="validated",
                usage_count=1, citation="C2", tokens_estimate=150,
            ),
        ]

        injected, formatted = injector.inject(items, current_context_tokens=0)

        assert len(injected) == 2
        assert "Item 1" in formatted
        assert "Item 2" in formatted

    def test_inject_exceeds_budget(self):
        """Injeção excede orçamento - deve cortar."""
        from agent.knowledge.memory.reuse import RetrievedKnowledge

        injector = BudgetAwareInjector(max_tokens=200)

        items = [
            RetrievedKnowledge(
                item_id=uuid.uuid4(), title="Item 1", summary="S1", key_content="Content 1",
                technology="python", confidence=0.9, validation_status="validated",
                usage_count=1, citation="C1", tokens_estimate=150,
            ),
            RetrievedKnowledge(
                item_id=uuid.uuid4(), title="Item 2", summary="S2", key_content="Content 2",
                technology="python", confidence=0.8, validation_status="validated",
                usage_count=1, citation="C2", tokens_estimate=150,
            ),
        ]

        injected, formatted = injector.inject(items, current_context_tokens=0)

        # Só deve caber o primeiro
        assert len(injected) == 1
        assert injected[0].title == "Item 1"

    def test_budget_status(self):
        """Status do orçamento."""
        injector = BudgetAwareInjector(max_tokens=1000)

        status = injector.get_budget_status(used_tokens=300)
        assert status["used"] == 300
        assert status["available"] == 900  # 1000 - 100 reserve
        assert status["remaining"] == 600  # 900 - 300
        assert status["usage_ratio"] == 300 / 900


class TestKnowledgeReuser:
    """Testes do KnowledgeReuser."""

    @pytest.fixture
    def store(self, db_session: Session) -> KnowledgeMemoryStore:
        return KnowledgeMemoryStore(db_session)

    @pytest.fixture
    def reuser(self, store: KnowledgeMemoryStore) -> KnowledgeReuser:
        store.initialize()
        return KnowledgeReuser(store)

    @pytest.fixture
    def project_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def test_prepare_context_for_task(self, reuser: KnowledgeReuser, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Prepara contexto para task."""
        store.save(project_id=project_id, kind="solution", title="AsyncIO", content="Use asyncio.gather", technology="python", confidence=0.9)

        result = reuser.prepare_context_for_task(
            project_id=project_id,
            task_objective="Requisições concorrentes",
            task_technology="python",
            max_items=2,
        )

        assert result.query == "Requisições concorrentes"
        assert result.sources_consulted >= 1
        assert result.total_tokens > 0
        assert result.budget_used <= 1.0

    def test_format_for_prompt(self, reuser: KnowledgeReuser, store: KnowledgeMemoryStore, project_id: uuid.UUID):
        """Formata para prompt."""
        store.save(project_id=project_id, kind="solution", title="Pattern", content="Use asyncio", technology="python")

        result = reuser.prepare_context_for_task(
            project_id=project_id,
            task_objective="Test",
            task_technology="python",
        )

        formatted = reuser.format_for_prompt(result)

        assert "CONHECIMENTO RELEVANTE" in formatted
        assert "Pattern" in formatted
        assert "asyncio" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])