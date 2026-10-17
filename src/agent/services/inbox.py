# src/agent/services/inbox.py — conversas que ainda não pertencem a uma pasta
from __future__ import annotations

INBOX_ROOT = "agente-inbox://local"


def is_inbox_path(root_path: str | None) -> bool:
    return str(root_path or "").startswith("agente-inbox://")
