"""
Arquivo: src/agent/automation/service/__init__.py
Nome: __init__.py
Propósito: expor os adaptadores de inicialização nativa do runtime de automações.
Responsabilidade: camada de infraestrutura — escolha do adaptador compatível com a máquina.
Componentes: ServiceAdapter, ServiceOptions, ServiceStatus, LaunchdAdapter, SystemdAdapter, WindowsTaskAdapter, current_adapter, adapters_status, default_options.
Dependências: agent.automation.service.base, agent.automation.service.launchd, agent.automation.service.systemd, agent.automation.service.windows.
Observações: o núcleo do Callidus é o mesmo em toda parte; só a inicialização nativa muda.

Escolhe o adaptador compatível com a máquina e expõe os três.

O núcleo do Callidus é o mesmo em toda parte; só a inicialização nativa muda.
"""
from __future__ import annotations

import os

from agent.automation.service.base import (
    ServiceAdapter,
    ServiceOptions,
    ServiceStatus,
    default_options,
)
from agent.automation.service.launchd import LaunchdAdapter
from agent.automation.service.systemd import SystemdAdapter
from agent.automation.service.windows import WindowsTaskAdapter

ADAPTERS: tuple[type[ServiceAdapter], ...] = (
    LaunchdAdapter,
    SystemdAdapter,
    WindowsTaskAdapter,
)


def current_adapter() -> ServiceAdapter:
    """Adaptador da plataforma atual (o primeiro compatível)."""
    for adapter in ADAPTERS:
        instance = adapter()
        if instance.available():
            return instance
    if os.name == "nt":
        return WindowsTaskAdapter()
    if os.uname().sysname == "Darwin" if hasattr(os, "uname") else False:
        return LaunchdAdapter()
    return SystemdAdapter()


def adapters_status() -> list[dict]:
    """Situação de todos os adaptadores (útil para diagnóstico multiplataforma)."""
    out: list[dict] = []
    for adapter in ADAPTERS:
        instance = adapter()
        try:
            out.append({"platform": instance.platform_name, "available": instance.available()})
        except Exception as exc:  # noqa: BLE001
            out.append({"platform": instance.platform_name, "available": False, "error": str(exc)})
    return out


__all__ = [
    "ADAPTERS",
    "LaunchdAdapter",
    "ServiceAdapter",
    "ServiceOptions",
    "ServiceStatus",
    "SystemdAdapter",
    "WindowsTaskAdapter",
    "adapters_status",
    "current_adapter",
    "default_options",
]
