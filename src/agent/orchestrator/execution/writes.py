"""
Arquivo: src/agent/orchestrator/execution/writes.py
Nome: writes.py
Propósito: transformar a resposta do modelo em uma escrita de arquivo e em um critério de verificação.
Responsabilidade: camada de aplicação — mapeamento payload→ferramenta, spec implícita e registro de recusa.
Componentes: write_tool_from_payload, implicit_spec, model_refusal_result, tool_refusal_result, WriteJournal.
Dependências: nenhuma (funções puras sobre dicionários).
Observações: a recusa de escrita vira **resultado** da etapa — repetir o mesmo pedido não muda a permissão.
"""

from __future__ import annotations

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


def implicit_spec(path: Any, written: str) -> dict[str, Any] | None:
    """Critério implícito de verificação de uma escrita (`file_contains` com o que foi gravado).

    Args:
        path: caminho do arquivo gravado.
        written: conteúdo gravado (ou o trecho substituído).

    Returns:
        O critério de verificação, ou `None` quando não há o que comprovar.
    """
    if not written or not written.strip() or not isinstance(path, str):
        return None
    return {
        "type": "file_contains",
        "path": path,
        "contains": written[:200],
        "implicit": True,
        "syntax": True,
    }


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

    Atributos:
        root: raiz do projeto (caminhos relativos são resolvidos a partir dela).
        originals: caminho absoluto → conteúdo antes da primeira escrita da etapa.
    """

    def __init__(self, root: str) -> None:
        """Começa vazio, para a raiz informada."""
        self.root = Path(root)
        self.originals: dict[Path, bytes] = {}

    def remember(self, tool: str, path: Any) -> None:
        """Guarda o conteúdo do arquivo antes da primeira escrita nele (só arquivo que já existe).

        Args:
            tool: ferramenta prestes a rodar; só `write_file` e `edit_file` contam.
            path: caminho alvo, relativo à raiz ou absoluto.
        """
        if tool not in _WRITE_TOOLS or not isinstance(path, str) or not path.strip():
            return
        full = Path(path) if Path(path).is_absolute() else self.root / path
        try:
            full = full.resolve()
        except OSError:
            return
        if full in self.originals or not full.is_file():
            return
        try:
            self.originals[full] = full.read_bytes()
        except OSError:
            return

    def restore(self) -> list[str]:
        """Devolve cada arquivo ao conteúdo original. Arquivos novos ficam (apagar é decisão do dono).

        Returns:
            Os caminhos restaurados.
        """
        restored = []
        for full, content in self.originals.items():
            try:
                if full.read_bytes() != content:
                    full.write_bytes(content)
                    restored.append(str(full))
            except OSError:
                continue
        return restored
