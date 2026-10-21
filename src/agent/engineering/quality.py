"""
Arquivo: src/agent/engineering/quality.py
Nome: quality.py
Propósito: executar verificações de qualidade (lint, teste, build) e resumir o resultado.
Responsabilidade: camada de infraestrutura — execução de comandos de projeto e leitura do resultado.
Componentes: run_check, summarize_test_output, parse_pytest_summary, parse_generic_errors.
Dependências: subprocess, re.
Observações: o resumo distingue sucesso confirmado de falha e de resultado inconclusivo.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Padrão da linha de resumo do pytest.
_PYTEST_SUMMARY = re.compile(
    r"(?:(\d+) failed)?(?:,\s*)?(?:(\d+) passed)?(?:,\s*)?(?:(\d+) skipped)?(?:,\s*)?(?:(\d+) error)?",
    re.IGNORECASE,
)

#: Padrões genéricos de erro em saída de compilação ou teste.
_ERROR_PATTERNS = (
    re.compile(r"^error(?:\[[A-Z0-9]+\])?:", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^FAILED\s+(\S+)", re.MULTILINE),
    re.compile(r"^\s*(\d+)\s+(?:errors?|failures?)\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(\w+Error|Exception)\b", re.MULTILINE),
)


def parse_pytest_summary(output: str) -> dict[str, Any]:
    """Lê o resumo do pytest na saída do comando.

    Args:
        output: saída do pytest.

    Returns:
        Um dicionário com as contagens e a linha de resumo, quando encontrada.
    """
    text = output or ""
    line = ""
    for candidate in reversed(text.splitlines()):
        if "passed" in candidate or "failed" in candidate or "error" in candidate:
            line = candidate.strip()
            break
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    match = _PYTEST_SUMMARY.search(line)
    if match:
        failed, passed, skipped, errors = match.groups()
        counts = {
            "passed": int(passed or 0),
            "failed": int(failed or 0),
            "skipped": int(skipped or 0),
            "errors": int(errors or 0),
        }
    return {"counts": counts, "summary": line, "found": bool(line)}


def parse_generic_errors(output: str) -> dict[str, Any]:
    """Conta sinais de erro em uma saída de compilação ou teste.

    Args:
        output: saída do comando.

    Returns:
        Um dicionário com a quantidade de erros e as linhas que os indiciam.
    """
    text = output or ""
    hits: list[str] = []
    for pattern in _ERROR_PATTERNS:
        for match in pattern.finditer(text):
            line = text[match.start() : text.find("\n", match.start()) if "\n" in text[match.start() :] else None]
            snippet = (line or match.group(0)).strip()
            if snippet and snippet not in hits:
                hits.append(snippet[:200])
    return {"errors": len(hits), "lines": hits[:20]}


def summarize_test_output(output: str, exit_code: int) -> dict[str, Any]:
    """Resume o resultado de uma execução de testes.

    Args:
        output: saída combinada do comando.
        exit_code: código de saída do comando.

    Returns:
        Um dicionário com `status` (`passed`, `failed` ou `inconclusive`), as contagens e
        as linhas de erro relevantes.
    """
    pytest_summary = parse_pytest_summary(output)
    generic = parse_generic_errors(output)
    if exit_code == 0:
        status = "passed"
    elif generic["errors"] or pytest_summary["counts"]["failed"]:
        status = "failed"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "exit_code": exit_code,
        "counts": pytest_summary["counts"],
        "summary": pytest_summary["summary"],
        "errors": generic["errors"],
        "error_lines": generic["lines"],
        "inconclusive": status == "inconclusive",
    }


def run_check(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 300.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Executa um comando de qualidade e devolve o resultado interpretado.

    Args:
        command: comando e argumentos, sem shell.
        cwd: diretório de trabalho.
        timeout: tempo limite da execução, em segundos.
        env: variáveis de ambiente adicionais.

    Returns:
        Um dicionário com o código de saída, a saída (limitada) e o resumo do resultado.
    """
    argv = [str(item) for item in command]
    if not argv:
        return {"success": False, "error": "comando vazio"}
    import os

    environment = {**os.environ, **(env or {})}
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"executável não encontrado: {argv[0]}",
            "command": argv,
            "missing_tool": argv[0],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"tempo limite excedido ({timeout:.0f}s)",
            "command": argv,
            "timeout": True,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"falha ao executar: {exc}", "command": argv}
    output = (completed.stdout or "") + (completed.stderr or "")
    summary = summarize_test_output(output, completed.returncode)
    return {
        "success": completed.returncode == 0,
        "command": argv,
        "exit_code": completed.returncode,
        "output": output[:20000],
        "truncated": len(output) > 20000,
        **summary,
    }
