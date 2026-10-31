"""
Arquivo: src/agent/tools/edit_repair.py
Nome: edit_repair.py
Propósito: salvar edições de código Python que o modelo pequeno manda com a indentação errada, sem nunca aceitar um resultado inválido.
Responsabilidade: camada de infraestrutura — localização do trecho ignorando a indentação e reindentação do texto novo.
Componentes: python_ok, loose_span, reindent, repair_edit.
Dependências: ast, textwrap.
Observações: só vale para `.py` e só é usada quando a edição literal falha (trecho não encontrado ou sintaxe inválida); o resultado só é aceito se o arquivo inteiro continuar sintaticamente válido.

Por que existe
--------------
Visto com o `qwen3-vl:8b` em "termine a calculadora": `edit_file` com `new_string` sem a
indentação do método (`"self.entry1 = tk.Entry\\nself.entry1.bind(...)"`) — "unexpected indent"
duas vezes seguidas, e a etapa foi bloqueada. O trecho certo estava lá; faltavam os espaços.
"""
from __future__ import annotations

import ast
import textwrap


def python_ok(text: str) -> bool:
    """Diz se o texto é Python sintaticamente válido."""
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return True


def _indent_of(line: str) -> str:
    """Espaços do começo da linha."""
    return line[: len(line) - len(line.lstrip())]


def loose_span(content: str, old: str) -> tuple[int, int, str] | None:
    """Acha o trecho comparando linha a linha sem a indentação; só quando há uma única ocorrência.

    Args:
        content: arquivo inteiro.
        old: trecho pedido pelo modelo.

    Returns:
        `(início, fim, indentação da primeira linha)` em posições de caractere, cobrindo as linhas
        inteiras; `None` quando não acha ou acha mais de uma vez.
    """
    wanted = [line.strip() for line in old.strip("\n").split("\n")]
    if not wanted or not any(wanted):
        return None
    lines = content.split("\n")
    hits = []
    for i in range(len(lines) - len(wanted) + 1):
        if all(lines[i + k].strip() == wanted[k] for k in range(len(wanted))):
            hits.append(i)
    if len(hits) != 1:
        return None
    i = hits[0]
    start = sum(len(line) + 1 for line in lines[:i])
    end = start + sum(len(line) + 1 for line in lines[i : i + len(wanted)]) - 1
    return start, end, _indent_of(lines[i])


def reindent(new: str, base: str, *, first_line_too: bool) -> str:
    """Reindenta o texto novo a partir da indentação `base`, preservando a estrutura relativa.

    Args:
        new: texto novo do modelo.
        base: indentação do lugar onde ele entra.
        first_line_too: indenta também a primeira linha (troca de linhas inteiras).

    Returns:
        O texto com as linhas não vazias prefixadas por `base`.
    """
    lines = textwrap.dedent(new.strip("\n")).split("\n")
    out = []
    for index, line in enumerate(lines):
        if not line.strip():
            out.append("")
        elif index == 0 and not first_line_too:
            out.append(line)
        else:
            out.append(base + line)
    return "\n".join(out)


def repair_edit(content: str, old: str, new: str) -> str | None:
    """Tenta a edição com a indentação corrigida; devolve o arquivo novo só se ele for válido.

    Args:
        content: arquivo inteiro antes da edição.
        old: trecho a substituir, como o modelo mandou.
        new: texto novo, como o modelo mandou.

    Returns:
        O conteúdo editado e sintaticamente válido, ou `None` quando não há reparo seguro.
    """
    candidates: list[str] = []
    if old and content.count(old) == 1:
        at = content.index(old)
        line_start = content.rfind("\n", 0, at) + 1
        prefix = content[line_start:at]
        base = prefix if not prefix.strip() else _indent_of(prefix)
        candidates.append(content[:at] + reindent(new, base, first_line_too=bool(prefix.strip())) + content[at + len(old):])
    span = loose_span(content, old) if old else None
    if span is not None:
        start, end, base = span
        candidates.append(content[:start] + reindent(new, base, first_line_too=True) + content[end:])
    for candidate in candidates:
        if candidate != content and python_ok(candidate):
            return candidate
    return None
