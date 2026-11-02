"""
Arquivo: src/agent/orchestrator/execution/writes.py
Nome: writes.py
Propósito: transformar a resposta do modelo em uma escrita de arquivo e em um critério de verificação.
Responsabilidade: camada de aplicação — mapeamento payload→ferramenta, spec implícita e registro de recusa.
Componentes: write_tool_from_payload, implicit_spec, model_refusal_result, tool_refusal_result, WriteJournal.
Dependências: hashlib, pathlib (funções puras sobre dicionários e o diário de escritas).
Observações: a recusa de escrita vira **resultado** da etapa — repetir o mesmo pedido não muda a permissão.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

# Ferramentas que mudam o conteúdo de um arquivo existente (o diário guarda o original antes).
_WRITE_TOOLS = {"write_file", "edit_file"}


def write_tool_from_payload(data: dict) -> tuple[str, dict[str, Any]]:
    """Traduz o JSON do modelo na ferramenta de escrita correspondente.

    Args:
        data: objeto JSON devolvido pelo modelo, com `path` e o conteúdo.

    Returns:
        Tupla `(tool_id, argumentos)` — `edit_file` quando há trecho a substituir,
        `write_file` quando o modelo devolve o conteúdo inteiro.
    """
    old = data.get("old_string", data.get("old"))
    new = data["new_string"] if "new_string" in data else data.get("new")
    if isinstance(old, str) and isinstance(new, str):
        return "edit_file", {"path": data["path"], "old_string": old, "new_string": new}
    return "write_file", {"path": data["path"], "content": data.get("content", "")}


#: A partir de quantas linhas um arquivo existente passa a ter o volume protegido.
PRESERVE_MIN_LINES = 20


def implicit_spec(path: Any, written: str, *, lines_before: int | None = None) -> dict[str, Any] | None:
    """Critério implícito de verificação de uma escrita (`file_contains` com o que foi gravado).

    Args:
        path: caminho do arquivo gravado.
        written: conteúdo gravado (ou o trecho substituído).
        lines_before: linhas do arquivo antes da etapa, quando ele já existia. A partir de
            `PRESERVE_MIN_LINES`, o critério exige que a escrita não apague a maior parte dele.

    Returns:
        O critério de verificação, ou `None` quando não há o que comprovar.
    """
    if not written or not written.strip() or not isinstance(path, str):
        return None
    spec: dict[str, Any] = {
        "type": "file_contains",
        "path": path,
        "contains": written[:200],
        "implicit": True,
        "syntax": True,
    }
    if lines_before and lines_before >= PRESERVE_MIN_LINES:
        spec["preserve_lines"] = lines_before
    return spec


def model_refusal_result(
    tool_name: str,
    path: Any,
    reason: str,
    *,
    report: str,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Resultado consolidado de uma escrita recusada vinda do modelo.

    Args:
        tool_name: ferramenta que o modelo tentou usar.
        path: caminho alvo.
        reason: motivo da recusa.
        report: texto produced pelo modelo (o que ele tentou entregar).
        snapshot_id: identificador do snapshot de contexto, quando houver.

    Returns:
        O dicionário a gravar em `consolidated_result_json` da etapa.
    """
    result: dict[str, Any] = {
        "model_operation": True,
        "refused_write": {"tool": tool_name, "path": path, "reason": reason},
        "report": report,
    }
    if snapshot_id is not None:
        result["context_snapshot_id"] = snapshot_id
    return result


def tool_refusal_result(tool_id: str, path: Any, reason: str) -> dict[str, Any]:
    """Resultado consolidado de uma escrita recusada vinda do plano da etapa.

    Args:
        tool_id: ferramenta que o plano pedia.
        path: caminho alvo.
        reason: motivo da recusa.

    Returns:
        O dicionário a gravar em `consolidated_result_json` da etapa.
    """
    return {
        "tool": tool_id,
        "result": {"success": False, "error": reason, "refused": True},
        "refused_write": {"tool": tool_id, "path": path, "reason": reason},
    }


class WriteJournal:
    """Diário das escritas de uma etapa: o conteúdo original de cada arquivo, para desfazer.

    Visto com o `qwen3-vl:8b` em "termine a calculadora": a escrita que a verificação reprovou
    ficava no disco — a calculadora que funcionava ficava quebrada, e a próxima tentativa partia
    do arquivo quebrado. Com o diário, uma escrita reprovada é desfeita: o projeto nunca fica pior
    do que estava antes da etapa.

    O rollback só devolve o que **pertence à tentativa**: depois de cada escrita, o diário anota o
    hash do que a etapa gravou (`settle`). Se, na hora de desfazer, o arquivo já não tem esse
    conteúdo, outra mão o alterou (a pessoa no editor, outra ferramenta) — sobrescrever apagaria
    esse trabalho, então o arquivo fica como está e entra em `conflicts`.

    Atributos:
        root: raiz do projeto (caminhos relativos são resolvidos a partir dela).
        originals: caminho absoluto → conteúdo antes da primeira escrita da etapa.
        written: caminho absoluto → SHA-256 do conteúdo que a etapa deixou depois da última escrita.
        created: arquivos que não existiam antes da etapa (nunca são apagados no rollback).
        conflicts: arquivos que o rollback deixou intocados porque mudaram depois da escrita da etapa.
    """

    def __init__(self, root: str) -> None:
        """Começa vazio, para a raiz informada."""
        self.root = Path(root)
        self.originals: dict[Path, bytes] = {}
        self.written: dict[Path, str] = {}
        self.created: set[Path] = set()
        self.conflicts: list[str] = []

    def _resolve(self, path: Any) -> Path | None:
        """Caminho absoluto resolvido, ou `None` quando o caminho é inválido."""
        if not isinstance(path, str) or not path.strip():
            return None
        full = Path(path) if Path(path).is_absolute() else self.root / path
        try:
            return full.resolve()
        except OSError:
            return None

    def remember(self, tool: str, path: Any) -> None:
        """Guarda o conteúdo do arquivo antes da primeira escrita nele.

        Args:
            tool: ferramenta prestes a rodar; só `write_file` e `edit_file` contam.
            path: caminho alvo, relativo à raiz ou absoluto.
        """
        if tool not in _WRITE_TOOLS:
            return
        full = self._resolve(path)
        if full is None or full in self.originals or full in self.created:
            return
        if not full.is_file():
            self.created.add(full)
            return
        try:
            self.originals[full] = full.read_bytes()
        except OSError:
            return

    def settle(self, tool: str, path: Any) -> None:
        """Anota o que a etapa acabou de gravar (chamado depois de uma escrita bem-sucedida).

        Args:
            tool: ferramenta que acabou de rodar.
            path: caminho escrito.
        """
        if tool not in _WRITE_TOOLS:
            return
        full = self._resolve(path)
        if full is None or not full.is_file():
            return
        try:
            self.written[full] = hashlib.sha256(full.read_bytes()).hexdigest()
        except OSError:
            return

    def lines_before(self, path: Any) -> int | None:
        """Linhas do arquivo antes da primeira escrita da etapa (`None` se era novo ou desconhecido).

        Args:
            path: caminho escrito.

        Returns:
            O número de linhas do original.
        """
        full = self._resolve(path)
        original = self.originals.get(full) if full is not None else None
        if original is None:
            return None
        return original.decode("utf-8", errors="replace").count("\n") + 1

    def restore(self) -> list[str]:
        """Devolve cada arquivo ao conteúdo original, só quando o disco ainda tem o que a etapa gravou.

        Arquivos novos ficam (apagar é decisão do dono). Arquivo alterado por terceiros depois da
        escrita da etapa também fica, e entra em `conflicts`.

        Returns:
            Os caminhos restaurados.
        """
        restored = []
        for full, content in self.originals.items():
            try:
                current = full.read_bytes()
                if current == content:
                    continue
                expected = self.written.get(full)
                if expected is not None and hashlib.sha256(current).hexdigest() != expected:
                    self.conflicts.append(str(full))
                    continue
                full.write_bytes(content)
                restored.append(str(full))
            except OSError:
                continue
        return restored
