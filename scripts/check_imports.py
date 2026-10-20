#!/usr/bin/env python3
"""
Arquivo: scripts/check_imports.py
Nome: check_imports.py
Propósito: conferir que uma alteração não removeu importações nem definições de símbolos do código anterior.
Responsabilidade: script de verificação — compara o inventário de símbolos entre o Git (HEAD) e a árvore de trabalho.
Componentes: main, symbols_of, compare.
Dependências: ast, subprocess, pathlib (somente biblioteca padrão).
Observações: usado depois de refatorações e movimentações de arquivo; sai com código 1 quando há perda de símbolo.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Símbolos que mudaram de módulo ou de nome **de propósito** nesta refatoração.
# O mapa existe para que o verificador continue sendo útil como barreira depois
# dela: qualquer símbolo fora daqui que suma é um erro de verdade.
MOVED: dict[str, str] = {
    "agent.api.main._present_task": "agent.api.presenters.present_task",
    "agent.api.main._present_conversation": "agent.api.presenters.present_conversation",
    "agent.api.main._usage_tokens": "agent.api.presenters.usage_tokens",
    "agent.api.main._remembered_model": "agent.api.presenters.remembered_model",
    "agent.api.main._thought_trace": "agent.api.live_view.thought_trace",
    "agent.api.main._mark_repeated_thought": "agent.api.live_view.mark_repeated_thought",
    "agent.api.main._how_for_task": "agent.api.live_view.how_for_task",
    "agent.api.main._provider_by_name": "agent.api.system_routes.provider_by_name",
    "agent.api.main._mcp_path": "agent.api.system_routes.mcp_path",
    "agent.orchestrator.runner._operation_tools_for": "agent.orchestrator.execution.guards.operation_tools_for",
    "agent.orchestrator.runner._write_refusal_reason": "agent.orchestrator.execution.guards.write_refusal_reason",
    "agent.orchestrator.runner._payload_is_usable": "agent.orchestrator.execution.guards.payload_is_usable",
    "agent.orchestrator.runner._is_informative_test_result": "agent.orchestrator.execution.tool_results.is_informative_test_result",
    "agent.orchestrator.runner._test_summary": "agent.orchestrator.execution.tool_results.test_summary",
    "agent.orchestrator.runner._compact_inspection": "agent.orchestrator.execution.guards.compact_inspection",
    "agent.orchestrator.runner.evidence_state": "agent.orchestrator.execution.guards.evidence_state",
    "agent.orchestrator.runner._default_provider_name": "agent.orchestrator.execution.providers.default_provider_name",
    "agent.orchestrator.runner._ENVIRONMENT": "agent.orchestrator.execution.executor.ENVIRONMENT_FAILURES",
    "agent.api.main.fastapi": "agent.api.*_routes",
    "agent.api.main.pydantic": "agent.api.*_routes",
    "agent.api.main.sqlalchemy": "agent.api.*_routes",
    "agent.api.main.uuid": "agent.api.*_routes",
    "tests.test_recovery_and_reporting.agent.orchestrator.runner._is_informative_test_result":
        "agent.orchestrator.execution.tool_results.is_informative_test_result",
    "tests.test_request_permissions.agent.orchestrator.runner._write_refusal_reason":
        "agent.orchestrator.execution.guards.write_refusal_reason",
}


def _imports(tree: ast.AST) -> set[str]:
    """Módulos importados por uma árvore sintática.

    Args:
        tree: árvore já parseada.

    Returns:
        Conjunto de nomes de módulo importados (`from x import y` conta como `x.y`).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


def _defined(tree: ast.AST) -> set[str]:
    """Nomes de nível superior definidos por uma árvore sintática.

    Args:
        tree: árvore já parseada.

    Returns:
        Conjunto com classes, funções e constantes de nível superior.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def symbols_of(source: str) -> tuple[set[str], set[str]] | None:
    """Importações e definições de um código Python.

    Args:
        source: conteúdo do arquivo.

    Returns:
        Tupla (imports, definições), ou `None` quando o código não compila.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return _imports(tree), _defined(tree)


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
    """Arquivos Python alterados na árvore de trabalho (versionados ou novos).

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


def _defined_everywhere() -> set[str]:
    """Nomes definidos em qualquer módulo Python do repositório.

    Returns:
        Conjunto dos nomes de nível superior definidos no projeto.
    """
    names: set[str] = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names |= _defined(tree)
        names |= {item.rsplit(".", 1)[-1] for item in _imports(tree)}
    return names


def compare() -> list[str]:
    """Compara cada arquivo Python alterado com a versão no HEAD.

    Um símbolo que sumiu do arquivo mas existe em outro módulo é **movido**, não
    perdido: o relatório separa os dois casos.

    Returns:
        Lista de problemas encontrados (símbolo removido, por arquivo).
    """
    problems: list[str] = []
    movidos_por_arquivo: list[str] = []
    existentes = _defined_everywhere()
    for path in _changed_files():
        current = (ROOT / path).read_text(encoding="utf-8")
        before = _head_source(path)
        if before is None:
            continue
        old = symbols_of(before)
        new = symbols_of(current)
        if old is None or new is None:
            problems.append(f"{path}: não compila (sintaxe inválida)")
            continue
        lost_imports = old[0] - new[0]
        lost_defs = old[1] - new[1]
        # Um import removido cujo símbolo continua definido em outro módulo é uma
        # movimentação — não uma perda. Só é perda quando o símbolo sumiu do projeto.
        modulo = path[:-3].replace("/", ".")
        if modulo.startswith("src."):
            modulo = modulo[4:]
        perdidos_import = {
            item
            for item in lost_imports
            if item.rsplit(".", 1)[-1] not in existentes and f"{modulo}.{item}" not in MOVED
        }
        perdidos_def = {item for item in lost_defs if item not in existentes and f"{modulo}.{item}" not in MOVED}
        movidos = len(lost_imports) - len(perdidos_import) + len(lost_defs) - len(perdidos_def)
        if perdidos_import:
            problems.append(f"{path}: importações removidas: {', '.join(sorted(perdidos_import))}")
        if perdidos_def:
            problems.append(f"{path}: definições removidas: {', '.join(sorted(perdidos_def))}")
        if movidos:
            movidos_por_arquivo.append(f"{path}: {movidos} símbolo(s) movido(s) para outro módulo")
    return problems, movidos_por_arquivo


def main(argv: list[str]) -> int:
    """Executa a comparação e imprime o resultado.

    Args:
        argv: argumentos da linha de comando (não usados).

    Returns:
        0 quando nada foi perdido; 1 quando há perdas a revisar.
    """
    problems, movidos = compare()
    for item in movidos:
        print(f"movido: {item}")
    if not problems:
        print("Imports e definições preservados nos arquivos alterados.")
        return 0
    print("Perdas detectadas (revisar):")
    for item in problems:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
