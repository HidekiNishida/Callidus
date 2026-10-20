"""
Arquivo: src/agent/security/paths.py
Nome: paths.py
Propósito: garantir que todo caminho manipulado pelo agente fique dentro da raiz autorizada.
Responsabilidade: camada de infraestrutura — validação de caminhos e escape da raiz.
Componentes: PathSecurityError, resolve_under_root.
Dependências: pathlib.
Observações: caminhos são resolvidos (links simbólicos incluidos) antes da comparação com a raiz.
"""
from __future__ import annotations

from pathlib import Path


class PathSecurityError(ValueError):
    """Caminho que sai da raiz autorizada do projeto."""


def resolve_under_root(root: str | Path, user_path: str) -> Path:
    """Resolve um caminho relativo ou absoluto garantindo que ele fique sob a raiz.

    Args:
        root: raiz autorizada (por exemplo, a pasta do projeto).
        user_path: caminho informado pelo modelo ou pelo usuário.

    Returns:
        O caminho absoluto e resolvido.

    Raises:
        PathSecurityError: quando o caminho resolve para fora da raiz autorizada.
    """
    root_resolved = Path(root).expanduser().resolve()
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = candidate.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise PathSecurityError(f"Caminho fora do escopo autorizado: {user_path}")
    return resolved
