# src/agent/providers/secrets.py — credenciais gravadas pela interface (fora do versionamento)
from __future__ import annotations

import os
import stat
from pathlib import Path

from agent.config import Settings
from agent.providers.base import ProviderConfigError

SECRET_SUFFIX = ".key"
DIR_MODE = 0o700
FILE_MODE = 0o600


def secret_path(settings: Settings, name: str) -> Path:
    """Arquivo da credencial de um provedor. O nome do provedor vira nome de arquivo seguro."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in (name or "")).strip("-")
    if not safe:
        raise ProviderConfigError("nome do provedor inválido para credencial")
    return settings.resolved_secrets_dir() / f"{safe}{SECRET_SUFFIX}"


def write_secret(settings: Settings, name: str, secret: str) -> Path:
    """Grava a credencial com permissão restrita (0600) e devolve o caminho."""
    if not secret or not secret.strip():
        raise ProviderConfigError("credencial vazia")
    path = secret_path(settings, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, DIR_MODE)
    except OSError:  # pragma: no cover - sistemas sem chmod
        pass
    path.write_text(secret.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, FILE_MODE)
    except OSError:  # pragma: no cover - sistemas sem chmod
        pass
    return path


def read_secret(settings: Settings, name: str) -> str | None:
    path = secret_path(settings, name)
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def delete_secret(settings: Settings, name: str) -> bool:
    path = secret_path(settings, name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def secret_state(settings: Settings, name: str) -> dict:
    """Situação da credencial sem revelar o valor."""
    path = secret_path(settings, name)
    if path.is_file():
        return {"configured": True, "source": "file"}
    return {"configured": False, "source": None}


def is_world_readable(path: Path) -> bool:
    """A credencial não pode ficar legível por outros usuários do sistema."""
    try:
        mode = path.stat().st_mode
    except OSError:  # pragma: no cover - arquivo sumiu
        return False
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH))
