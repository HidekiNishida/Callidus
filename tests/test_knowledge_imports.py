# tests/test_knowledge_imports.py
from pathlib import Path

from agent.knowledge.indexer import scan_project


def test_scan_records_import_edges(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "util.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "main.py").write_text("from pkg import util\n", encoding="utf-8")
    nodes, edges = scan_project(str(tmp_path))
    imports = [e for e in edges if e["rel"] == "imports"]
    assert imports
    assert any("main.py" in e["src_ref"] for e in imports)
