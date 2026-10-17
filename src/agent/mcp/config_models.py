# src/agent/mcp/config_models.py — tipos de configuração MCP
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpServerConfig:
    id: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
