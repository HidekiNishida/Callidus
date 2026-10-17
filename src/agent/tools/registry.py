# src/agent/tools/registry.py — registro central de ferramentas
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


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


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


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
        spec = self.get_spec(tool_id)
        if spec.requires_approval and not approved:
            return {
                "success": False,
                "error": "approval_required",
                "tool": tool_id,
            }
        handler = self._handlers[tool_id]
        return await handler(ctx, args)


def build_default_registry() -> ToolRegistry:
    from agent.tools import builtins as built

    reg = ToolRegistry()
    built.register_all(reg)
    return reg
