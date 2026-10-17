# src/agent/security/paths.py — validação de caminhos dentro do escopo
from __future__ import annotations

from pathlib import Path


class PathSecurityError(ValueError):
    pass


def resolve_under_root(root: str | Path, user_path: str) -> Path:
    root_resolved = Path(root).expanduser().resolve()
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = candidate.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise PathSecurityError(f"Caminho fora do escopo autorizado: {user_path}")
    return resolved
