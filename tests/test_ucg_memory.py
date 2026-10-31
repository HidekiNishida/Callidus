"""
Arquivo: tests/test_ucg_memory.py
Nome: test_ucg_memory.py
Propósito: Verificar o Memory Graph — memórias existentes expostas como nós do UCG com
validade temporal, confiança e promoção controlada.
Responsabilidade: camada de testes — integração do Memory Graph com as camadas de memória
existentes sem criar novas tabelas.
Componentes: MemoryNodeRef, MemoryValidity, MemoryConflict, MemoryGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.memory,
agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; não grava dados de negócio.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.ucg.memory import (
    DEFAULT_MAX_AGE_DAYS,
    MemoryConflict,
    MemoryGraphService,
    MemoryNodeRef,
    MemoryValidity,
    PROMOTION_MIN_CONFIDENCE,
)
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
    GraphStatus,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import MemoryRecordModel
from agent.services.project_service import ProjectService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


@pytest.fixture
def project(session, tmp_path: Path):
    """Cria um projeto com registros de memória."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="memory", root_path=str(tmp_path / "root"))
    )
    now = datetime.now(UTC)
    rows = [
        MemoryRecordModel(
            project_id=project.id,
            kind="canonical",
            title="Arquitetura do projeto",
            content="O Callidus usa SQLite como estado verdadeiro.",
            summary="Estado verdadeiro no SQLite.",
            version=1,
            source_refs_json=["src/agent/persistence/models.py"],
            created_at=now - timedelta(days=5),
        ),
        MemoryRecordModel(
            project_id=project.id,
            kind="operational",
            title="Próxima ação da tarefa",
            content="Continuar a implementação da Fase 4.",
            summary="Continuar Fase 4.",
            version=1,
            source_refs_json=[],
            created_at=now - timedelta(days=1),
        ),
        MemoryRecordModel(
            project_id=project.id,
            kind="evidence",
            title="Teste passou",
            content="Todos os testes da suíte passaram.",
            summary="Suíte verde.",
            version=1,
            source_refs_json=[],
            created_at=now - timedelta(days=2),
        ),
    ]
    for row in rows:
        session.add(row)
    session.flush()
    return project


def test_memory_validity_not_expired():
    """Valididade não expirada quando dentro da janela."""
    validity = MemoryValidity(
        valid_from=datetime.now(UTC) - timedelta(days=5),
        max_age_days=DEFAULT_MAX_AGE_DAYS,
    )
    assert validity.is_expired is False


def test_memory_validity_expired_by_age():
    """Valididade expira quando a idade máxima é excedida."""
    validity = MemoryValidity(
        valid_from=datetime.now(UTC) - timedelta(days=100),
        max_age_days=DEFAULT_MAX_AGE_DAYS,
    )
    assert validity.is_expired is True


def test_memory_validity_expired_by_until():
    """Valididade expira quando valid_until é alcançado."""
    validity = MemoryValidity(
        valid_from=datetime.now(UTC) - timedelta(days=5),
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    assert validity.is_expired is True


def test_memory_node_ref_to_graph_node_ref():
    """MemoryNodeRef converte para GraphNodeRef com tipo MEMORY/Knowledge."""
    mem = MemoryNodeRef(
        id="mem-1",
        kind="canonical",
        title="Arquitetura",
        summary="Estado verdadeiro no SQLite.",
        project_id=str(uuid4()),
        version=1,
        status=GraphStatus.ACTIVE,
        confidence=0.9,
        validity=MemoryValidity(
            valid_from=datetime.now(UTC),
            max_age_days=DEFAULT_MAX_AGE_DAYS,
        ),
        source_refs=["src/agent/persistence/models.py"],
        created_at=datetime.now(UTC),
    )
    ref = mem.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.KNOWLEDGE
    assert ref.domain == GraphDomain.MEMORY
    assert ref.source_system == "memory"
    assert ref.source_id == "mem-1"
    assert mem.is_valid is True
    assert mem.is_reusable is True


def test_memory_node_ref_expired_not_reusable():
    """Memória expirada não é válida nem reutilizável."""
    mem = MemoryNodeRef(
        id="mem-expired",
        kind="execution",
        title="Antiga",
        project_id=str(uuid4()),
        status=GraphStatus.ACTIVE,
        confidence=0.9,
        validity=MemoryValidity(
            valid_from=datetime.now(UTC) - timedelta(days=100),
            max_age_days=DEFAULT_MAX_AGE_DAYS,
        ),
        created_at=datetime.now(UTC) - timedelta(days=100),
    )
    assert mem.is_valid is False
    assert mem.is_reusable is False


def test_memory_graph_discover_memories(session, project):
    """Serviço descobre memórias relevantes para o projeto."""
    proj = project
    service = MemoryGraphService(session)
    mems = service.discover_memories(
        project_id=proj.id, objective="arquitetura", limit=10
    )
    assert len(mems) >= 1
    titles = {m.title for m in mems}
    assert "Arquitetura do projeto" in titles
    for m in mems:
        assert m.is_valid is True


def test_memory_graph_only_reusable(session, project):
    """only_reusable filtra memórias com confiança baixa."""
    proj = project
    service = MemoryGraphService(session)
    mems = service.discover_memories(
        project_id=proj.id, objective="qualquer", limit=10, only_reusable=True
    )
    for m in mems:
        assert m.is_reusable is True


def test_memory_graph_relate_memory_to_task(session, project):
    """relate_memory_to_task cria aresta USED_IN entre memória e tarefa."""
    proj = project
    service = MemoryGraphService(session)
    mems = service.discover_memories(project_id=proj.id, limit=1)
    assert len(mems) >= 1
    edge = service.relate_memory_to_task(mems[0], str(uuid4()))
    assert edge is not None
    assert edge.relation == GraphRelationKind.USED_IN


def test_memory_graph_detect_conflicts(session, project):
    """detect_conflicts identifica memórias com mesmo título e conteúdo diferente."""
    proj = project
    service = MemoryGraphService(session)
    mems = [
        MemoryNodeRef(
            id="a",
            kind="canonical",
            title="Fato X",
            content="valor 1",
            project_id=str(proj.id),
        ),
        MemoryNodeRef(
            id="b",
            kind="canonical",
            title="Fato X",
            content="valor 2",
            project_id=str(proj.id),
        ),
    ]
    conflicts = service.detect_conflicts(mems)
    assert len(conflicts) >= 1
    assert conflicts[0].fact == "Fato X"
    assert conflicts[0].category == "valor"


def test_memory_graph_promote_to_semantic_requires_validation(session, project):
    """promote_to_semantic retorna None quando não validado."""
    proj = project
    service = MemoryGraphService(session)
    mem = MemoryNodeRef(
        id="mem-1",
        kind="operational",
        title="Episódica",
        project_id=str(proj.id),
        confidence=0.6,
    )
    promoted = service.promote_to_semantic(mem, validated=False)
    assert promoted is None


def test_memory_graph_promote_to_semantic_when_validated(session, project):
    """promote_to_semantic promove para canonical quando validado."""
    proj = project
    service = MemoryGraphService(session)
    mem = MemoryNodeRef(
        id="mem-1",
        kind="operational",
        title="Episódica validada",
        project_id=str(proj.id),
        confidence=0.7,
    )
    promoted = service.promote_to_semantic(
        mem, validated=True, evidence_id="ev-1", confidence=0.9
    )
    assert promoted is not None
    assert promoted.kind == "canonical"
    assert promoted.title == "Promovido: Episódica validada"
    assert promoted.confidence >= 0.9
    assert "ev-1" in promoted.source_refs
    assert promoted.metadata["promoted_from"] == "mem-1"
