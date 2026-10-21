"""
Arquivo: src/agent/system/platform_info.py
Nome: platform_info.py
Propósito: descrever o ambiente de execução e diagnosticar bloqueios do sistema operacional.
Responsabilidade: camada de infraestrutura — sistema, sessão gráfica, permissões e limitações.
Componentes: describe_system, diagnose_permissions, session_kind.
Dependências: agent.system.adapters, agent.tools.availability, platform, shutil.
Observações: o diagnóstico diz o que falta e como resolver; ele nunca tenta elevar privilégio.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from agent.system.adapters import current_os, get_adapter, session_kind
from agent.tools.availability import environment_report


def describe_system() -> dict[str, Any]:
    """Descreve o computador onde o agente roda.

    Returns:
        Um dicionário com sistema, arquitetura, sessão gráfica, servidor de display,
        ambiente de desktop e os executáveis opcionais presentes.
    """
    adapter = get_adapter()
    report = environment_report()
    report.update(
        {
            "session": session_kind(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "adapter": adapter.name,
            "optional_tools_present": [tool for tool in adapter.available_tools if shutil.which(tool)],
            "optional_tools_missing": adapter.missing_tools(),
            "notes": list(adapter.notes),
        }
    )
    return report


def _macos_permissions() -> list[dict[str, Any]]:
    """Verifica as permissões do TCC no macOS.

    Returns:
        Uma lista de verificações com o estado e o caminho do ajuste necessário.
    """
    checks: list[dict[str, Any]] = []
    osascript = shutil.which("osascript")
    if not osascript:
        checks.append(
            {
                "permission": "automation",
                "status": "unavailable",
                "detail": "osascript não está instalado; a automação de interface não pode rodar.",
                "fix": "instale o comando line tools do Xcode ou use o binário do sistema.",
            }
        )
        return checks
    checks.append(
        {
            "permission": "automation",
            "status": "probe",
            "detail": "o acesso ao TCC é verificado ao primeiro comando AppleScript; o erro vem do sistema.",
            "fix": "System Settings → Privacy & Security → Automation → habilite o terminal usado.",
        }
    )
    checks.append(
        {
            "permission": "accessibility",
            "status": "probe",
            "detail": "a entrada de mouse e teclado exige Accessibility.",
            "fix": "System Settings → Privacy & Security → Accessibility → habilite o aplicativo.",
        }
    )
    checks.append(
        {
            "permission": "screen_recording",
            "status": "probe",
            "detail": "a captura de tela exige Screen Recording.",
            "fix": "System Settings → Privacy & Security → Screen Recording → habilite o aplicativo.",
        }
    )
    return checks


def _windows_permissions() -> list[dict[str, Any]]:
    """Verifica as condições de sessão e privilégio no Windows.

    Returns:
        Uma lista de verificações com o estado e a observação necessária.
    """
    checks = [
        {
            "permission": "interactive_session",
            "status": "ok" if session_kind() == "windows" else "blocked",
            "detail": (
                "A sessão interativa existe."
                if session_kind() == "windows"
                else "Sem sessão interativa: um serviço do Windows não tem desktop para automatizar."
            ),
            "fix": "" if session_kind() == "windows" else "rode o Callidus na sessão do usuário, não como serviço.",
        },
        {
            "permission": "elevation",
            "status": "ok",
            "detail": "O processo não está elevado; a elevação nunca é solicitada automaticamente.",
            "fix": "",
        },
    ]
    if not shutil.which("powershell"):
        checks.append(
            {
                "permission": "powershell",
                "status": "unavailable",
                "detail": "PowerShell não está disponível no PATH.",
                "fix": "instale o Windows PowerShell 5.1 ou superior.",
            }
        )
    return checks


def _linux_permissions() -> list[dict[str, Any]]:
    """Verifica as condições de sessão no Linux.

    Returns:
        Uma lista de verificações com o estado e a observação necessária.
    """
    kind = session_kind()
    checks = [
        {
            "permission": "display_server",
            "status": "ok" if kind in {"x11", "wayland"} else "blocked",
            "detail": f"sessão gráfica: {kind}.",
            "fix": "" if kind in {"x11", "wayland"} else "rode dentro de uma sessão gráfica (X11 ou Wayland).",
        },
        {
            "permission": "portal",
            "status": "ok" if kind == "wayland" else "not_required",
            "detail": (
                "Wayland exige portais para captura de tela e entrada global."
                if kind == "wayland"
                else "X11 não exige portais para as ferramentas usadas."
            ),
            "fix": "instale xdg-desktop-portal e o portal do seu ambiente." if kind == "wayland" else "",
        },
    ]
    for tool in get_adapter("linux").missing_tools():
        checks.append(
            {
                "permission": f"tool:{tool}",
                "status": "unavailable",
                "detail": f"'{tool}' não está instalado.",
                "fix": f"instale {tool} pelo gerenciador de pacotes do sistema (requer privilégio de administrador).",
            }
        )
    return checks


def diagnose_permissions() -> dict[str, Any]:
    """Diagnostica as permissões que a automação de interface pode exigir.

    Returns:
        Um dicionário com o sistema, a sessão e a lista de verificações.
    """
    system = current_os()
    if system == "macos":
        checks = _macos_permissions()
    elif system == "windows":
        checks = _windows_permissions()
    else:
        checks = _linux_permissions()
    blocked = [item for item in checks if item["status"] in {"blocked", "unavailable"}]
    return {
        "system": system,
        "session": session_kind(),
        "checks": checks,
        "blocked": len(blocked),
        "ready": not blocked,
    }


def platform_summary() -> str:
    """Resumo textual do ambiente, para o agente decidir o modo de automação.

    Returns:
        Uma frase com sistema, sessão e modo de execução viável.
    """
    system = current_os()
    session = session_kind()
    if session == "headless":
        return (
            f"{system} sem sessão gráfica: só headless (processos, arquivos, HTTP e navegador "
            "sem janela) é viável."
        )
    if system == "linux" and session == "wayland":
        return (
            "linux/Wayland: a automação de interface é limitada; prefira APIs (AT-SPI, D-Bus) "
            "a coordenadas de tela."
        )
    return f"{system} com sessão gráfica ({session}): automação de desktop e de navegador viável."
