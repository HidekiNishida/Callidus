"""
Arquivo: tests/test_knowledge_graph.py
Nome: test_knowledge_graph.py
Propósito: Verificar a indexação e a busca no grafo de conhecimento do projeto.
Responsabilidade: camada de testes — reindexação do projeto e busca por um símbolo indexado.
Componentes: reindexação com nós e busca por símbolo.
Dependências: agent.knowledge.graph_service e agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.graph_service import KnowledgeGraphService
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


def test_reindex_and_search(session, tmp_path: Path):
    """A reindexação cria os nós do código e a busca encontra o símbolo indexado."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    project = ProjectService(session).create_project(
        ProjectCreate(name="kg", root_path=str(tmp_path))
    )
    kg = KnowledgeGraphService(session)
    stats = kg.reindex(project.id, project.root_path)
    assert stats["nodes"] >= 2
    hits = kg.search(project.id, "hello")
    assert any("hello" in h["label"].lower() or "hello" in h["ref"].lower() for h in hits)
