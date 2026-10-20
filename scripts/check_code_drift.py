#!/usr/bin/env python3
"""
Arquivo: scripts/check_code_drift.py
Nome: check_code_drift.py
Propósito: detectar se a edição de um arquivo Python alterou código além de comentários e docstrings.
Responsabilidade: script de verificação — compara a árvore sintática sem docstrings entre o Git (HEAD) e a árvore de trabalho.
Componentes: main, stripped_tree, compare.
Dependências: ast, subprocess, pathlib (somente biblioteca padrão).
Observações: usado na auditoria final — uma refatoração que mexe em docstrings não pode mudar o comportamento.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove docstrings de um corpo de classe ou função.

    Args:
        tree: nó cujo corpo será limpo.

    Returns:
        O mesmo nó, com as docstrings removidas do corpo.
    """
    body = getattr(tree, "body", None)
    if not isinstance(body, list) or not body:
        return tree
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        tree.body = body[1:]
    # `pass` e uma docstring são equivalentes para o comportamento: normaliza os dois.
    tree.body = [node for node in tree.body if not isinstance(node, ast.Pass)]
    for child in ast.iter_child_nodes(tree):
        _strip_docstrings(child)
    return tree


def stripped_tree(source: str) -> str | None:
    """Árvore sintática sem docstrings, em forma textual comparável.

    Args:
        source: conteúdo do arquivo.

    Returns:
        A representação textual da árvore, ou `None` quando o código não compila.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    _strip_docstrings(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _head_source(path: str) -> str | None:
    """Conteúdo da versão do arquivo no commit HEAD.

    Args:
        path: caminho relativo ao repositório.

    Returns:
        O conteúdo anterior, ou `None` quando o arquivo é novo.
    """
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _changed_files() -> list[str]:
    """Arquivos Python alterados na árvore de trabalho.

    Returns:
        Lista de caminhos relativos.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    files: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path.endswith(".py") and (ROOT / path).is_file():
            files.append(path)
    return sorted(set(files))


def compare() -> list[str]:
    """Compara o código (sem docstrings) de cada arquivo alterado com a versão no HEAD.

    Returns:
        Lista de arquivos cujo código mudou.
    """
    drifted: list[str] = []
    for path in _changed_files():
        before = _head_source(path)
        if before is None:
            drifted.append(f"{path} (arquivo novo — revisar)")
            continue
        old = stripped_tree(before)
        new = stripped_tree((ROOT / path).read_text(encoding="utf-8"))
        if old is None or new is None:
            drifted.append(f"{path} (não compila)")
        elif old != new:
            drifted.append(path)
    return drifted


def main(argv: list[str]) -> int:
    """Executa a comparação e imprime o resultado.

    Args:
        argv: argumentos da linha de comando (não usados).

    Returns:
        0 quando nenhum arquivo alterou o código; 1 quando algum alterou.
    """
    drifted = compare()
    if not drifted:
        print("Nenhum arquivo alterado mudou de código (só comentários e docstrings).")
        return 0
    print("Arquivos com mudança de código:")
    for item in drifted:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
