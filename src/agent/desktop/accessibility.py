"""
Arquivo: src/agent/desktop/accessibility.py
Nome: accessibility.py
Propósito: consultar a árvore de acessibilidade e agir sobre um elemento pelo nome.
Responsabilidade: camada de infraestrutura — automação semântica antes de coordenadas.
Componentes: list_elements, wait_for, click_named, parse_accessibility_text, match_elements, element_center.
Dependências: agent.desktop.input, agent.system.adapters, subprocess.
Observações: cada plataforma usa a API nativa disponível; a ausência vira diagnóstico, não sucesso falso.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import time
from typing import Any

from agent.desktop.input import click
from agent.system.adapters import current_os

_APP_NAME = re.compile(r"^[\w .+\-]{1,80}$")
_MAX_WAIT = 30.0


def parse_accessibility_text(text: str) -> dict[str, Any]:
    """Interpreta o texto estável devolvido pelos adaptadores de acessibilidade.

    Cada elemento ocupa uma linha `nome||papel||x||y||largura||altura`. A primeira linha
    pode ser `WINDOW|título|aplicativo`, `NOWINDOW|aplicativo`, `NOFOCUS` ou `NOMATCH`.

    Args:
        text: saída textual do adaptador.

    Returns:
        Um dicionário com a janela, o aplicativo e os elementos reconhecidos.
    """
    window = ""
    application = ""
    elements: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WINDOW|"):
            parts = line.split("|", 2)
            window = parts[1] if len(parts) > 1 else ""
            application = parts[2] if len(parts) > 2 else ""
            continue
        if line.startswith("NOWINDOW|"):
            return {
                "success": True,
                "mechanism": "accessibility",
                "window": "",
                "application": line.split("|", 1)[-1],
                "elements": [],
                "count": 0,
                "note": "o aplicativo não tem janela",
            }
        if line == "NOFOCUS":
            return {
                "success": False,
                "mechanism": "accessibility",
                "error": "nenhum elemento em foco",
                "elements": [],
                "count": 0,
            }
        if line == "NOMATCH":
            return {
                "success": False,
                "mechanism": "accessibility",
                "error": "o aplicativo informado não está em foco",
                "elements": [],
                "count": 0,
            }
        parts = line.split("||")
        if len(parts) < 2:
            continue
        bounds = _bounds(parts[2:6]) if len(parts) >= 6 else None
        elements.append({"name": parts[0], "role": parts[1], "bounds": bounds})
    return {
        "success": True,
        "mechanism": "accessibility",
        "window": window,
        "application": application,
        "elements": elements,
        "count": len(elements),
    }


def match_elements(elements: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Filtra elementos cujo nome contém o texto pedido.

    Args:
        elements: elementos já interpretados.
        name: trecho do nome, sem diferenciar maiúsculas.

    Returns:
        Os elementos que casam, na ordem recebida.
    """
    needle = (name or "").strip().lower()
    if not needle:
        return []
    return [item for item in elements if needle in str(item.get("name") or "").lower()]


def element_center(element: dict[str, Any]) -> tuple[int, int] | None:
    """Centro geométrico de um elemento, quando a árvore informa o retângulo.

    Args:
        element: elemento com `bounds`.

    Returns:
        O par `(x, y)`, ou `None` quando o retângulo é ausente ou vazio.
    """
    bounds = element.get("bounds") or {}
    try:
        width = int(bounds.get("width") or 0)
        height = int(bounds.get("height") or 0)
        x = int(bounds.get("x") or 0)
        y = int(bounds.get("y") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x + width // 2, y + height // 2)


def list_elements(app: str | None = None, *, limit: int = 40) -> dict[str, Any]:
    """Lista os elementos da janela em foco, ou do aplicativo pedido.

    A ordem de preferência é a da especificação: API de acessibilidade do sistema.
    Coordenadas só aparecem quando a árvore as fornece; elas não são a fonte da busca.

    Args:
        app: nome do aplicativo. Vazio usa a janela em foco.
        limit: quantidade máxima de elementos.

    Returns:
        Um dicionário com os elementos, ou o diagnóstico da plataforma.
    """
    cleaned = _clean_app(app)
    if isinstance(cleaned, dict):
        return cleaned
    bounded = max(1, min(int(limit or 40), 80))
    system = current_os()
    if system == "macos":
        return _from_command(_macos_script(cleaned, bounded), timeout=15)
    if system == "windows":
        return _from_command(["powershell", "-NoProfile", "-Command", _windows_script(cleaned, bounded)], timeout=25)
    return _linux_elements(cleaned, bounded)


def wait_for(
    *,
    title: str = "",
    name: str = "",
    timeout: float = 8.0,
    interval: float = 0.4,
) -> dict[str, Any]:
    """Espera uma janela pelo título ou um elemento pelo nome.

    A espera é limitada e cooperativa com o relógio: ao estourar, devolve tempo esgotado
    em vez de continuar. Não clica e não altera a interface.

    Args:
        title: trecho do título da janela.
        name: trecho do nome do elemento de acessibilidade.
        timeout: tempo máximo, em segundos (teto de 30).
        interval: pausa entre tentativas, em segundos.

    Returns:
        O que foi encontrado, ou o motivo do tempo esgotado.
    """
    title = (title or "").strip()
    name = (name or "").strip()
    if not title and not name:
        return {"success": False, "error": "informe title ou name"}
    deadline = time.monotonic() + max(0.05, min(float(timeout or 8), _MAX_WAIT))
    pause = max(0.05, float(interval or 0.4))
    last: dict[str, Any] = {}
    while True:
        if title:
            from agent.desktop.windows import list_windows

            found = list_windows(match=title, limit=10)
            last = found
            hits = found.get("windows") or []
            if hits:
                return {"success": True, "matched": "window", "windows": hits[:5], "count": len(hits)}
        if name:
            found = list_elements(limit=60)
            last = found
            hits = match_elements(found.get("elements") or [], name)
            if hits:
                return {"success": True, "matched": "element", "elements": hits[:8], "count": len(hits)}
        if time.monotonic() >= deadline:
            return {
                "success": False,
                "error": "tempo esgotado",
                "timeout_seconds": timeout,
                "last": {"error": last.get("error"), "count": last.get("count", 0)},
            }
        time.sleep(pause)


def click_named(name: str, *, app: str | None = None, button: str = "left") -> dict[str, Any]:
    """Clica no centro de um elemento localizado pelo nome na árvore de acessibilidade.

    A geometria é lida no momento do clique. Se o elemento não tiver retângulo, a função
    recusa a ação em vez de chutar uma coordenada antiga.

    Args:
        name: trecho do nome do elemento.
        app: aplicativo, quando não for a janela em foco.
        button: `left` ou `right`.

    Returns:
        O resultado do clique, com o elemento usado; ou o motivo da recusa.
    """
    if not (name or "").strip():
        return {"success": False, "error": "informe o nome do elemento"}
    found = list_elements(app=app, limit=80)
    if not found.get("success"):
        return found
    hits = match_elements(found.get("elements") or [], name)
    if not hits:
        return {
            "success": False,
            "error": f"elemento não encontrado: {name}",
            "window": found.get("window"),
            "count": found.get("count", 0),
        }
    target = hits[0]
    center = element_center(target)
    if center is None:
        return {
            "success": False,
            "error": "o elemento não tem geometria; reavalie a tela antes de usar coordenadas",
            "element": {"name": target.get("name"), "role": target.get("role")},
        }
    result = click(center[0], center[1], button=button)
    result["mechanism"] = "accessibility"
    result["element"] = {"name": target.get("name"), "role": target.get("role"), "bounds": target.get("bounds")}
    return result


def _bounds(parts: list[str]) -> dict[str, int] | None:
    """Converte quatro números textuais em um retângulo.

    Args:
        parts: `x`, `y`, largura e altura, como texto.

    Returns:
        O retângulo, ou `None` quando algum número é ilegível.
    """
    try:
        x, y, width, height = (int(float(part)) for part in parts[:4])
    except (TypeError, ValueError):
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _clean_app(app: str | None) -> str | None | dict[str, Any]:
    """Normaliza o nome do aplicativo ou devolve o erro de formato.

    Args:
        app: nome informado pelo chamador.

    Returns:
        O nome limpo, `None` quando vazio, ou um dicionário de erro.
    """
    text = (app or "").strip()
    if not text:
        return None
    if not _APP_NAME.match(text):
        return {"success": False, "error": "nome de aplicativo inválido", "elements": [], "count": 0}
    return text


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Executa o comando nativo da plataforma.

    Args:
        command: comando e argumentos.
        timeout: tempo limite, em segundos.

    Returns:
        O processo concluído; em falha de sistema, um resultado sintético com código 127.
    """
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def _from_command(command: list[str], *, timeout: float) -> dict[str, Any]:
    """Roda o adaptador e interpreta a saída.

    Args:
        command: comando do adaptador.
        timeout: tempo limite, em segundos.

    Returns:
        Os elementos, ou o erro do sistema com a dica de permissão.
    """
    completed = _run(command, timeout)
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "falha ao ler a acessibilidade").strip()[:400]
        hint = ""
        lowered = error.lower()
        if any(
            token in lowered
            for token in ("not allowed", "assistive", "appleevent", "-10000", "-1719", "-25211", "não é permitido")
        ):
            hint = (
                "conceda Automação e Accessibility ao processo do Callidus em "
                "Ajustes do Sistema > Privacidade e Segurança."
            )
        return {
            "success": False,
            "mechanism": "accessibility",
            "error": error or "falha ao ler a acessibilidade",
            "hint": hint,
            "elements": [],
            "count": 0,
        }
    parsed = parse_accessibility_text(completed.stdout or "")
    parsed["mechanism"] = "accessibility"
    return parsed


def _macos_script(app: str | None, limit: int) -> list[str]:
    """AppleScript que lista os elementos da primeira janela.

    Args:
        app: aplicativo; vazio usa o processo em primeiro plano.
        limit: quantidade máxima de elementos.

    Returns:
        O comando `osascript`.
    """
    if app:
        choose = f'set targetName to "{app}"'
    else:
        choose = "set targetName to name of first application process whose frontmost is true"
    script = f'''
tell application "System Events"
  {choose}
  if not (exists process targetName) then
    return "NOMATCH"
  end if
  tell process targetName
    if (count of windows) is 0 then
      return "NOWINDOW|" & targetName
    end if
    set winName to ""
    try
      set winName to name of window 1 as text
    end try
    set outLines to "WINDOW|" & winName & "|" & targetName
    set i to 0
    repeat with el in UI elements of window 1
      set i to i + 1
      if i > {int(limit)} then exit repeat
      set n to ""
      set r to ""
      set x to 0
      set y to 0
      set w to 0
      set h to 0
      try
        set n to name of el as text
      end try
      try
        set r to role of el as text
      end try
      try
        set pos to position of el
        set x to item 1 of pos
        set y to item 2 of pos
        set sz to size of el
        set w to item 1 of sz
        set h to item 2 of sz
      end try
      set outLines to outLines & linefeed & n & "||" & r & "||" & x & "||" & y & "||" & w & "||" & h
    end repeat
    return outLines
  end tell
end tell
'''
    return ["osascript", "-e", script]


def _windows_script(app: str | None, limit: int) -> str:
    """PowerShell que lista os filhos da janela em foco via UI Automation.

    Args:
        app: filtro opcional pelo nome do processo.
        limit: quantidade máxima de elementos.

    Returns:
        O script PowerShell.
    """
    escaped = (app or "").replace("'", "''")
    return f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$focused = [System.Windows.Automation.AutomationElement]::FocusedElement
if (-not $focused) {{ Write-Output 'NOFOCUS'; exit 0 }}
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$window = $focused
while ($window) {{
  $kind = $window.Current.ControlType.ProgrammaticName
  if ($kind -eq 'ControlType.Window') {{ break }}
  $parent = $walker.GetParent($window)
  if (-not $parent) {{ break }}
  $window = $parent
}}
$procId = $window.Current.ProcessId
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
$wanted = '{escaped}'
if ($wanted -and $proc -and ($proc.ProcessName -notlike ('*' + $wanted + '*'))) {{ Write-Output 'NOMATCH'; exit 0 }}
$winName = $window.Current.Name
$procName = if ($proc) {{ $proc.ProcessName }} else {{ '' }}
Write-Output ('WINDOW|' + $winName + '|' + $procName)
$child = $walker.GetFirstChild($window)
$i = 0
while ($child -and $i -lt {int(limit)}) {{
  $i++
  $n = $child.Current.Name
  $r = $child.Current.ControlType.ProgrammaticName
  $b = $child.Current.BoundingRectangle
  Write-Output ($n + '||' + $r + '||' + [int]$b.X + '||' + [int]$b.Y + '||' + [int]$b.Width + '||' + [int]$b.Height)
  $child = $walker.GetNextSibling($child)
}}
"""


def _linux_elements(app: str | None, limit: int) -> dict[str, Any]:
    """Lista elementos via AT-SPI quando o módulo `pyatspi` está instalado.

    Args:
        app: filtro opcional pelo nome do aplicativo.
        limit: quantidade máxima de elementos.

    Returns:
        Os elementos, ou o diagnóstico de dependência ausente.
    """
    if importlib.util.find_spec("pyatspi") is None:
        return {
            "success": False,
            "available": False,
            "mechanism": "accessibility",
            "error": "AT-SPI indisponível: o módulo pyatspi não está instalado.",
            "hint": "Instale python3-pyatspi na sessão gráfica. No Wayland, portais não expõem a mesma árvore que o X11.",
            "elements": [],
            "count": 0,
        }
    try:
        import pyatspi
    except Exception as exc:
        return {
            "success": False,
            "mechanism": "accessibility",
            "error": f"não foi possível carregar o AT-SPI: {exc}",
            "elements": [],
            "count": 0,
        }
    try:
        desktop = pyatspi.Registry.getDesktop(0)
    except Exception as exc:
        return {
            "success": False,
            "mechanism": "accessibility",
            "error": f"sessão AT-SPI indisponível: {exc}",
            "hint": "confira se o barramento de acessibilidade está ativo nesta sessão.",
            "elements": [],
            "count": 0,
        }
    elements: list[dict[str, Any]] = []
    application = ""
    window = ""
    wanted = (app or "").lower()
    for index in range(getattr(desktop, "childCount", 0)):
        application_node = desktop.getChildAtIndex(index)
        application_name = str(getattr(application_node, "name", "") or "")
        if wanted and wanted not in application_name.lower():
            continue
        application = application_name
        for child_index in range(getattr(application_node, "childCount", 0)):
            child = application_node.getChildAtIndex(child_index)
            if not window:
                window = str(getattr(child, "name", "") or "")
            elements.append(
                {
                    "name": str(getattr(child, "name", "") or ""),
                    "role": str(getattr(child, "getRoleName", lambda: "")() or ""),
                    "bounds": None,
                }
            )
            if len(elements) >= limit:
                break
        if len(elements) >= limit:
            break
    return {
        "success": True,
        "mechanism": "accessibility",
        "window": window,
        "application": application,
        "elements": elements,
        "count": len(elements),
    }
