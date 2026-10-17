# src/agent/tools/builtins.py — ferramentas prioritárias
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path

from agent.security.paths import PathSecurityError, resolve_under_root
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec


async def _read_file(ctx: ToolContext, args: dict) -> dict:
    path = args.get("path", "")
    try:
        full = resolve_under_root(ctx.project_root, path)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    if not full.is_file():
        return {"success": False, "error": "arquivo não encontrado", "path": str(full)}
    content = full.read_text(encoding="utf-8", errors="replace")
    return {"success": True, "path": str(full.relative_to(Path(ctx.project_root).resolve())), "content": content}


async def _write_file(ctx: ToolContext, args: dict) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        full = resolve_under_root(ctx.project_root, path)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return {"success": True, "path": path, "bytes": len(content.encode("utf-8"))}


async def _search_grep(ctx: ToolContext, args: dict) -> dict:
    pattern = args.get("pattern", "")
    if not pattern:
        return {"success": False, "error": "pattern obrigatório"}
    root = Path(ctx.project_root).resolve()
    try:
        re.compile(pattern)
    except re.error as exc:
        return {"success": False, "error": f"regex inválida: {exc}"}
    matches: list[dict] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix in {".pyc", ".png", ".jpg"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                matches.append({"path": str(p.relative_to(root)), "line": i, "text": line[:200]})
                if len(matches) >= 100:
                    break
        if len(matches) >= 100:
            break
    return {"success": True, "matches": matches, "count": len(matches)}


async def _run_command(ctx: ToolContext, args: dict) -> dict:
    command = args.get("command")
    if not command or not isinstance(command, list):
        return {"success": False, "error": "command deve ser lista de strings"}
    cwd = args.get("cwd") or ctx.project_root
    try:
        cwd_path = resolve_under_root(ctx.project_root, cwd)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    timeout = float(args.get("timeout", 120))
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd_path),
        env=args.get("env"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"success": False, "error": "timeout", "command": command}
    return {
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[-8000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-8000:],
        "command": command,
    }


async def _git_diff(ctx: ToolContext, args: dict) -> dict:
    cmd = ["git", "-C", str(Path(ctx.project_root).resolve()), "diff", "--stat"]
    if args.get("staged"):
        cmd = ["git", "-C", str(Path(ctx.project_root).resolve()), "diff", "--cached", "--stat"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "success": proc.returncode == 0,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


async def _run_script(ctx: ToolContext, args: dict) -> dict:
    """Executa um arquivo Python dentro do projeto. Testes em tests/ rodam com o pacote no PYTHONPATH."""
    raw = args.get("path")
    if not raw or not isinstance(raw, str):
        return {"success": False, "error": "path obrigatório"}
    try:
        script = resolve_under_root(ctx.project_root, raw)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    if not script.is_file():
        return {"success": False, "error": f"arquivo inexistente: {script}"}
    cwd = script.parent.parent if script.parent.name == "tests" else script.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
    return await _run_command(
        ctx,
        {
            "command": ["python", str(script)],
            "cwd": str(cwd),
            "env": env,
            "timeout": args.get("timeout", 90),
        },
    )


async def _run_pytest(ctx: ToolContext, args: dict) -> dict:
    target = args.get("path", ".")
    try:
        target_path = resolve_under_root(ctx.project_root, target)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    return await _run_command(
        ctx,
        {
            "command": ["python", "-m", "pytest", "-q", str(target_path)],
            "cwd": ctx.project_root,
            "timeout": args.get("timeout", 180),
        },
    )


def register_all(registry: ToolRegistry) -> None:
    specs = [
        ToolSpec(id="read_file", description="Lê arquivo dentro do projeto", input_schema={"path": "str"}),
        ToolSpec(
            id="write_file",
            description="Grava arquivo dentro do projeto",
            input_schema={"path": "str", "content": "str"},
            requires_approval=False,
        ),
        ToolSpec(id="search_grep", description="Busca regex em arquivos", input_schema={"pattern": "str"}),
        ToolSpec(
            id="run_command",
            description="Executa comando (lista argv)",
            input_schema={"command": "list[str]"},
            requires_approval=True,
            timeout_seconds=120,
        ),
        ToolSpec(id="git_diff", description="Diff git resumido", input_schema={"staged": "bool?"}),
        ToolSpec(id="run_pytest", description="Executa pytest em path", input_schema={"path": "str?"}),
        ToolSpec(
            id="run_script",
            description="Executa um arquivo Python local",
            input_schema={"path": "str"},
            requires_approval=True,
            timeout_seconds=90,
        ),
    ]
    handlers = {
        "read_file": _read_file,
        "write_file": _write_file,
        "search_grep": _search_grep,
        "run_command": _run_command,
        "git_diff": _git_diff,
        "run_pytest": _run_pytest,
        "run_script": _run_script,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])
