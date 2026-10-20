"""
Arquivo: src/agent/verification/runner.py
Nome: runner.py
Propósito: executar as verificações determinísticas do contrato de uma tarefa.
Responsabilidade: camada de aplicação — execução dos verificadores e emissão dos eventos correspondentes.
Componentes: run_verification, VerificationResult, VERIFIER_TYPES, syntax_problem.
Dependências: agent.observability, agent.security.paths, agent.tools.registry.
Observações: o contrato de verificadores é fechado; um verificador inexistente falha na execução, não depois.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.observability import emit
from agent.security.paths import PathSecurityError, resolve_under_root
from agent.tools.registry import ToolContext, build_default_registry

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
_DELIVERABLE = {".html", ".htm", ".css", ".js", ".md", ".tsx", ".jsx", ".vue", ".svg"}

# Tipos de verificação aceitos. O contrato é fechado de propósito: um verificador que não existe
# só falha na hora de executar, depois de o modelo já ter escrito o trabalho.
VERIFIER_TYPES = frozenset(
    {
        "stages",
        "pytest",
        "script",
        "run_script",
        "command",
        "run_command",
        "file_contains",
        "file_exists",
        "syntax",
        "static_analysis",
        "ast_check",
        "acceptance_manual",
    }
)


@dataclass
class VerificationResult:
    """Veredito de uma verificação.

    Atributos:
        verifier: tipo do verificador executado.
        passed: `True` aprovado, `False` reprovado, `None` inconclusivo.
        summary: resumo textual do resultado.
        detail: detalhe estruturado da execução (saída, erros, exit code).
    """

    verifier: str
    passed: bool | None
    summary: str
    detail: dict[str, Any] | None = None


async def run_verification(
    *,
    project_root: str,
    spec: dict[str, Any],
    tool_args: dict[str, Any] | None = None,
    approved: bool = False,
) -> VerificationResult:
    """Executa a verificação pedida e emite os eventos de início e de desfecho.

    Args:
        project_root: raiz do projeto avaliado.
        spec: especificação da verificação (tipo, caminho, critério).
        tool_args: argumentos da ferramenta usados na verificação.
        approved: quando `True`, as ferramentas que pedem aprovação são executadas mesmo assim.

    Returns:
        O veredito da verificação, com resumo e detalhe.
    """
    vtype = str(spec.get("type") or spec.get("verification") or "unknown")
    criterion = {k: spec[k] for k in ("path", "contains", "command") if k in spec}
    emit("verification.started", {"verifier": vtype, "criterion": criterion}, commit=True)
    result = await _verify(project_root=project_root, spec=spec, tool_args=tool_args, approved=approved)
    outcome = {
        "verifier": result.verifier,
        "summary": result.summary,
        "criterion": criterion,
        "exit_code": (result.detail or {}).get("exit_code"),
    }
    if result.passed is None:
        emit("verification.inconclusive", outcome)
    else:
        emit("verification.passed" if result.passed else "verification.failed", outcome)
    return result


async def _verify(
    *,
    project_root: str,
    spec: dict[str, Any],
    tool_args: dict[str, Any] | None,
    approved: bool,
) -> VerificationResult:
    """Executa o verificador correspondente ao tipo pedido.

    Args:
        project_root: raiz do projeto avaliado.
        spec: especificação da verificação.
        tool_args: argumentos da ferramenta usados na verificação.
        approved: quando `True`, as ferramentas que pedem aprovação são executadas mesmo assim.

    Returns:
        O veredito da verificação.

    Observações:
        `stages` e `acceptance_manual` são inconclusivos: dependem de um estado que só o orquestrador tem.
    """
    vtype = spec.get("type") or spec.get("verification")
    ctx = ToolContext(project_root=project_root)
    tools = build_default_registry()

    if vtype == "stages":
        # A conferência real acontece no orquestrador, que tem o estado persistido das etapas.
        # Aqui não há o que aprovar: devolver "aprovado" seria um verde falso.
        return VerificationResult(
            "stages",
            None,
            "conferência de etapas precisa do estado das tarefas dependentes",
            {"type": "stages"},
        )

    if vtype == "pytest":
        path = spec.get("path", ".")
        out = await tools.execute("run_pytest", ctx, {"path": path}, approved=approved)
        if out.get("success"):
            return VerificationResult("pytest", True, "pytest ok", out)
        if _no_tests_collected(out) and _has_non_python_deliverable(project_root):
            return VerificationResult(
                "pytest",
                True,
                "não há testes Python; a entrega do projeto está presente",
                out,
            )
        return VerificationResult("pytest", False, "pytest falhou", out)

    if vtype in {"script", "run_script"}:
        path = spec.get("path") or (tool_args.get("path") if tool_args else "")
        out = await tools.execute("run_script", ctx, {"path": path}, approved=approved)
        passed = bool(out.get("success"))
        return VerificationResult(
            "script",
            passed,
            "script ok" if passed else "script falhou",
            out,
        )

    if vtype in {"command", "run_command"}:
        out = await tools.execute(
            "run_command",
            ctx,
            {"command": spec.get("command"), "cwd": spec.get("cwd"), "timeout": spec.get("timeout", 120)},
            approved=approved,
        )
        passed = bool(out.get("success"))
        return VerificationResult(
            "command",
            passed,
            "comando ok" if passed else "comando falhou",
            out,
        )

    if vtype == "file_contains":
        path = spec.get("path", "")
        needle = spec.get("contains", "")
        read = _read_whole(project_root, path)
        if not read.get("success"):
            return VerificationResult("file_contains", False, read.get("error", "leitura falhou"), read)
        content = read["content"]
        ok = needle in content
        if ok and spec.get("syntax"):
            problem = syntax_problem(path, content)
            if problem:
                return VerificationResult("file_contains", False, f"sintaxe inválida em {path}: {problem}", {"needle": needle, "syntax_error": problem})
        return VerificationResult(
            "file_contains",
            ok,
            f"trecho {'encontrado' if ok else 'ausente'} em {path}",
            {"needle": needle},
        )

    if vtype == "syntax":
        path = spec.get("path", "")
        read = _read_whole(project_root, path)
        if not read.get("success"):
            return VerificationResult("syntax", False, read.get("error", "leitura falhou"), read)
        problem = syntax_problem(path, read["content"])
        return VerificationResult(
            "syntax",
            problem is None,
            f"sintaxe válida em {path}" if problem is None else f"sintaxe inválida em {path}: {problem}",
            {"syntax_error": problem} if problem else {},
        )

    if vtype == "file_exists":
        path = spec.get("path", "")
        min_bytes = int(spec.get("min_bytes", 1))
        read = _read_whole(project_root, path)
        if not read.get("success"):
            return VerificationResult("file_exists", False, f"arquivo {path} não existe: {read.get('error')}", read)
        size = len(read["content"].encode("utf-8"))
        ok = size >= min_bytes
        return VerificationResult(
            "file_exists",
            ok,
            f"arquivo {path} existe ({size} bytes)" if ok else f"arquivo {path} tem apenas {size} bytes (< {min_bytes})",
            {"path": path, "size": size, "min_bytes": min_bytes},
        )

    if vtype in {"static_analysis", "ast_check"}:
        path = spec.get("path", ".")
        try:
            full_path = resolve_under_root(project_root, path) if path != "." else Path(project_root)
        except Exception as exc:
            return VerificationResult("static_analysis", False, str(exc), {"error": str(exc)})
        files = [full_path] if full_path.is_file() else list(full_path.rglob("*.py"))
        problems = {}
        for f in files:
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            prob = syntax_problem(str(f), f.read_text(encoding="utf-8", errors="replace"))
            if prob:
                problems[str(f.relative_to(project_root))] = prob
        ok = len(problems) == 0
        return VerificationResult(
            "static_analysis",
            ok,
            "análise estática sem erros sintáticos" if ok else f"erros sintáticos em {len(problems)} arquivos",
            {"problems": problems, "files_checked": len(files)},
        )

    if vtype == "acceptance_manual":
        return VerificationResult(
            "acceptance_manual",
            None,
            "verificação manual pendente",
            spec,
        )

    return VerificationResult("unknown", False, f"verificador desconhecido: {vtype}", spec)


def _read_whole(project_root: str, path: str) -> dict[str, Any]:
    """Arquivo inteiro, como gravado: `read_file` pagina e corta a quebra final, o que faria um trecho
    gravado falhar na conferência."""
    try:
        full = resolve_under_root(project_root, path)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    if not full.is_file():
        return {"success": False, "error": "arquivo não encontrado", "path": path}
    return {"success": True, "content": full.read_text(encoding="utf-8", errors="replace")}


def syntax_problem(path: str, content: str) -> str | None:
    """Análise sintática determinística pela extensão (Python e JSON); `None` se válido ou sem analisador."""
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(content, filename=path)
        elif suffix == ".json":
            json.loads(content)
    except SyntaxError as exc:
        return f"linha {exc.lineno}: {exc.msg}"
    except ValueError as exc:
        return str(exc)
    return None


def _no_tests_collected(out: dict[str, Any]) -> bool:
    """Indica que o pytest rodou mas não coletou teste algum.

    Args:
        out: saída da execução do pytest.

    Returns:
        `True` quando nenhum teste foi coletado.
    """
    if out.get("exit_code") == 5:
        return True
    text = f"{out.get('stdout') or ''}\n{out.get('stderr') or ''}".lower()
    return "no tests ran" in text or "collected 0 items" in text


def _has_non_python_deliverable(root: str) -> bool:
    """Indica se o projeto tem entregável fora do código Python.

    Args:
        root: raiz do projeto.

    Returns:
        `True` quando existe ao menos um arquivo de entrega (HTML, CSS, Markdown, etc.).
    """
    base = Path(root)
    if not base.is_dir():
        return False
    for path in base.rglob("*"):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _DELIVERABLE:
            return True
    return False
