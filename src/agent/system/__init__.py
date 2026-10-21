"""
Arquivo: src/agent/system/__init__.py
Nome: __init__.py
Propósito: expor a camada de automação do sistema (processos, aplicativos, diagnóstico).
Responsabilidade: camada de infraestrutura — ponto de entrada estável para o resto do agente.
Componentes: reexports de `platform_info`, `processes`, `apps` e `adapters`.
Dependências: agent.system.*.
Observações: nada aqui exige dependência paga ou de nuvem; usa apenas o que o sistema oferece.
"""
from __future__ import annotations

from agent.system.adapters import get_adapter
from agent.system.apps import launch_app, list_apps, open_path
from agent.system.platform_info import describe_system, diagnose_permissions
from agent.system.processes import (
    ProcessHandle,
    ProcessManager,
    list_processes,
    terminate_process,
)

__all__ = [
    "ProcessHandle",
    "ProcessManager",
    "describe_system",
    "diagnose_permissions",
    "get_adapter",
    "launch_app",
    "list_apps",
    "list_processes",
    "open_path",
    "terminate_process",
]
