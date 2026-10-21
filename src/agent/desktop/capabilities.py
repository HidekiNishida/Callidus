"""
Arquivo: src/agent/desktop/capabilities.py
Nome: capabilities.py
Propósito: descrever a tela do computador e capturar screenshots de tela inteira ou de região.
Responsabilidade: camada de infraestrutura — geometria da tela e captura de imagem por plataforma.
Componentes: screen_info, capture_screenshot.
Dependências: agent.system.adapters, subprocess, shutil, tempfile.
Observações: a captura usa apenas o que o sistema oferece; sem permissão de gravação, o erro é explícito.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from agent.system.adapters import current_os, get_adapter, session_kind

#: Padrão de `bounds` devolvido pelo AppleScript: "x, y, largura, altura".
_OSA_BOUNDS = re.compile(r"(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)")


def _run(command: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
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


def _macos_screen() -> dict[str, Any]:
    """Geometria da tela no macOS, lida do desktop do Finder.

    Returns:
        Um dicionário com os limites da tela e o modo de captura disponível.
    """
    info: dict[str, Any] = {"system": "macos", "bounds": None, "capture_tool": "screencapture"}
    if not shutil.which("osascript"):
        info["error"] = "osascript ausente: o macOS não tem a ferramenta de linha de comando completa."
        return info
    completed = _run(["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'], timeout=20)
    if completed.returncode != 0:
        info["error"] = (completed.stderr or "osascript falhou").strip()[:400]
        info["hint"] = "conceda a permissão de Automação ao terminal do Callidus."
        return info
    match = _OSA_BOUNDS.search(completed.stdout or "")
    if not match:
        info["error"] = "não foi possível ler os limites da tela."
        return info
    x, y, width, height = (int(value) for value in match.groups())
    info["bounds"] = {"x": x, "y": y, "width": width, "height": height}
    info["monitors"] = 1
    return info


def _windows_screen() -> dict[str, Any]:
    """Geometria da tela no Windows, lida das telas do Windows Forms.

    Returns:
        Um dicionário com os limites de cada monitor e o modo de captura disponível.
    """
    info: dict[str, Any] = {"system": "windows", "bounds": None, "monitors": []}
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Screen]::AllScreens | ForEach-Object { "
        "$b=$_.Bounds; \"$($b.X)|$($b.Y)|$($b.Width)|$($b.Height)\" }"
    )
    completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    if completed.returncode != 0:
        info["error"] = (completed.stderr or "powershell falhou").strip()[:400]
        return info
    for line in (completed.stdout or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4:
            continue
        try:
            x, y, width, height = (int(value) for value in parts)
        except ValueError:
            continue
        info["monitors"].append({"x": x, "y": y, "width": width, "height": height})
    if info["monitors"]:
        primary = info["monitors"][0]
        info["bounds"] = {
            "x": primary["x"],
            "y": primary["y"],
            "width": primary["width"],
            "height": primary["height"],
        }
    return info


def _linux_screen() -> dict[str, Any]:
    """Geometria da tela no Linux, lida do `xrandr` (X11) ou dos portals (Wayland).

    Returns:
        Um dicionário com os limites da tela e o modo de captura disponível.
    """
    info: dict[str, Any] = {"system": "linux", "session": session_kind(), "bounds": None, "monitors": []}
    if session_kind() == "wayland":
        info["error"] = "Wayland não expõe a geometria da tela por linha de comando."
        info["hint"] = "use a automação por API (AT-SPI) ou capture a tela inteira sem recorte."
        info["capture_tool"] = "gnome-screenshot" if shutil.which("gnome-screenshot") else ""
        return info
    if not shutil.which("xrandr"):
        info["error"] = "xrandr ausente: a geometria da tela não pôde ser lida."
        return info
    completed = _run(["xrandr", "--current"], timeout=20)
    if completed.returncode != 0:
        info["error"] = (completed.stderr or "xrandr falhou").strip()[:400]
        return info
    for line in (completed.stdout or "").splitlines():
        match = re.match(r"^\S+\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)", line.strip())
        if not match:
            continue
        width, height, x, y = (int(value) for value in match.groups())
        info["monitors"].append({"x": x, "y": y, "width": width, "height": height})
    if info["monitors"]:
        first = info["monitors"][0]
        info["bounds"] = {
            "x": first["x"],
            "y": first["y"],
            "width": first["width"],
            "height": first["height"],
        }
    return info


def screen_info() -> dict[str, Any]:
    """Informa a geometria da tela e o que é possível fazer com ela.

    Returns:
        Um dicionário com os limites da tela, os monitores e as limitações conhecidas.
    """
    system = current_os()
    if system == "macos":
        info = _macos_screen()
    elif system == "windows":
        info = _windows_screen()
    else:
        info = _linux_screen()
    adapter = get_adapter()
    info.setdefault("capture_tool", adapter.screenshot_cmd[0] if adapter.screenshot_cmd else "")
    info["notes"] = list(adapter.notes)
    info["success"] = not info.get("error")
    return info


def _capture_target(path: str | None) -> str:
    """Resolve o caminho de destino da captura.

    Args:
        path: caminho pedido; `None` gera um arquivo temporário.

    Returns:
        O caminho absoluto do arquivo de destino.
    """
    if path:
        return os.path.abspath(os.path.expanduser(path))
    handle, generated = tempfile.mkstemp(prefix="callidus-shot-", suffix=".png")
    os.close(handle)
    return generated


def capture_screenshot(path: str | None = None, region: dict[str, int] | None = None) -> dict[str, Any]:
    """Captura a tela inteira ou uma região permitida.

    Args:
        path: arquivo de destino; `None` usa um arquivo temporário.
        region: região `{x, y, width, height}` em pixels da tela; `None` captura tudo.

    Returns:
        Um dicionário com o caminho da imagem e a confirmação do tamanho do arquivo.
    """
    target = _capture_target(path)
    adapter = get_adapter()
    system = current_os()
    if system == "macos":
        command = [*adapter.screenshot_cmd, target]
        if region:
            command += ["-R", f"{region['x']},{region['y']},{region['width']},{region['height']}"]
        completed = _run(command, timeout=30)
        if completed.returncode != 0:
            return {
                "success": False,
                "error": (completed.stderr or "screencapture falhou").strip()[:400],
                "hint": "conceda a permissão de Screen Recording ao processo do Callidus.",
            }
    elif system == "windows":
        environment = {**os.environ, "CALLIDUS_SHOT": target}
        try:
            completed = subprocess.run(
                [*adapter.screenshot_cmd],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "error": f"falha na captura: {exc}"}
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "captura falhou").strip()[:400]}
    else:
        tool = ""
        for candidate in ("gnome-screenshot", "scrot", "import"):
            if shutil.which(candidate):
                tool = candidate
                break
        if not tool:
            return {
                "success": False,
                "error": "nenhuma ferramenta de captura disponível",
                "hint": "instale gnome-screenshot, scrot ou ImageMagick.",
            }
        command = [tool, "-f", target] if tool != "import" else [tool, target]
        completed = _run(command, timeout=30)
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "captura falhou").strip()[:400]}
    if not os.path.exists(target):
        return {"success": False, "error": "a captura não gerou arquivo", "path": target}
    return {
        "success": True,
        "path": target,
        "bytes": os.path.getsize(target),
        "region": region,
        "system": system,
    }
