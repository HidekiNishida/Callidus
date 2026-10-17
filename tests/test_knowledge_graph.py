# tests/test_knowledge_graph.py
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService


@pytest.fixture
def session(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_reindex_and_search(session, tmp_path: Path):
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
