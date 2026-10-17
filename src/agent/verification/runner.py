# src/agent/verification/runner.py — verificações determinísticas
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.tools.registry import ToolContext, build_default_registry


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

    if vtype == "pytest":
        path = spec.get("path", ".")
        out = await tools.execute("run_pytest", ctx, {"path": path}, approved=approved)
        passed = bool(out.get("success"))
        return VerificationResult(
            verifier="pytest",
            passed=passed,
            summary="pytest ok" if passed else "pytest falhou",
            detail=out,
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
