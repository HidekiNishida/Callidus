"""
Arquivo: src/agent/tools/diffing.py
Nome: diffing.py
Propósito: produzir o diff unificado curto que acompanha uma alteração na conversa e montar o texto de um acréscimo ao fim do arquivo.
Responsabilidade: camada de apresentação — comparação entre o conteúdo antes e depois da escrita.
Componentes: unified_diff_text, append_block.
Dependências: difflib.
Observações: o diff é truncado no limite informado, com a marca de truncamento no resultado.
"""
from __future__ import annotations

import difflib


def unified_diff_text(path: str, before: str, after: str, *, limit: int = 4000) -> dict:
    """Monta o diff unificado entre dois conteúdos do mesmo arquivo.

    Args:
        path: caminho usado nos cabeçalhos do diff.
        before: conteúdo anterior.
        after: conteúdo novo.
        limit: tamanho máximo do diff em caracteres.

    Returns:
        Um dicionário com o diff, a quantidade de linhas adicionadas e removidas e a marca de truncamento.
    """
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    truncated = len(diff) > limit
    if truncated:
        diff = diff[:limit].rstrip() + "\n…"
    return {"diff": diff, "added": added, "removed": removed, "truncated": truncated}


def append_block(before: str, addition: str) -> str:
    """Acrescenta um bloco ao fim de um conteúdo, separado por quebra de linha.

    É o que `edit_file` faz com `old_string` vazio: modelos pequenos pedem "trecho antigo vazio"
    para escrever num arquivo quase vazio. Acrescentar preserva o que existia (nada se perde),
    em vez de falhar e repetir a mesma chamada.

    Args:
        before: conteúdo atual do arquivo.
        addition: bloco a acrescentar.

    Returns:
        O conteúdo novo, terminado em quebra de linha.
    """
    head = before if not before or before.endswith("\n") else before + "\n"
    tail = addition if addition.endswith("\n") else addition + "\n"
    return head + tail
