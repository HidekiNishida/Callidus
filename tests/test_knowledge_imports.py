"""
Arquivo: tests/test_knowledge_imports.py
Nome: test_knowledge_imports.py
Propósito: Verificar a varredura de imports do projeto.
Responsabilidade: camada de testes — registro das arestas de import entre arquivos.
Componentes: aresta de import gerada pela varredura.
Dependências: agent.knowledge.indexer.
Observações: filesystem temporário em tmp_path; a varredura é pura.
"""

from pathlib import Path

from agent.knowledge.indexer import scan_project


def test_scan_records_import_edges(tmp_path: Path):
    """A varredura registra a aresta de import entre os arquivos do pacote."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "util.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "main.py").write_text("from pkg import util\n", encoding="utf-8")
    nodes, edges = scan_project(str(tmp_path))
    imports = [e for e in edges if e["rel"] == "imports"]
    assert imports
    assert any("main.py" in e["src_ref"] for e in imports)
