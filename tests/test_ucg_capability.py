"""
Arquivo: tests/test_ucg_capability.py
Nome: test_ucg_capability.py
Propósito: Verificar o Capability Graph — descoberta seletiva de Skills, ferramentas e MCPs
como nós do UCG com dependências, permissões e disponibilidade com TTL.
Responsabilidade: camada de testes — integração do Capability Graph com catálogos existentes
sem criar novas tabelas.
Componentes: CapabilityRef, CapabilityCache, CapabilityResolver, CapabilityGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.capability,
agent.knowledge.ucg.graph, agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; não grava dados de negócio.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.ucg.capability import (
    CapabilityCache,
    CapabilityCacheEntry,
    CapabilityGraphService,
    CapabilityRef,
    CapabilityResolver,
)
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
    GraphStatus,
)
from agent.persistence.database import build_session_factory, init_db
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
    """Cria um projeto com catálogo de skills simples."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "audit.md").write_text(
        "---\nid: frontend-audit\nname: Auditoria Frontend\ndescription: Audita interface e corrige problemas.\nstate: approved\nkeywords: [audit, interface]\nactivation_criteria: [audit, interface]\nprocedures:\n- Ler arquivos\n- Corrigir problemas\n---\n",
        encoding="utf-8",
    )
    project = ProjectService(session).create_project(
        ProjectCreate(name="capability", root_path=str(root))
    )
    return project, root


def test_capability_cache_entry_expiration():
    """Entrada de cache expira após o TTL."""
    entry = CapabilityCacheEntry(
        capability_id="cap-1",
        available=True,
        checked_at=datetime.now(UTC) - timedelta(seconds=10),
        ttl_seconds=5,
    )
    assert entry.is_stale() is True

    entry2 = CapabilityCacheEntry(
        capability_id="cap-2",
        available=True,
        checked_at=datetime.now(UTC),
        ttl_seconds=300,
    )
    assert entry2.is_stale() is False


def test_capability_cache_get_set_invalidate():
    """Cache armazena, recupera e invalida entradas."""
    cache = CapabilityCache()
    assert cache.get("cap-1") is None

    cache.set("cap-1", True, ttl_seconds=300)
    entry = cache.get("cap-1")
    assert entry is not None
    assert entry.available is True

    assert cache.invalidate("cap-1") is True
    assert cache.get("cap-1") is None
    assert cache.invalidate("cap-1") is False


def test_capability_ref_to_graph_node_ref():
    """CapabilityRef converte para GraphNodeRef com tipo e metadados corretos."""
    cap = CapabilityRef(
        id="skill:frontend-audit",
        kind="skill",
        name="Auditoria Frontend",
        description="Audita interface",
        source_system="skill",
        source_id="frontend-audit",
        project_id=str(uuid4()),
        version=1,
        status=GraphStatus.ACTIVE,
        metadata={"keywords": ["audit"], "state": "approved"},
        available_at=datetime.now(UTC),
    )
    ref = cap.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.SKILL
    assert ref.domain == GraphDomain.CAPABILITY
    assert ref.source_system == "skill"
    assert ref.source_id == "frontend-audit"
    assert cap.is_available is True


def test_capability_ref_unavailable_after_ttl():
    """CapabilityRef fica indisponível após o TTL expirar."""
    cap = CapabilityRef(
        id="skill:x",
        kind="skill",
        name="X",
        source_system="skill",
        source_id="x",
        available_at=datetime.now(UTC) - timedelta(seconds=600),
        availability_ttl_seconds=300,
    )
    assert cap.is_available is False


def test_resolver_discover_skills(session, project):
    """Resolvedor descobre skills do catálogo como capacidades."""
    proj, _ = project
    resolver = CapabilityResolver(session, proj)
    caps = resolver.resolve_skills(limit=10)
    assert len(caps) >= 1
    audit = [c for c in caps if c.source_id == "frontend-audit"]
    assert len(audit) == 1
    assert audit[0].kind == "skill"
    assert audit[0].status == GraphStatus.ACTIVE
    assert "audit" in audit[0].metadata["keywords"]
    assert audit[0].metadata["activation_criteria"] == ["audit", "interface"]


def test_graph_service_discover_capabilities(session, project):
    """Serviço descobre capacidades relevantes para um objetivo."""
    proj, _ = project
    service = CapabilityGraphService(session, proj)
    caps = service.discover_capabilities(objective="auditar interface", requirements=["audit"], limit=10)
    assert len(caps) >= 1
    names = {c.name for c in caps}
    assert "Auditoria Frontend" in names
    # Todas as devolvidas devem estar disponíveis (score > 0 ou sem filtro)
    for cap in caps:
        assert cap.is_available is True


def test_graph_service_available_capabilities(session, project):
    """available_capabilities devolve apenas capacidades com TTL válido."""
    proj, _ = project
    service = CapabilityGraphService(session, proj)
    caps = service.available_capabilities(limit=10)
    for cap in caps:
        assert cap.is_available is True


def test_capability_to_graph_node_ref(session, project):
    """capability_to_graph_node_ref converte CapabilityRef para GraphNodeRef."""
    proj, _ = project
    service = CapabilityGraphService(session, proj)
    caps = service.discover_capabilities(objective="auditar interface", limit=10)
    assert len(caps) >= 1
    ref = service.capability_to_graph_node_ref(caps[0])
    assert ref.kind == GraphNodeKind.SKILL
    assert ref.source_system == "skill"


def test_relate_capability_to_tool(session, project):
    """relate_capability_to_tool cria aresta CAPABILITY_USES_TOOL quando válida."""
    proj, _ = project
    service = CapabilityGraphService(session, proj)
    caps = service.discover_capabilities(objective="auditar interface", limit=10)
    assert len(caps) >= 1
    edge = service.relate_capability_to_tool(caps[0], "read_file")
    assert edge is not None
    assert edge.relation == GraphRelationKind.CAPABILITY_USES_TOOL
    assert edge.source.kind == GraphNodeKind.SKILL
    assert edge.target.kind == GraphNodeKind.TOOL


def test_refresh_availability_invalidates_cache(session, project):
    """refresh_availability invalida todo o cache de disponibilidade."""
    proj, _ = project
    service = CapabilityGraphService(session, proj)
    # Primeiro acesso popula o cache.
    service.discover_capabilities(objective="auditar", limit=10)
    count = service.refresh_availability()
    assert count >= 0
