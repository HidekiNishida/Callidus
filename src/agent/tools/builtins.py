# src/agent/tools/builtins.py — ferramentas prioritárias
from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from agent.security.paths import PathSecurityError, resolve_under_root
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
READ_LINE_CAP = 400
LIST_CAP = 200

TOOL_CATALOG = (
    "Ferramentas locais (use exatamente estes ids): "
    "list_dir, glob_files, read_file, search_grep, edit_file, write_file, "
    "delete_file, make_dir, move_file, run_pytest, run_script, run_command, git_status, git_diff. "
    "edit_file: path, old_string, new_string. "
    "read_file: path, offset e limit opcionais. "
    "run_script executa um .py. run_command aceita command como lista ou string e exige aprovação. "
    "delete_file e move_file exigem aprovação. Não invente outros nomes."
)


def _root(ctx: ToolContext) -> Path:
    return Path(ctx.project_root).resolve()


def _skipped(rel: Path) -> bool:
    return any(part in SKIP_DIRS for part in rel.parts)


def _resolve(ctx: ToolContext, raw: str) -> tuple[Path | None, dict | None]:
    try:
        return resolve_under_root(ctx.project_root, raw), None
    except PathSecurityError as exc:
        return None, {"success": False, "error": str(exc)}


async def _read_file(ctx: ToolContext, args: dict) -> dict:
    path = args.get("path", "")
    try:
        full = resolve_under_root(ctx.project_root, path)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    if not full.is_file():
        return {"success": False, "error": "arquivo não encontrado", "path": str(full)}
    content = full.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    total = len(lines)
    try:
        offset = max(1, int(args.get("offset") or args.get("start_line") or 1))
    except (TypeError, ValueError):
        offset = 1
    raw_limit = args.get("limit", args.get("max_lines"))
    limit: int | None
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else None
    except (TypeError, ValueError):
        limit = None
    truncated = False
    if limit is None and total > READ_LINE_CAP:
        limit = READ_LINE_CAP
        truncated = True
    if offset > total and total:
        return {"success": False, "error": "offset além do fim do arquivo", "total_lines": total}
    window = lines[offset - 1 :] if limit is None else lines[offset - 1 : offset - 1 + max(limit, 0)]
    if limit is not None and offset - 1 + limit < total:
        truncated = True
    rel = str(full.relative_to(_root(ctx)))
    return {
        "success": True,
        "path": rel,
        "content": "\n".join(window),
        "offset": offset,
        "total_lines": total,
        "truncated": truncated,
    }


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
    pattern = args.get("pattern") or args.get("query") or ""
    if not pattern:
        return {"success": False, "error": "pattern obrigatório"}
    root = _root(ctx)
    scope = root
    if args.get("path"):
        scope, err = _resolve(ctx, str(args["path"]))
        if err:
            return err
        if scope is None or not scope.exists():
            return {"success": False, "error": "caminho inexistente"}
    try:
        re.compile(pattern)
    except re.error as exc:
        return {"success": False, "error": f"regex inválida: {exc}"}
    matches: list[dict] = []
    files = [scope] if scope.is_file() else scope.rglob("*")
    for p in files:
        if not p.is_file() or p.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip"}:
            continue
        rel = p.relative_to(root)
        if _skipped(rel):
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


def _argv(command: object) -> list[str] | None:
    if isinstance(command, str) and command.strip():
        return shlex.split(command)
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        if len(command) == 1 and " " in command[0]:
            return shlex.split(command[0])
        return list(command)
    return None


async def _run_command(ctx: ToolContext, args: dict) -> dict:
    command = _argv(args.get("command"))
    if not command:
        return {"success": False, "error": "command deve ser lista ou string"}
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
    root = str(_root(ctx))
    cmd = ["git", "-C", root, "diff"]
    if args.get("stat"):
        cmd.append("--stat")
    if args.get("staged"):
        cmd.append("--cached")
    if isinstance(args.get("path"), str) and args["path"]:
        cmd.extend(["--", args["path"]])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    stdout = proc.stdout
    truncated = len(stdout) > 12000
    return {
        "success": proc.returncode == 0,
        "stdout": stdout[:12000],
        "stderr": proc.stderr[:2000],
        "truncated": truncated,
    }


async def _git_status(ctx: ToolContext, args: dict) -> dict:
    proc = subprocess.run(
        ["git", "-C", str(_root(ctx)), "status", "--short"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "success": proc.returncode == 0,
        "stdout": proc.stdout[:8000],
        "stderr": proc.stderr[:2000],
    }


async def _list_dir(ctx: ToolContext, args: dict) -> dict:
    full, err = _resolve(ctx, str(args.get("path") or "."))
    if err:
        return err
    if full is None or not full.is_dir():
        return {"success": False, "error": "diretório inexistente"}
    root = _root(ctx)
    entries: list[dict] = []
    iterator = full.rglob("*") if args.get("recursive") else full.iterdir()
    for path in iterator:
        rel = path.relative_to(root)
        if _skipped(rel):
            continue
        entries.append({"path": str(rel), "kind": "dir" if path.is_dir() else "file"})
        if len(entries) >= LIST_CAP:
            break
    entries.sort(key=lambda item: (item["kind"] != "dir", item["path"]))
    return {"success": True, "entries": entries, "truncated": len(entries) >= LIST_CAP}


async def _glob_files(ctx: ToolContext, args: dict) -> dict:
    pattern = args.get("pattern") or args.get("glob") or ""
    if not isinstance(pattern, str) or not pattern:
        return {"success": False, "error": "pattern obrigatório"}
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        return {"success": False, "error": "pattern fora do projeto"}
    root = _root(ctx)
    matches: list[str] = []
    for path in root.glob(pattern):
        rel = path.relative_to(root)
        if _skipped(rel):
            continue
        matches.append(str(rel))
        if len(matches) >= LIST_CAP:
            break
    return {"success": True, "matches": matches, "truncated": len(matches) >= LIST_CAP}


async def _edit_file(ctx: ToolContext, args: dict) -> dict:
    raw = args.get("path", "")
    old = args.get("old_string", args.get("old", args.get("search", args.get("find"))))
    if "new_string" in args:
        new = args.get("new_string")
    elif "new" in args:
        new = args.get("new")
    elif "replace" in args:
        new = args.get("replace")
    else:
        new = args.get("replacement")
    if not isinstance(old, str) or not isinstance(new, str):
        return {"success": False, "error": "old_string e new_string são obrigatórios"}
    if old == "":
        return {"success": False, "error": "old_string vazio"}
    full, err = _resolve(ctx, str(raw))
    if err:
        return err
    if full is None or not full.is_file():
        return {"success": False, "error": "arquivo não encontrado"}
    content = full.read_text(encoding="utf-8", errors="replace")
    count = content.count(old)
    if count == 0:
        return {"success": False, "error": "trecho não encontrado", "path": str(raw)}
    if count > 1 and not args.get("replace_all"):
        return {"success": False, "error": f"trecho ambíguo ({count} vezes); use replace_all ou um trecho único"}
    updated = content.replace(old, new) if args.get("replace_all") else content.replace(old, new, 1)
    full.write_text(updated, encoding="utf-8")
    return {"success": True, "path": str(raw), "replacements": count if args.get("replace_all") else 1}


async def _delete_file(ctx: ToolContext, args: dict) -> dict:
    full, err = _resolve(ctx, str(args.get("path") or ""))
    if err:
        return err
    if full is None or not full.is_file():
        return {"success": False, "error": "arquivo inexistente"}
    full.unlink()
    return {"success": True, "path": str(args.get("path"))}


async def _make_dir(ctx: ToolContext, args: dict) -> dict:
    full, err = _resolve(ctx, str(args.get("path") or ""))
    if err:
        return err
    if full is None:
        return {"success": False, "error": "path obrigatório"}
    if full.exists() and not full.is_dir():
        return {"success": False, "error": "já existe um arquivo nesse caminho"}
    full.mkdir(parents=True, exist_ok=True)
    return {"success": True, "path": str(args.get("path"))}


async def _move_file(ctx: ToolContext, args: dict) -> dict:
    src_raw = args.get("from") or args.get("source") or args.get("path")
    dst_raw = args.get("to") or args.get("dest") or args.get("destination")
    if not isinstance(src_raw, str) or not isinstance(dst_raw, str):
        return {"success": False, "error": "from e to são obrigatórios"}
    src, err = _resolve(ctx, src_raw)
    if err:
        return err
    dst, err = _resolve(ctx, dst_raw)
    if err:
        return err
    if src is None or dst is None or not src.is_file():
        return {"success": False, "error": "origem inexistente"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"success": True, "from": src_raw, "to": dst_raw}


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
        ToolSpec(id="list_dir", description="Lista arquivos do projeto", input_schema={"path": "str?"}),
        ToolSpec(id="glob_files", description="Encontra arquivos por glob", input_schema={"pattern": "str"}),
        ToolSpec(
            id="edit_file",
            description="Substitui um trecho único do arquivo",
            input_schema={"path": "str", "old_string": "str", "new_string": "str"},
        ),
        ToolSpec(
            id="delete_file",
            description="Apaga um arquivo do projeto",
            input_schema={"path": "str"},
            requires_approval=True,
        ),
        ToolSpec(id="make_dir", description="Cria um diretório", input_schema={"path": "str"}),
        ToolSpec(
            id="move_file",
            description="Move ou renomeia um arquivo",
            input_schema={"from": "str", "to": "str"},
            requires_approval=True,
        ),
        ToolSpec(id="git_status", description="git status --short", input_schema={}),
    ]
    handlers = {
        "read_file": _read_file,
        "write_file": _write_file,
        "search_grep": _search_grep,
        "run_command": _run_command,
        "git_diff": _git_diff,
        "run_pytest": _run_pytest,
        "run_script": _run_script,
        "list_dir": _list_dir,
        "glob_files": _glob_files,
        "edit_file": _edit_file,
        "delete_file": _delete_file,
        "make_dir": _make_dir,
        "move_file": _move_file,
        "git_status": _git_status,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])
