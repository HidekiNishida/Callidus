"""
Arquivo: tests/test_knowledge_engine.py
Nome: test_knowledge_engine.py
Propósito: testes unitários do Knowledge Engine core.
Responsabilidade: camada de teste — verifica discovery, request, service.
Dependências: pytest, agent.knowledge, sqlalchemy.
Observações: usa banco SQLite em memória para isolamento.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from agent.knowledge import (
    KnowledgeEngineService,
    KnowledgeDiscovery,
    KnowledgeRequestCreate,
    KnowledgeDepth,
    KnowledgeKind,
    KnowledgeSourceKind,
    KnowledgeValidationStatus,
)
from agent.knowledge.models import KnowledgeItemModel, KnowledgeRequestModel
from agent.persistence.models import Base


@pytest.fixture
def db_session() -> Session:
    """Cria sessão SQLite em memória para testes."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def task_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def agent_id() -> uuid.UUID:
    return uuid.uuid4()


class TestKnowledgeDiscovery:
    """Testes do KnowledgeDiscovery."""

    def test_should_acquire_low_confidence(self):
        """Deve acionar aquisição quando confiança baixa."""
        discovery = KnowledgeDiscovery(min_confidence=0.6)
        should_acquire, gap = discovery.should_acquire(
            model_confidence=0.3,
            context_has_answer=False,
            repeated_failures=0,
            requires_updated_info=False,
            needs_specialized_docs=False,
            complexity_score=0.5,
        )
        assert should_acquire is True
        assert gap is not None
        assert gap.confidence > 0.5

    def test_should_not_acquire_high_confidence(self):
        """Não deve acionar quando confiança alta e contexto tem resposta."""
        discovery = KnowledgeDiscovery(min_confidence=0.6)
        should_acquire, gap = discovery.should_acquire(
            model_confidence=0.9,
            context_has_answer=True,
            repeated_failures=0,
            requires_updated_info=False,
            needs_specialized_docs=False,
            complexity_score=0.3,
        )
        assert should_acquire is False
        assert gap is None

    def test_should_acquire_repeated_failures(self):
        """Deve acionar após falhas repetidas."""
        discovery = KnowledgeDiscovery(max_repeated_failures=2)
        should_acquire, gap = discovery.should_acquire(
            model_confidence=0.7,
            context_has_answer=True,
            repeated_failures=3,
            requires_updated_info=False,
            needs_specialized_docs=False,
            complexity_score=0.5,
        )
        assert should_acquire is True
        assert "falhas repetidas" in gap.description

    def test_should_acquire_requires_updated_info(self):
        """Deve acionar quando precisa info atualizada."""
        discovery = KnowledgeDiscovery()
        should_acquire, gap = discovery.should_acquire(
            model_confidence=0.8,
            context_has_answer=True,
            repeated_failures=0,
            requires_updated_info=True,
            needs_specialized_docs=False,
            complexity_score=0.4,
        )
        assert should_acquire is True
        assert "atualizada" in gap.description

    def test_create_request_from_gap(self):
        """Cria request a partir de gap."""
        discovery = KnowledgeDiscovery()
        gap = discovery.should_acquire(
            model_confidence=0.3,
            context_has_answer=False,
            repeated_failures=0,
            requires_updated_info=False,
            needs_specialized_docs=False,
            complexity_score=0.5,
        )[1]

        project_id = uuid.uuid4()
        request = discovery.create_request_from_gap(gap, project_id)

        assert isinstance(request, KnowledgeRequestCreate)
        assert request.project_id == project_id
        assert request.depth in (KnowledgeDepth.QUICK, KnowledgeDepth.STANDARD, KnowledgeDepth.DEEP, KnowledgeDepth.COMPREHENSIVE)


class TestKnowledgeEngineService:
    """Testes do KnowledgeEngineService."""

    def test_create_and_get_request(self, db_session: Session, project_id: uuid.UUID):
        """Cria e recupera request."""
        service = KnowledgeEngineService(db_session)

        request_data = KnowledgeRequestCreate(
            project_id=project_id,
            question="Como usar asyncio?",
            depth=KnowledgeDepth.STANDARD,
        )

        request = service.create_request(request_data)
        assert request.id is not None
        assert request.status == "pending"

        # Recuperar
        retrieved = db_session.get(KnowledgeRequestModel, request.id)
        assert retrieved is not None
        assert retrieved.question == "Como usar asyncio?"

    def test_update_request_status(self, db_session: Session, project_id: uuid.UUID):
        """Atualiza status do request."""
        service = KnowledgeEngineService(db_session)

        request_data = KnowledgeRequestCreate(
            project_id=project_id,
            question="Test question",
        )
        request = service.create_request(request_data)

        # Atualizar para in_progress
        updated = service.update_request_status(request.id, "in_progress")
        assert updated.status == "in_progress"
        assert updated.started_at is not None

        # Atualizar para completed
        completed = service.update_request_status(request.id, "completed")
        assert completed.status == "completed"
        assert completed.completed_at is not None

    def test_save_and_search_knowledge(self, db_session: Session, project_id: uuid.UUID):
        """Salva e busca conhecimento."""
        service = KnowledgeEngineService(db_session)

        item = service.save_knowledge(
            project_id=project_id,
            kind=KnowledgeKind.SOLUTION.value,
            title="AsyncIO Pattern",
            content="Use asyncio.gather...",
            summary="Pattern for concurrent requests",
            technology="python",
            version="3.11",
            confidence=0.85,
            sources=[{"source_kind": "documentation", "title": "Python docs", "credibility": 0.9}],
        )

        assert item.id is not None
        assert item.source_count == 1

        # Buscar
        results = service.search_knowledge(project_id, "async", technology="python")
        assert len(results) == 1
        assert results[0].title == "AsyncIO Pattern"

    def test_save_knowledge_with_sources(self, db_session: Session, project_id: uuid.UUID):
        """Salva conhecimento com múltiplas fontes."""
        service = KnowledgeEngineService(db_session)

        item = service.save_knowledge(
            project_id=project_id,
            kind=KnowledgeKind.FACT.value,
            title="Python 3.11 features",
            content="New features include...",
            sources=[
                {"source_kind": "documentation", "title": "Python 3.11 release notes", "credibility": 0.95},
                {"source_kind": "web_search", "title": "Real Python article", "credibility": 0.7},
            ],
        )

        assert item.source_count == 2

        # Verificar fontes salvas
        from agent.persistence.models import KnowledgeSourceModel
        sources = list(db_session.scalars(
            select(KnowledgeSourceModel).where(KnowledgeSourceModel.item_id == item.id)
        ).all())
        assert len(sources) == 2

    def test_record_usage_success(self, db_session: Session, project_id: uuid.UUID):
        """Registra uso bem-sucedido."""
        service = KnowledgeEngineService(db_session)

        item = service.save_knowledge(
            project_id=project_id,
            kind=KnowledgeKind.SOLUTION.value,
            title="Test",
            content="Content",
            confidence=0.8,
        )

        service.record_usage(
            item_id=item.id,
            task_id=uuid.uuid4(),
            outcome="used_in_generation",
            success=True,
        )

        item_refreshed = db_session.get(KnowledgeItemModel, item.id)
        assert item_refreshed.usage_count == 1
        assert item_refreshed.last_used_at is not None

    def test_record_usage_failure_creates_validation(self, db_session: Session, project_id: uuid.UUID):
        """Falha no uso cria validação de falha."""
        service = KnowledgeEngineService(db_session)

        item = service.save_knowledge(
            project_id=project_id,
            kind=KnowledgeKind.SOLUTION.value,
            title="Test",
            content="Content",
            confidence=0.8,
        )

        service.record_usage(
            item_id=item.id,
            outcome="generation_failed",
            success=False,
            evidence_ref="ev_123",
        )

        from agent.persistence.models import KnowledgeValidationModel
        validations = list(db_session.scalars(
            select(KnowledgeValidationModel).where(KnowledgeValidationModel.item_id == item.id)
        ).all())

        assert len(validations) == 1
        assert validations[0].passed is False
        assert validations[0].validation_kind == "usage_failure"

    def test_add_validation_updates_item_status(self, db_session: Session, project_id: uuid.UUID):
        """Validação atualiza status do item."""
        service = KnowledgeEngineService(db_session)

        item = service.save_knowledge(
            project_id=project_id,
            kind=KnowledgeKind.FACT.value,
            title="Test",
            content="Content",
            confidence=0.5,
        )

        # Validar
        validation = service.add_validation(
            item_id=item.id,
            validation_kind="code_review",
            passed=True,
            validated_by="test_user",
        )

        assert validation.passed is True
        item_refreshed = db_session.get(KnowledgeItemModel, item.id)
        assert item_refreshed.validation_status == KnowledgeValidationStatus.VALIDATED.value

        # Invalidar
        validation2 = service.add_validation(
            item_id=item.id,
            validation_kind="test",
            passed=False,
            validated_by="test_user",
        )

        item_refreshed2 = db_session.get(KnowledgeItemModel, item.id)
        assert item_refreshed2.validation_status == KnowledgeValidationStatus.FAILED.value

    def test_get_stats(self, db_session: Session, project_id: uuid.UUID):
        """Estatísticas do knowledge engine."""
        service = KnowledgeEngineService(db_session)

        # Criar alguns itens
        service.save_knowledge(project_id=project_id, kind="fact", title="Fact 1", content="C1", confidence=0.9)
        service.save_knowledge(project_id=project_id, kind="solution", title="Sol 1", content="C2", confidence=0.8)
        service.save_knowledge(project_id=project_id, kind="solution", title="Sol 2", content="C3", confidence=0.7)

        stats = service.get_stats(project_id)
        assert stats["total_items"] == 3
        assert stats["by_kind"]["fact"] == 1
        assert stats["by_kind"]["solution"] == 2
        assert stats["total_usage"] == 0


class TestKnowledgeModels:
    """Testes dos modelos de dados."""

    def test_knowledge_item_creation(self, db_session: Session, project_id: uuid.UUID):
        """Criação de KnowledgeItemModel."""
        item = KnowledgeItemModel(
            project_id=project_id,
            kind="solution",
            title="Test Solution",
            content="Solution content",
            technology="python",
            version="3.11",
            confidence=0.8,
            validation_status="unvalidated",
        )
        db_session.add(item)
        db_session.flush()

        assert item.id is not None
        assert item.created_at is not None
        assert item.updated_at is not None

    def test_knowledge_source_relationship(self, db_session: Session, project_id: uuid.UUID):
        """Relacionamento item-fonte."""
        item = KnowledgeItemModel(
            project_id=project_id,
            kind="fact",
            title="Fact",
            content="Content",
        )
        db_session.add(item)
        db_session.flush()

        from agent.persistence.models import KnowledgeSourceModel
        source = KnowledgeSourceModel(
            item_id=item.id,
            source_kind="documentation",
            title="Doc Title",
            url="https://example.com",
            credibility=0.9,
        )
        db_session.add(source)
        db_session.flush()

        # Verificar relationship
        assert len(item.sources) == 1
        assert item.sources[0].title == "Doc Title"

    def test_knowledge_validation_status_enum(self):
        """Enum de status de validação."""
        assert KnowledgeValidationStatus.VALIDATED.value == "validated"
        assert KnowledgeValidationStatus.FAILED.value == "failed"
        assert KnowledgeValidationStatus.UNVALIDATED.value == "unvalidated"
        assert KnowledgeValidationStatus.OUTDATED.value == "outdated"

    def test_knowledge_kind_enum(self):
        """Enum de tipos de conhecimento."""
        assert KnowledgeKind.FACT.value == "fact"
        assert KnowledgeKind.SOLUTION.value == "solution"
        assert KnowledgeKind.PATTERN.value == "pattern"
        assert KnowledgeKind.DECISION.value == "decision"

    def test_knowledge_source_kind_enum(self):
        """Enum de tipos de fonte."""
        assert KnowledgeSourceKind.WEB_SEARCH.value == "web_search"
        assert KnowledgeSourceKind.GITHUB.value == "github"
        assert KnowledgeSourceKind.DOCUMENTATION.value == "documentation"
        assert KnowledgeSourceKind.AI_SERVICE.value == "ai_service"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])