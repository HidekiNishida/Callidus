"""
Arquivo: src/agent/desktop/input.py
Nome: input.py
Propósito: injetar eventos de mouse e teclado na sessão gráfica do usuário.
Responsabilidade: camada de infraestrutura — cliques, digitação, teclas e rolagem por plataforma.
Componentes: click, double_click, move_pointer, press_key, type_text, scroll, drag.
Dependências: agent.desktop.capabilities, agent.system.adapters, subprocess.
Observações: as coordenadas são do momento da ação; a tela pode ter mudado desde a captura.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

from agent.desktop.capabilities import screen_info
from agent.system.adapters import current_os

#: Teclas que o AppleScript aceita por nome.
_OSA_KEYS = {
    "enter": "return",
    "return": "return",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "delete": "delete",
    "backspace": "delete",
    "up": "up arrow",
    "down": "down arrow",
    "left": "left arrow",
    "right": "right arrow",
    "home": "home",
    "end": "end",
    "pageup": "page up",
    "pagedown": "page down",
}


def _run(command: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
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


def _check_point(x: int, y: int) -> dict[str, Any] | None:
    """Confere se um ponto está dentro da tela conhecida.

    Args:
        x: coordenada horizontal.
        y: coordenada vertical.

    Returns:
        Um aviso quando a geometria é conhecida e o ponto está fora; `None` quando não há
        como afirmar nada.
    """
    info = screen_info()
    bounds = info.get("bounds")
    if not bounds:
        return None
    if bounds["x"] <= x < bounds["x"] + bounds["width"] and bounds["y"] <= y < bounds["y"] + bounds["height"]:
        return None
    return {
        "success": False,
        "error": f"ponto ({x}, {y}) fora da tela conhecida",
        "bounds": bounds,
    }


def _macos_click(x: int, y: int, *, double: bool = False, button: str = "left") -> dict[str, Any]:
    """Clica por coordenadas no macOS, via AppleScript do System Events.

    Args:
        x: coordenada horizontal.
        y: coordenada vertical.
        double: quando `True`, faz um clique duplo.
        button: botão do mouse (`left` ou `right`).

    Returns:
        O resultado da ação.
    """
    suffix = "double " if double else ""
    if button == "right":
        suffix = "right " if not suffix else "right " + suffix
    script = f'tell application "System Events" to {suffix}click at {{{x}, {y}}}'
    completed = _run(["osascript", "-e", script])
    if completed.returncode != 0:
        return {
            "success": False,
            "error": (completed.stderr or "osascript falhou").strip()[:300],
            "hint": "conceda a permissão de Accessibility ao processo do Callidus.",
        }
    return {"success": True, "x": x, "y": y, "double": double, "button": button}


def _windows_click(x: int, y: int, *, double: bool = False, button: str = "left") -> dict[str, Any]:
    """Clica por coordenadas no Windows, via `user32` do PowerShell.

    Args:
        x: coordenada horizontal.
        y: coordenada vertical.
        double: quando `True`, faz um clique duplo.
        button: botão do mouse (`left` ou `right`).

    Returns:
        O resultado da ação.
    """
    down = "0x0002" if button == "left" else "0x0008"
    up = "0x0004" if button == "left" else "0x0010"
    double_flag = "$true" if double else "$false"
    script = (
        "Add-Type -Namespace W -Name U -MemberDefinition "
        "'[DllImport(\"user32.dll\")] public static extern bool SetCursorPos(int X,int Y); "
        "[DllImport(\"user32.dll\")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,int e);'; "
        f"[W.U]::SetCursorPos({x},{y}) | Out-Null; "
        f"$d={double_flag}; "
        f"[W.U]::mouse_event({down},0,0,0,0); [W.U]::mouse_event({up},0,0,0,0); "
        "if ($d) { [W.U]::mouse_event(" + down + ",0,0,0,0); [W.U]::mouse_event(" + up + ",0,0,0,0); }"
    )
    completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "powershell falhou").strip()[:300]}
    return {"success": True, "x": x, "y": y, "double": double, "button": button}


def _linux_click(x: int, y: int, *, double: bool = False, button: str = "right") -> dict[str, Any]:
    """Clica por coordenadas no Linux, via `xdotool`.

    Args:
        x: coordenada horizontal.
        y: coordenada vertical.
        double: quando `True`, faz um clique duplo.
        button: botão do mouse.

    Returns:
        O resultado da ação.
    """
    if button == "right":
        completed = _run(["xdotool", "mousemove", str(x), str(y), "click", "3"])
    else:
        completed = _run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
    if completed.returncode != 0:
        return {
            "success": False,
            "error": (completed.stderr or "xdotool falhou").strip()[:300],
            "hint": "instale xdotool ou use automação por API (AT-SPI).",
        }
    if double:
        _run(["xdotool", "click", "--repeat", "2", "1"])
    return {"success": True, "x": x, "y": y, "double": double, "button": button}


def click(
    x: int,
    y: int,
    *,
    double: bool = False,
    button: str = "left",
) -> dict[str, Any]:
    """Clica em um ponto da tela.

    Args:
        x: coordenada horizontal, em pixels do monitor principal.
        y: coordenada vertical, em pixels do monitor principal.
        double: quando `True`, executa um clique duplo.
        button: `left` ou `right`.

    Returns:
        O resultado da ação; quando o ponto está fora da tela conhecida, o erro explica isso.
    """
    warning = _check_point(int(x), int(y))
    if warning:
        return warning
    system = current_os()
    if system == "macos":
        return _macos_click(int(x), int(y), double=double, button=button)
    if system == "windows":
        return _windows_click(int(x), int(y), double=double, button=button)
    return _linux_click(int(x), int(y), double=double, button=button)


def drag(x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
    """Arrasta o ponteiro de um ponto a outro.

    Args:
        x1: coordenada inicial horizontal.
        y1: coordenada inicial vertical.
        x2: coordenada final horizontal.
        y2: coordenada final vertical.

    Returns:
        O resultado da ação.
    """
    system = current_os()
    if system == "macos":
        script = (
            f'tell application "System Events" to drag {{1, 1}} to {{{x2}, {y2}}} '
            "using {{mouse down, mouse up}}"
        )
        completed = _run(["osascript", "-e", script])
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "osascript falhou").strip()[:300]}
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}
    if system == "windows":
        script = (
            "Add-Type -Namespace W -Name U -MemberDefinition "
            "'[DllImport(\"user32.dll\")] public static extern bool SetCursorPos(int X,int Y); "
            "[DllImport(\"user32.dll\")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,int e);'; "
            f"[W.U]::SetCursorPos({x1},{y1}) | Out-Null; Start-Sleep -Milliseconds 100; "
            "[W.U]::mouse_event(0x0002,0,0,0,0); Start-Sleep -Milliseconds 100; "
            f"[W.U]::SetCursorPos({x2},{y2}) | Out-Null; Start-Sleep -Milliseconds 100; "
            "[W.U]::mouse_event(0x0004,0,0,0,0);"
        )
        completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "powershell falhou").strip()[:300]}
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}
    completed = _run(["xdotool", "mousemove", str(x1), str(y1), "mousedown", "1", "mouseup", "1"])
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "xdotool falhou").strip()[:300]}
    return {"success": True, "from": [x1, y1], "to": [x2, y2]}


def press_key(key: str, *, repeat: int = 1) -> dict[str, Any]:
    """Pressiona uma tecla ou um atalho de teclado.

    Args:
        key: nome da tecla (`enter`, `tab`, `escape`, `f5`, ...) ou atalho
            no formato `cmd+s` / `ctrl+shift+p`.
        repeat: quantidade de repetições.

    Returns:
        O resultado da ação.
    """
    system = current_os()
    name = (key or "").strip()
    if not name:
        return {"success": False, "error": "informe a tecla"}
    if system == "macos":
        mapped = _OSA_KEYS.get(name.lower(), name)
        script = 'tell application "System Events" to key code 0'
        if "+" in name:
            parts = name.split("+")
            modifiers = {"cmd": "command down", "command": "command down", "ctrl": "control down", "control": "control down", "shift": "shift down", "alt": "option down", "option": "option down"}
            pressed = " & ".join(modifiers.get(part.lower(), "") for part in parts[:-1] if part.lower() in modifiers)
            last = parts[-1]
            mapped = _OSA_KEYS.get(last.lower(), last)
            if pressed:
                script = f'tell application "System Events" to keystroke "{mapped}" using {{{pressed}}}'
            else:
                script = f'tell application "System Events" to keystroke "{mapped}"'
        else:
            script = f'tell application "System Events" to keystroke "{mapped}"'
        completed = _run(["osascript", "-e", script])
        if completed.returncode != 0:
            return {
                "success": False,
                "error": (completed.stderr or "osascript falhou").strip()[:300],
                "hint": "conceda a permissão de Accessibility ao processo do Callidus.",
            }
        return {"success": True, "key": name}
    if system == "windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{_windows_keys(name)}');"
        )
        completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "powershell falhou").strip()[:300]}
        return {"success": True, "key": name}
    completed = _run(["xdotool", "key", "--clearmodifiers", name])
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "xdotool falhou").strip()[:300]}
    return {"success": True, "key": name}


def _windows_keys(name: str) -> str:
    """Converte um nome de tecla para a notação do SendKeys.

    Args:
        name: nome da tecla ou atalho (`ctrl+s`, `enter`, `f5`).

    Returns:
        A sequência equivalente no SendKeys.
    """
    mapping = {
        "enter": "{ENTER}",
        "return": "{ENTER}",
        "tab": "{TAB}",
        "escape": "{ESC}",
        "esc": "{ESC}",
        "space": " ",
        "backspace": "{BACKSPACE}",
        "delete": "{DELETE}",
        "up": "{UP}",
        "down": "{DOWN}",
        "left": "{LEFT}",
        "right": "{RIGHT}",
    }
    key = name.lower()
    if "+" in key:
        parts = key.split("+")
        modifiers = {"ctrl": "^", "control": "^", "shift": "+", "alt": "%", "cmd": "%"}
        prefix = "".join(modifiers.get(part, "") for part in parts[:-1])
        last = parts[-1]
        return f"{prefix}{mapping.get(last, last)}"
    return mapping.get(key, name)


def type_text(text: str, *, interval: float = 0.01) -> dict[str, Any]:
    """Digita um texto na janela em foco.

    Args:
        text: texto a digitar.
        interval: intervalo entre teclas, em segundos.

    Returns:
        O resultado da ação.
    """
    if text is None:
        return {"success": False, "error": "texto vazio"}
    system = current_os()
    if system == "macos":
        escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        completed = _run(["osascript", "-e", script])
        if completed.returncode != 0:
            return {
                "success": False,
                "error": (completed.stderr or "osascript falhou").strip()[:300],
                "hint": "conceda a permissão de Accessibility ao processo do Callidus.",
            }
        return {"success": True, "typed": len(text)}
    if system == "windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait({_ps_quote(str(text))});"
        )
        completed = _run(["powershell", "-NoProfile", "-Command", script], timeout=60)
        if completed.returncode != 0:
            return {"success": False, "error": (completed.stderr or "powershell falhou").strip()[:300]}
        return {"success": True, "typed": len(text)}
    completed = _run(["xdotool", "type", "--delay", str(int(interval * 1000)), "--", str(text)], timeout=60)
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "xdotool falhou").strip()[:300]}
    return {"success": True, "typed": len(text)}


def _ps_quote(value: str) -> str:
    """Cita um texto para uso dentro de um comando PowerShell.

    Args:
        value: texto a citar.

    Returns:
        O texto entre aspas simples do PowerShell, com as aspas internas duplicadas.
    """
    return "'" + value.replace("'", "''") + "'"


def scroll(amount: int, *, horizontal: bool = False) -> dict[str, Any]:
    """Rola a tela.

    Args:
        amount: quantidade de passos de rolagem; positivo rola para cima.
        horizontal: quando `True`, rola na horizontal.

    Returns:
        O resultado da ação.
    """
    system = current_os()
    steps = int(amount)
    if system == "macos":
        if horizontal:
            script = 'tell application "System Events" to key code 124 using {shift down}'
        else:
            script = 'tell application "System Events" to key code 125'
        for _ in range(max(1, abs(steps))):
            _run(["osascript", "-e", script])
            time.sleep(0.02)
        return {"success": True, "steps": steps, "horizontal": horizontal}
    if system == "windows":
        button = "h" if horizontal else "v"
        for _ in range(max(1, abs(steps))):
            _run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Windows.Forms; "
                        f"[System.Windows.Forms.SendKeys]::SendWait('{{{button}scrolldown}}');"
                    ),
                ],
                timeout=20,
            )
        return {"success": True, "steps": steps, "horizontal": horizontal}
    if horizontal:
        completed = _run(["xdotool", "click", "7"])
    else:
        completed = _run(["xdotool", "click", "4"])
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "xdotool falhou").strip()[:300]}
    return {"success": True, "steps": steps, "horizontal": horizontal}
