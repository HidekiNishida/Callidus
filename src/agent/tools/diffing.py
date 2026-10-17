# src/agent/tools/diffing.py — diff curto para a conversa
from __future__ import annotations

import difflib


def unified_diff_text(path: str, before: str, after: str, *, limit: int = 4000) -> dict:
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    truncated = len(diff) > limit
    if truncated:
        diff = diff[:limit].rstrip() + "\n…"
    return {"diff": diff, "added": added, "removed": removed, "truncated": truncated}
