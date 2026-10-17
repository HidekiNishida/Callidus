# src/agent/verification/runner.py — verificações determinísticas
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.tools.registry import ToolContext, build_default_registry

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
_DELIVERABLE = {".html", ".htm", ".css", ".js", ".md", ".tsx", ".jsx", ".vue", ".svg"}


@dataclass
class VerificationResult:
    verifier: str
    passed: bool | None
    summary: str
    detail: dict[str, Any] | None = None


async def run_verification(
    *,
    project_root: str,
    spec: dict[str, Any],
    approved: bool = False,
) -> VerificationResult:
    vtype = spec.get("type") or spec.get("verification")
    ctx = ToolContext(project_root=project_root)
    tools = build_default_registry()

    if vtype == "stages":
        return VerificationResult(
            "stages",
            True,
            "etapas anteriores concluídas",
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
        out = await tools.execute("run_script", ctx, {"path": spec.get("path", "")}, approved=approved)
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
        read = await tools.execute("read_file", ctx, {"path": path})
        if not read.get("success"):
            return VerificationResult("file_contains", False, read.get("error", "leitura falhou"), read)
        ok = needle in read.get("content", "")
        return VerificationResult(
            "file_contains",
            ok,
            f"trecho {'encontrado' if ok else 'ausente'} em {path}",
            {"needle": needle},
        )

    if vtype == "acceptance_manual":
        return VerificationResult(
            "acceptance_manual",
            None,
            "verificação manual pendente",
            spec,
        )

    return VerificationResult("unknown", False, f"verificador desconhecido: {vtype}", spec)


def _no_tests_collected(out: dict[str, Any]) -> bool:
    if out.get("exit_code") == 5:
        return True
    text = f"{out.get('stdout') or ''}\n{out.get('stderr') or ''}".lower()
    return "no tests ran" in text or "collected 0 items" in text


def _has_non_python_deliverable(root: str) -> bool:
    base = Path(root)
    if not base.is_dir():
        return False
    for path in base.rglob("*"):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _DELIVERABLE:
            return True
    return False
