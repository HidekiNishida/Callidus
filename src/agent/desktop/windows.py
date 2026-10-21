"""
Arquivo: src/agent/desktop/windows.py
Nome: windows.py
Propósito: listar janelas ativas, títulos e aplicativos donos das janelas.
Responsabilidade: camada de infraestrutura — inventário de janelas por plataforma.
Componentes: list_windows, WindowInfo.
Dependências: agent.system.adapters, subprocess.
Observações: a enumeração usa mecanismos nativos do sistema, não coordenadas de tela.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from agent.system.adapters import current_os, session_kind


@dataclass(frozen=True)
class WindowInfo:
    """Uma janela visível da sessão gráfica.

    Atributos:
        title: título da janela.
        app: aplicativo ao qual a janela pertence, quando conhecido.
        pid: processo dono da janela, quando conhecido.
    """

    title: str
    app: str = ""
    pid: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável da janela.

        Returns:
            Um dicionário com `title`, `app` e `pid`.
        """
        return {"title": self.title, "app": self.app, "pid": self.pid}


def _run(command: list[str], timeout: float = 25) -> subprocess.CompletedProcess:
    """Executa um comando do sistema capturing a saída.

    Args:
        command: comando e argumentos.
        timeout: tempo limite da execução.

    Returns:
        O resultado da execução; em falha de sistema, um resultado sintético com código 127.
    """
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def _macos_windows() -> tuple[list[WindowInfo], str | None]:
    """Janelas do macOS, lidas do System Events.

    Returns:
        Tupla com a lista de janelas e o erro, quando houver.
    """
    script = (
        'tell application "System Events" to get {name, unix id, title of windows} of '
        "(every process whose visible is true)"
    )
    completed = _run(["osascript", "-e", script])
    if completed.returncode != 0:
        return [], (completed.stderr or "osascript falhou").strip()[:300]
    windows: list[WindowInfo] = []
    # A saída do AppleScript é uma lista de registros; o parser por texto cobre o caso comum.
    for chunk in re.findall(r'name:"([^"]*)", unix id:(\d+), title of windows:\{([^}]*)\}', completed.stdout or ""):
        app, pid, titles = chunk
        for title in re.findall(r'"([^"]*)"', titles):
            if title.strip():
                windows.append(WindowInfo(title=title, app=app, pid=int(pid)))
    if not windows:
        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if line and line not in {"{}", ""}:
                windows.append(WindowInfo(title=line))
    return windows, None


def _windows_windows() -> tuple[list[WindowInfo], str | None]:
    """Janelas do Windows, lidas dos processos com título de janela.

    Returns:
        Tupla com a lista de janelas e o erro, quando houver.
    """
    script = (
        "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
        "ForEach-Object { \"$($_.Id)|$($_.ProcessName)|$($_.MainWindowTitle)\" }"
    )
    completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    if completed.returncode != 0:
        return [], (completed.stderr or "powershell falhou").strip()[:300]
    windows: list[WindowInfo] = []
    for line in (completed.stdout or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        windows.append(WindowInfo(title=parts[2], app=parts[1], pid=pid))
    return windows, None


def _linux_windows() -> tuple[list[WindowInfo], str | None]:
    """Janelas do Linux, lidas do `wmctrl` (X11) ou do Wayland, quando disponível.

    Returns:
        Tupla com a lista de janelas e o erro, quando houver.
    """
    if session_kind() == "wayland":
        completed = _run(["wayland-info"], timeout=15)
        if completed.returncode == 0:
            return [], None
        return [], (
            "Wayland não expõe a lista de janelas por linha de comando; "
            "use automação por API (AT-SPI) ou o portal de captura."
        )
    completed = _run(["wmctrl", "-l"], timeout=20)
    if completed.returncode != 0:
        return [], (completed.stderr or "wmctrl falhou").strip()[:300]
    windows: list[WindowInfo] = []
    for line in (completed.stdout or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 3:
            continue
        title = parts[4] if len(parts) > 4 else ""
        windows.append(WindowInfo(title=title, app=parts[3] if len(parts) > 3 else ""))
    return windows, None


def list_windows(match: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista as janelas visíveis da sessão gráfica.

    Args:
        match: filtro opcional por substring do título ou do aplicativo.
        limit: quantidade máxima de janelas devolvidas.

    Returns:
        Um dicionário com a lista de janelas e a sessão usada.
    """
    system = current_os()
    if system == "macos":
        windows, error = _macos_windows()
    elif system == "windows":
        windows, error = _windows_windows()
    else:
        windows, error = _linux_windows()
    if match:
        needle = match.lower()
        windows = [item for item in windows if needle in item.title.lower() or needle in item.app.lower()]
    payload: dict[str, Any] = {
        "success": error is None,
        "windows": [item.as_dict() for item in windows[: max(1, int(limit))]],
        "count": len(windows),
        "session": session_kind(),
        "system": system,
    }
    if error:
        payload["error"] = error
    return payload
