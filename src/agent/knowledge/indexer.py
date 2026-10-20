"""
Arquivo: src/agent/knowledge/indexer.py
Nome: indexer.py
Propósito: indexar arquivos e símbolos do projeto para o grafo de conhecimento.
Responsabilidade: camada de infraestrutura — varredura do projeto e extração de símbolos por AST.
Componentes: scan_project, grep_symbols_in_objective.
Dependências: ast, pathlib, re.
Observações: a varredura é limitada por número de arquivos e ignora dependências e caches.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def _py_import_edges(path: Path, root: Path) -> list[dict]:
    """Arestas de importação de um módulo Python.

    Args:
        path: arquivo Python a analisar.
        root: raiz do projeto, usada para o caminho relativo.

    Returns:
        A lista de arestas `imports`; arquivos com erro de sintaxe não geram arestas.
    """
    rel = str(path.relative_to(root))
    edges: list[dict] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return edges
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.replace(".", "/")
                edges.append({"src_ref": rel, "dst_ref": f"{mod}.py", "rel": "imports"})
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.replace(".", "/")
                edges.append({"src_ref": rel, "dst_ref": f"{mod}.py", "rel": "imports"})
    return edges


def _py_symbols(path: Path, root: Path) -> list[dict]:
    """Símbolos (funções e classes) definidos em um arquivo Python.

    Args:
        path: arquivo Python a analisar.
        root: raiz do projeto, usada para o caminho relativo.

    Returns:
        A lista de símbolos; quando o arquivo não define nenhum, um nó do próprio arquivo.
    """
    rel = str(path.relative_to(root))
    out: list[dict] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return [{"kind": "file", "ref": rel, "label": path.name}]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            out.append({"kind": "function", "ref": f"{rel}::{node.name}", "label": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            out.append({"kind": "class", "ref": f"{rel}::{node.name}", "label": node.name, "line": node.lineno})
    if not out:
        out.append({"kind": "file", "ref": rel, "label": path.name})
    return out


def scan_project(root_path: str, *, max_files: int = 500) -> tuple[list[dict], list[dict]]:
    """Retorna (nodes, edges) para indexação inicial."""
    root = Path(root_path).expanduser().resolve()
    nodes: list[dict] = []
    edges: list[dict] = []
    if not root.is_dir():
        return nodes, edges

    project_node = {"kind": "project", "ref": str(root), "label": root.name}
    nodes.append(project_node)

    count = 0
    for path in root.rglob("*"):
        if count >= max_files:
            break
        if not path.is_file():
            continue
        if any(p in path.parts for p in {".git", ".venv", "node_modules", "__pycache__"}):
            continue
        rel = str(path.relative_to(root))
        if path.suffix == ".py":
            syms = _py_symbols(path, root)
            file_ref = rel
            nodes.append({"kind": "file", "ref": file_ref, "label": path.name})
            edges.append({"src_ref": str(root), "dst_ref": file_ref, "rel": "contains"})
            for sym in syms:
                if sym["kind"] in {"function", "class"}:
                    nodes.append(sym)
                    edges.append({"src_ref": file_ref, "dst_ref": sym["ref"], "rel": "defines"})
            for imp in _py_import_edges(path, root):
                edges.append(imp)
                nodes.append({"kind": "module", "ref": imp["dst_ref"], "label": imp["dst_ref"]})
            if rel.startswith("tests/") or rel.startswith("test_") or "/test_" in rel:
                mod_guess = rel.replace("tests/", "").replace("test_", "").replace(".py", ".py")
                edges.append({"src_ref": file_ref, "dst_ref": mod_guess, "rel": "tests"})
        elif path.suffix in {".md", ".json", ".toml", ".yaml", ".yml"}:
            nodes.append({"kind": "document", "ref": rel, "label": path.name})
            edges.append({"src_ref": str(root), "dst_ref": rel, "rel": "documents"})
        count += 1

    req_node = {"kind": "requirement", "ref": "canonical:objective", "label": "Objetivo canônico"}
    nodes.append(req_node)
    return nodes, edges


def grep_symbols_in_objective(objective: str) -> list[str]:
    """Palavras que parecem identificadores dentro do objetivo da etapa.

    Args:
        objective: texto do objetivo.

    Returns:
        A lista de candidatos a símbolo, na ordem em que aparecem.
    """
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", objective)
