# src/agent/tools/registry.py — registro central de ferramentas
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from agent.observability import emit


class ToolSpec(BaseModel):
    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    timeout_seconds: float = 60.0


@dataclass
class ToolContext:
    project_root: str
    run_id: str | None = None
    task_id: str | None = None
    memory_saver: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    browser_mode: str = "off"
    # Configuração do computador remoto (quando o projeto roda em outro servidor).
    remote: Any = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

# Nomes que o modelo costuma inventar → ferramenta real.
TOOL_ALIASES: dict[str, str] = {
    "ls": "list_dir",
    "list_files": "list_dir",
    "list_directory": "list_dir",
    "dir": "list_dir",
    "glob": "glob_files",
    "find_files": "glob_files",
    "find": "glob_files",
    "grep": "search_grep",
    "search": "search_grep",
    "str_replace": "edit_file",
    "search_replace": "edit_file",
    "apply_patch": "edit_file",
    "replace_in_file": "edit_file",
    "edit": "edit_file",
    "delete": "delete_file",
    "remove_file": "delete_file",
    "rm": "delete_file",
    "shell": "run_command",
    "bash": "run_command",
    "exec": "run_command",
    "python": "run_script",
    "pytest": "run_pytest",
    "mkdir": "make_dir",
    "create_directory": "make_dir",
    "mv": "move_file",
    "rename": "move_file",
    "git": "git_status",
    "browse": "browser",
    "web": "browser",
    "open_url": "browser",
    "sysinfo": "system_info",
    "os_info": "system_info",
    "whoami": "system_info",
}


def canonical_tool_id(tool_id: str) -> str:
    return TOOL_ALIASES.get(tool_id, tool_id)


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.id] = spec
        self._handlers[spec.id] = handler

    def get_spec(self, tool_id: str) -> ToolSpec:
        if tool_id not in self._specs:
            raise KeyError(tool_id)
        return self._specs[tool_id]

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    async def execute(
        self,
        tool_id: str,
        ctx: ToolContext,
        args: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        tool_id = canonical_tool_id(tool_id)
        if tool_id not in self._specs:
            known = ", ".join(sorted(self._specs))
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "ferramenta desconhecida", "executed": False},
            )
            return {"success": False, "error": f"ferramenta desconhecida: {tool_id}", "known": known}
        spec = self.get_spec(tool_id)
        if spec.requires_approval and not approved:
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "approval_required", "executed": False},
            )
            return {
                "success": False,
                "error": "approval_required",
                "tool": tool_id,
            }
        handler = self._handlers[tool_id]
        call_id = uuid.uuid4().hex[:12]
        token = _CALL_ID.set(call_id)
        started = time.monotonic()
        emit("tool.started", {"call_id": call_id, "tool": tool_id, "args": _args_preview(args)}, commit=True)
        try:
            result = await handler(ctx, args)
        except Exception as exc:
            emit(
                "tool.failed",
                {"call_id": call_id, "tool": tool_id, "error": f"{type(exc).__name__}: {exc}", "duration_ms": _ms(started)},
            )
            raise
        finally:
            _CALL_ID.reset(token)
        if result.get("success"):
            emit("tool.completed", {"call_id": call_id, "tool": tool_id, "duration_ms": _ms(started), "summary": _summary(result)})
        else:
            emit(
                "tool.failed",
                {
                    "call_id": call_id,
                    "tool": tool_id,
                    "error": str(result.get("error") or "falhou"),
                    "duration_ms": _ms(started),
                    "summary": _summary(result),
                },
            )
        return result


_CALL_ID: ContextVar[str | None] = ContextVar("tool_call_id", default=None)
_PREVIEW_KEYS = ("content", "new_string", "old_string", "new", "old", "replace", "replacement")


def current_call_id() -> str | None:
    """Id da chamada de ferramenta em andamento (comandos e arquivos usam o mesmo para se ligar a ela)."""
    return _CALL_ID.get()


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _args_preview(args: dict[str, Any]) -> dict[str, Any]:
    """Argumentos para exibição: conteúdo de arquivo vira tamanho (o diff real sai em `file.*`)."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key in _PREVIEW_KEYS and isinstance(value, str) and len(value) > 200:
            out[key] = f"[{len(value)} caracteres]"
        else:
            out[key] = value
    return out


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keep = ("path", "exit_code", "count", "bytes", "added", "removed", "replacements", "total_lines", "truncated", "category")
    return {k: result[k] for k in keep if k in result}


def build_default_registry() -> ToolRegistry:
    from agent.tools import builtins as built

    reg = ToolRegistry()
    built.register_all(reg)
    return reg
