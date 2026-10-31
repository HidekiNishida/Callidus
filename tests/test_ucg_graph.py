"""
Arquivo: tests/test_ucg_graph.py
Nome: test_ucg_graph.py
Propósito: Verificar o provedor do Unified Cognitive Graph sobre as tabelas existentes — resolução de nós, travessia de arestas e validação de relacionamentos.
Responsabilidade: camada de testes — integração do repositório de grafos com o SQLite isolado.
Componentes: UnifiedGraphService, GraphNodeRef, GraphDomain, GraphNodeKind, GraphRelationKind, GraphDirection.
Dependências: agent.knowledge.graph_service, agent.knowledge.indexer, agent.knowledge.ucg.graph, agent.config, agent.domain.schemas, agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; não toca data/agent.db real.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.knowledge.ucg.graph import UnifiedGraphService
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    NodeNotFoundError,
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
    """Cria um projeto com um módulo Python indexado no grafo de conhecimento."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def hello():\n    return 1\n\nfrom pkg import other\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "other.py").write_text("def world():\n    return 2\n", encoding="utf-8")
    project = ProjectService(session).create_project(
        ProjectCreate(name="ucg", root_path=str(tmp_path))
    )
    KnowledgeGraphService(session).reindex(project.id, project.root_path)
    session.flush()
    return project


def _file_ref(session, project_id, rel_path: str) -> GraphNodeRef | None:
    """Resolve a referência de um arquivo indexado."""
    from agent.persistence.models import KgNodeModel
    from sqlalchemy import func, select

    row = session.scalar(
        select(KgNodeModel).where(
            KgNodeModel.project_id == project_id,
            func.lower(KgNodeModel.kind) == GraphNodeKind.FILE.value.lower(),
            KgNodeModel.ref == rel_path,
        )
    )
    if row is None:
        return None
    return GraphNodeRef(
        id=row.id,
        domain=GraphDomain.KNOWLEDGE,
        kind=GraphNodeKind.FILE,
        source_system="kg",
        source_id=row.ref,
        project_id=project_id,
    )


def test_get_node_resolves_indexed_file(session, project):
    """A resolução de nó encontra um arquivo indexado por caminho."""
    service = UnifiedGraphService(session)
    ref = _file_ref(session, project.id, "pkg/mod.py")
    assert ref is not None
    resolved = service.get_node(ref)
    assert resolved is not None
    assert resolved.kind == GraphNodeKind.FILE
    assert resolved.source_id == "pkg/mod.py"


def test_get_node_unknown_returns_none(session, project):
    """Nó inexistente retorna None em vez de falhar."""
    service = UnifiedGraphService(session)
    ref = GraphNodeRef(
        id=uuid4(), domain=GraphDomain.KNOWLEDGE, kind=GraphNodeKind.FILE,
        source_system="kg", source_id="pkg/nao_existe.py", project_id=project.id,
    )
    assert service.get_node(ref) is None


def test_validate_relationship_allows_and_rejects(session, project):
    """A validação permite relações entre tipos compatíveis e rejeita incompatíveis."""
    service = UnifiedGraphService(session)
    assert service.validate_relationship(
        GraphNodeRef(id=uuid4(), domain=GraphDomain.TASK, kind=GraphNodeKind.TASK,
                     source_system="task", source_id="t1"),
        GraphRelationKind.DEPENDS_ON,
        GraphNodeRef(id=uuid4(), domain=GraphDomain.TASK, kind=GraphNodeKind.TASK,
                     source_system="task", source_id="t2"),
    ) is True
    assert service.validate_relationship(
        GraphNodeRef(id=uuid4(), domain=GraphDomain.KNOWLEDGE, kind=GraphNodeKind.FILE,
                     source_system="kg", source_id="f1"),
        GraphRelationKind.DEPENDS_ON,
        GraphNodeRef(id=uuid4(), domain=GraphDomain.KNOWLEDGE, kind=GraphNodeKind.FILE,
                     source_system="kg", source_id="f2"),
    ) is False


def test_get_neighbors_traverses_kg_edges(session, project):
    """A travessia de vizinhos segue as arestas do grafo de conhecimento."""
    service = UnifiedGraphService(session)
    ref = _file_ref(session, project.id, "pkg/mod.py")
    assert ref is not None
    neighbors = service.get_neighbors(
        ref, direction=GraphDirection.OUTGOING, limit=10
    )
    # pkg/mod.py define a função hello (aresta defines).
    kinds = {node.kind for _, node in neighbors}
    relations = {edge.relation for edge, _ in neighbors}
    assert GraphNodeKind.FUNCTION in kinds
    assert GraphRelationKind.DEFINES in relations


def test_get_neighbors_raises_when_node_missing(session, project):
    """Vizinhos de nó inexistente levantam NodeNotFoundError."""
    service = UnifiedGraphService(session)
    ref = GraphNodeRef(
        id=uuid4(), domain=GraphDomain.KNOWLEDGE, kind=GraphNodeKind.FILE,
        source_system="kg", source_id="pkg/nao_existe.py", project_id=project.id,
    )
    with pytest.raises(NodeNotFoundError):
        service.get_neighbors(ref)
