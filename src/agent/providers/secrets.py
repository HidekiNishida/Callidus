"""
Arquivo: src/agent/providers/secrets.py
Nome: secrets.py
Propósito: guardar as credenciais gravadas pela interface, fora do versionamento.
Responsabilidade: camada de infraestrutura — persistência segura das chaves dos provedores.
Componentes: secret_path, write_secret, read_secret, delete_secret, secret_state, is_world_readable.
Dependências: agent.config, agent.providers.base.
Observações: a pasta fica em modo 0700 e cada credencial em 0600.
"""
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
    """Arquivo da credencial de um provedor. O nome do provedor vira nome de arquivo seguro.

    Args:
        settings: configurações que definem a pasta de segredos.
        name: nome do provedor dono da credencial.

    Returns:
        O caminho do arquivo de credencial.

    Raises:
        ProviderConfigError: quando o nome do provedor não gera um arquivo válido.
    """
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in (name or "")).strip("-")
    if not safe:
        raise ProviderConfigError("nome do provedor inválido para credencial")
    return settings.resolved_secrets_dir() / f"{safe}{SECRET_SUFFIX}"


def write_secret(settings: Settings, name: str, secret: str) -> Path:
    """Grava a credencial com permissão restrita (0600) e devolve o caminho.

    Args:
        settings: configurações que definem a pasta de segredos.
        name: nome do provedor dono da credencial.
        secret: credencial a gravar.

    Returns:
        O caminho do arquivo gravado.

    Raises:
        ProviderConfigError: quando a credencial está vazia.
    """
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
    """Lê a credencial gravada de um provedor.

    Args:
        settings: configurações que definem a pasta de segredos.
        name: nome do provedor dono da credencial.

    Returns:
        A credencial, ou `None` quando não existe ou não pode ser lida.
    """
    path = secret_path(settings, name)
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def delete_secret(settings: Settings, name: str) -> bool:
    """Remove a credencial gravada de um provedor.

    Args:
        settings: configurações que definem a pasta de segredos.
        name: nome do provedor dono da credencial.

    Returns:
        `True` quando o arquivo existia e foi removido.
    """
    path = secret_path(settings, name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def secret_state(settings: Settings, name: str) -> dict:
    """Situação da credencial sem revelar o valor.

    Args:
        settings: configurações que definem a pasta de segredos.
        name: nome do provedor dono da credencial.

    Returns:
        Um dicionário com `configured` e a origem da credencial.
    """
    path = secret_path(settings, name)
    if path.is_file():
        return {"configured": True, "source": "file"}
    return {"configured": False, "source": None}


def is_world_readable(path: Path) -> bool:
    """A credencial não pode ficar legível por outros usuários do sistema.

    Args:
        path: arquivo de credencial.

    Returns:
        `True` quando o arquivo é legível pelo grupo ou por outros.
    """
    try:
        mode = path.stat().st_mode
    except OSError:  # pragma: no cover - arquivo sumiu
        return False
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH))
