# src/agent/automation/security.py — permissões decididas antes do disparo
"""As permissões de uma automação são decididas **antes** do disparo e validadas de
novo a cada execução. O modelo não amplia nada em tempo de execução: uma ação que
não passa na validação é bloqueada, não replanejada.

Regras aplicadas:

- Scripts só rodam quando a definição autoriza (`allow_scripts`) e o executável está
  na allowlist de comandos.
- Diretórios são resolvidos com a validação de caminhos já existente no Callidus
  (`agent.security.paths.resolve_under_root`) — nenhum caminho escapa do escopo.
- Saídas e erros passam pela sanitização existente antes de virar evidência.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from agent.automation.contracts import PermissionSpec
from agent.observability.sanitize import sanitize
from agent.security.paths import PathSecurityError, resolve_under_root


class PermissionDenied(ValueError):
    """A execução não está autorizada pela definição aprovada."""

    def __init__(self, message: str, *, reason: str = "permission_denied") -> None:
        super().__init__(message)
        self.reason = reason


def command_allowed(command: list[str], permissions: PermissionSpec) -> bool:
    """O executável (primeiro item) está na allowlist?"""
    if not command:
        return False
    executable = command[0]
    allowed = permissions.allowed_commands or []
    for prefix in allowed:
        if executable == prefix:
            return True
        if prefix.endswith("*") and executable.startswith(prefix[:-1]):
            return True
        if os.path.basename(executable) == os.path.basename(prefix):
            return True
    return False


def assert_script_allowed(command: list[str], permissions: PermissionSpec) -> None:
    """Valida a autorização de um script antes de executá-lo."""
    if not permissions.allow_scripts:
        raise PermissionDenied(
            "a definição não autoriza execução de scripts", reason="scripts_not_allowed"
        )
    if not command_allowed(command, permissions):
        raise PermissionDenied(
            f"executável fora da allowlist: {command[0] if command else '<vazio>'}",
            reason="command_not_allowed",
        )


def resolve_workdir(
    cwd: str | None,
    *,
    project_root: str | Path,
    permissions: PermissionSpec,
) -> Path:
    """Resolve o diretório de trabalho dentro do escopo autorizado."""
    roots = [str(project_root)]
    roots.extend(permissions.allowed_paths or [])
    raw = cwd or str(project_root)
    for root in roots:
        try:
            return resolve_under_root(root, raw)
        except PathSecurityError:
            continue
    raise PermissionDenied(
        f"diretório de trabalho fora do escopo autorizado: {raw}",
        reason="path_not_allowed",
    )


def assert_path_allowed(path: str | Path, permissions: PermissionSpec, *, project_root: str | Path) -> Path:
    """Valida um caminho explícito (script, recibo) contra os escopos autorizados."""
    roots = [str(project_root)]
    roots.extend(permissions.allowed_paths or [])
    for root in roots:
        try:
            return resolve_under_root(root, str(path))
        except PathSecurityError:
            continue
    raise PermissionDenied(
        f"caminho fora do escopo autorizado: {path}", reason="path_not_allowed"
    )


def build_env(extra: dict[str, str] | None, *, allow_inherit: bool = True) -> dict[str, str]:
    """Ambiente controlado: herda o ambiente do processo (sem segredos novos) e aplica o extra.

    As chaves do ambiente do processo nunca são gravadas na evidência — o `sanitize`
    descarta `env`/`environ`.
    """
    env: dict[str, str] = dict(os.environ) if allow_inherit else {}
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


def redact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Sanitiza a evidência antes de persistir (segredos não entram no banco nem nos logs)."""
    return sanitize(evidence)


def which_or_none(executable: str) -> str | None:
    return shutil.which(executable)
