#!/usr/bin/env python3
"""
Arquivo: scripts/check_markdown.py
Nome: check_markdown.py
Propósito: conferir a integridade estrutural dos documentos Markdown do repositório.
Responsabilidade: script de verificação — título, hierarquia de cabeçalhos, blocos de código, tabelas e diagramas.
Componentes: main, analyse, relatorio.
Dependências: re, pathlib (somente biblioteca padrão).
Observações: as regras são de estrutura, não de estilo — um documento pequeno e correto passa; nenhum conteúdo é cobrado.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s*(```+|~~~+)\s*(\S*)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
PIPE = re.compile(r"(?<!\\)\|")
MERMAID_TYPES = (
    "flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram",
    "erDiagram", "journey", "gantt", "pie", "mindmap", "timeline", "C4Context",
)


def _targets(paths: list[str]) -> list[Path]:
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
    ignored = {".venv", ".git", "node_modules", ".pytest_cache"}
    return [f for f in files if not (ignored & set(f.parts))]


def _headings(lines: list[str]) -> list[tuple[int, str, int]]:
    """Cabeçalhos do documento, na ordem em que aparecem.

    Args:
        lines: linhas do arquivo.

    Returns:
        Lista de tuplas (nível, texto, número da linha).
    """
    found: list[tuple[int, str, int]] = []
    inside = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        match = HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2).strip(), number))
    return found


def _duplicate_siblings(headings: list[tuple[int, str, int]]) -> list[tuple[str, int, int]]:
    """Títulos de seção repetidos entre irmãos.

    Args:
        headings: cabeçalhos do documento.

    Returns:
        Lista de tuplas (texto, linha atual, linha da primeira ocorrência).
    """
    stack: list[tuple[int, str]] = []
    seen: dict[tuple[tuple[str, ...], str], int] = {}
    duplicates: list[tuple[str, int, int]] = []
    for level, text, number in headings:
        while stack and stack[-1][0] >= level:
            stack.pop()
        key = (tuple(item[1] for item in stack), text.strip().lower())
        if key in seen:
            duplicates.append((text, number, seen[key]))
        else:
            seen[key] = number
        stack.append((level, text))
    return duplicates


def _mermaid_problems(rel: str, lines: list[str]) -> list[str]:
    """Problemas nos diagramas Mermaid do documento.

    Args:
        rel: caminho do arquivo, para as mensagens.
        lines: linhas do arquivo.

    Returns:
        Lista de problemas encontrados.
    """
    problems: list[str] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip().startswith("```mermaid"):
            continue
        block: list[str] = []
        for follow in lines[number:]:
            if follow.strip().startswith("```"):
                break
            block.append(follow)
        first = next((item.strip() for item in block if item.strip()), "")
        if not first.startswith(MERMAID_TYPES):
            problems.append(f"{rel}:{number}: diagrama Mermaid com tipo desconhecido ({first[:30]})")
        if first.count("[") != first.count("]") or first.count("(") != first.count(")"):
            problems.append(f"{rel}:{number}: diagrama Mermaid com colchetes ou parênteses desbalanceados")
    return problems


def analyse(path: Path) -> list[str]:
    """Analisa um documento Markdown e devolve os problemas encontrados.

    Args:
        path: arquivo a analisar.

    Returns:
        Lista de problemas (vazia quando o documento está íntegro).
    """
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.relative_to(ROOT).as_posix()

    fence: str | None = None
    fence_line = 0
    fence_lang = ""
    blanks = 0
    in_table = False
    table_cols = 0

    for number, line in enumerate(lines, start=1):
        match = FENCE.match(line)
        if match:
            marker, lang = match.group(1), match.group(2)
            if fence is None:
                fence, fence_line, fence_lang = marker, number, lang
                in_table = False
            elif line.strip().startswith(fence):
                if not fence_lang:
                    problems.append(f"{rel}:{fence_line}: bloco de código sem linguagem")
                fence, fence_lang = None, ""
            blanks = 0
            continue
        if fence is not None:
            continue

        if HEADING.match(line):
            in_table = False
            blanks = 0
            continue

        if TABLE_ROW.match(line):
            cols = len(PIPE.findall(line)) - 1
            if not in_table:
                in_table, table_cols = True, cols
            elif cols != table_cols:
                problems.append(f"{rel}:{number}: tabela com {cols} colunas, o cabeçalho tem {table_cols}")
            blanks = 0
            continue
        in_table = False

        if not line.strip():
            blanks += 1
            if blanks == 3:
                problems.append(f"{rel}:{number}: três linhas em branco seguidas")
        else:
            blanks = 0
        if line.rstrip() != line:
            problems.append(f"{rel}:{number}: espaço no fim da linha")

    if fence is not None:
        problems.append(f"{rel}:{fence_line}: bloco de código nunca fechado")

    headings = _headings(lines)
    frontmatter = bool(lines) and lines[0].strip() == "---"
    if not headings:
        problems.append(f"{rel}: sem título (H1)")
    elif not frontmatter and headings[0][0] != 1:
        problems.append(f"{rel}:{headings[0][2]}: o primeiro título é H{headings[0][0]}, não H1")

    previous = headings[0][0] if headings else 0
    for level, text, number in headings[1:]:
        if level > previous + 1:
            problems.append(f"{rel}:{number}: salto de H{previous} para H{level} em «{text}»")
        previous = level

    for text, number, first in _duplicate_siblings(headings):
        problems.append(f"{rel}:{number}: título de seção repetido «{text}» (já em {first})")

    problems.extend(_mermaid_problems(rel, lines))
    return problems


def main(argv: list[str]) -> int:
    """Analisa os documentos indicados e imprime o resultado.

    Args:
        argv: pastas ou arquivos Markdown (padrão: README, AGENTS.md, docs, src, internal, web, tests, scripts, skills).

    Returns:
        0 quando nenhum problema foi encontrado; 1 quando há problemas.
    """
    paths = argv[1:] or ["README.md", "AGENTS.md", "docs", "src", "internal", "web", "tests", "scripts", "skills"]
    problems: list[str] = []
    for file in _targets(paths):
        problems.extend(analyse(file))
    if not problems:
        print("Documentos Markdown conferidos: nenhum problema estrutural.")
        return 0
    print(f"Problemas estruturais ({len(problems)}):")
    for item in problems:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
