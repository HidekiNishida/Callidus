#!/usr/bin/env python3
"""
Arquivo: scripts/check_docs.py
Nome: check_docs.py
Propósito: conferir que os links internos da documentação existem no repositório.
Responsabilidade: script de verificação — varre os arquivos Markdown e valida os links relativos e absolutos.
Componentes: main, links_of, resolve.
Dependências: re, pathlib (somente biblioteca padrão).
Observações: links para a web (http/https) e âncoras internas são ignorados; sai com código 1 quando há link quebrado.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import unquote
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _targets(paths: list[Path]) -> list[Path]:
    """Arquivos Markdown a verificar.

    Args:
        paths: pastas ou arquivos informados na linha de comando.

    Returns:
        Lista de arquivos Markdown existentes.
    """
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / raw
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            files.append(path)
    return [f for f in files if "__pycache__" not in f.parts]


def _resolve(source: Path, target: str) -> Path | None:
    """Resolve o destino de um link a partir do arquivo que o contém.

    Args:
        source: arquivo Markdown com o link.
        target: destino escrito no link.

    Returns:
        O caminho absoluto do destino, ou `None` quando o link é externo/âncora.
    """
    if target.startswith(("http://", "https://", "mailto:", "#")) or "<" in target:
        return None
    clean = unquote(target.split("#", 1)[0])
    if not clean:
        return None
    if clean.startswith("/"):
        return ROOT / clean.lstrip("/")
    return (source.parent / clean).resolve()


def main(argv: list[str]) -> int:
    """Verifica os links da documentação.

    Args:
        argv: pastas ou arquivos Markdown a verificar (padrão: README e docs).

    Returns:
        0 quando nenhum link está quebrado; 1 quando há links quebrados.
    """
    paths = argv[1:] or ["README.md", "docs", "src", "internal", "tests", "web", "scripts", "AGENTS.md"]
    broken: list[str] = []
    for file in _targets(paths):
        text = file.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            resolved = _resolve(file, match.group(1))
            if resolved is None:
                continue
            if not resolved.exists():
                broken.append(f"{file.relative_to(ROOT)}: {match.group(1)}")
    if not broken:
        print("Links internos da documentação conferidos: nenhum quebrado.")
        return 0
    print("Links quebrados:")
    for item in broken:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
