"""
Arquivo: src/agent/system/adapters.py
Nome: adapters.py
Propósito: isolar as diferenças de sistema operacional na automação do sistema.
Responsabilidade: camada de infraestrutura — comandos nativos por plataforma e detecção do SO.
Componentes: SystemAdapter, MacAdapter, WindowsAdapter, LinuxAdapter, get_adapter, current_os.
Dependências: platform, shutil, subprocess.
Observações: cada adaptador só monta comandos; a execução e a leitura da saída ficam fora.
"""
from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field


def current_os() -> str:
    """Sistema operacional canônico do ambiente atual.

    Returns:
        `macos`, `windows` ou `linux` (o valor bruto quando não é um dos três).
    """
    system = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)


@dataclass
class SystemAdapter:
    """Comandos e capacidades de automação de uma plataforma.

    A classe base descreve o contrato comum; cada plataforma concreta preenche os
    campos que sabe executar. Um campo vazio significa "não suportado aqui" — a
    ferramenta informa a limitação em vez de fingir que funciona.

    Atributos:
        name: identificador da plataforma.
        list_processes_cmd: comando que lista processos em formato legível por linha.
        process_columns: quantidade de campos por linha na listagem.
        launch_cmd: comando que abre um aplicativo pelo nome.
        open_cmd: comando que abre arquivo, pasta ou URL.
        screenshot_cmd: comando que captura a tela.
        windows_cmd: comando que lista janelas ativas.
        input_cmd: comando que injeta entrada de mouse ou teclado.
        available_tools: executáveis que este adaptador sabe usar.
        notes: limitações conhecidas da plataforma.
    """

    name: str = "generic"
    list_processes_cmd: Sequence[str] = ()
    process_columns: int = 5
    launch_cmd: Sequence[str] = ()
    open_cmd: Sequence[str] = ()
    screenshot_cmd: Sequence[str] = ()
    windows_cmd: Sequence[str] = ()
    input_cmd: Sequence[str] = ()
    available_tools: Sequence[str] = ()
    notes: Sequence[str] = field(default_factory=tuple)

    def supports(self, binary: str) -> bool:
        """Indica se um executável usado por este adaptador está disponível.

        Args:
            binary: nome do executável.

        Returns:
            `True` quando o executável está no `PATH`.
        """
        return shutil.which(binary) is not None

    def missing_tools(self) -> list[str]:
        """Executáveis necessários e ausentes.

        Returns:
            A lista de executáveis que este adaptador usaria e que não estão instalados.
        """
        return [binary for binary in self.available_tools if not self.supports(binary)]


@dataclass
class MacAdapter(SystemAdapter):
    """Adaptador de macOS: `ps`, `open`, `osascript` e `screencapture`.

    Observações:
        A automação de interface depende das permissões de Acessibilidade e Gravação de
        Tela concedidas ao processo; a verificação é feita por `diagnose_permissions`.
    """

    name: str = "macos"
    list_processes_cmd: Sequence[str] = ("ps", "-axo", "pid=,ppid=,etime=,command=")
    process_columns: int = 4
    launch_cmd: Sequence[str] = ("open", "-a")
    open_cmd: Sequence[str] = ("open",)
    screenshot_cmd: Sequence[str] = ("screencapture", "-x")
    windows_cmd: Sequence[str] = ("osascript", "-e")
    available_tools: Sequence[str] = ("osascript", "screencapture")
    notes: Sequence[str] = (
        "A automação de interface exige Accessibility e Screen Recording para o processo.",
        "O TCC bloqueia silenciosamente: a falha aparece como 'not allowed' do osascript.",
    )


@dataclass
class WindowsAdapter(SystemAdapter):
    """Adaptador de Windows: PowerShell para processos e janelas, UIAutomation opcional.

    Observações:
        A sessão interativa é necessária; um serviço do Windows não tem desktop.
    """

    name: str = "windows"
    list_processes_cmd: Sequence[str] = (
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath | Format-Table -AutoSize",
    )
    process_columns: int = 4
    launch_cmd: Sequence[str] = ("cmd", "/c", "start", "")
    open_cmd: Sequence[str] = ("cmd", "/c", "start", "")
    screenshot_cmd: Sequence[str] = (
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
            "$bmp.Save($env:CALLIDUS_SHOT)"
        ),
    )
    windows_cmd: Sequence[str] = (
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object Id,ProcessName,MainWindowTitle | Format-Table -AutoSize",
    )
    available_tools: Sequence[str] = ("powershell",)
    notes: Sequence[str] = (
        "Precisa de sessão interativa: um serviço do Windows não tem desktop.",
        "UIAutomation exige PowerShell 5.1 ou superior.",
    )


@dataclass
class LinuxAdapter(SystemAdapter):
    """Adaptador de Linux: `ps`, `xdg-open` e ferramentas de sessão (X11/Wayland).

    Observações:
        X11 e Wayland não têm as mesmas capacidades; o Wayland não expõe posições de
        janela nem entrada global sem portais. As ferramentas opcionais são detectadas
        em tempo de uso.
    """

    name: str = "linux"
    list_processes_cmd: Sequence[str] = ("ps", "-eo", "pid=,ppid=,etimes=,args=")
    process_columns: int = 4
    launch_cmd: Sequence[str] = ()
    open_cmd: Sequence[str] = ("xdg-open",)
    screenshot_cmd: Sequence[str] = ("gnome-screenshot", "-f")
    windows_cmd: Sequence[str] = ("wmctrl", "-l")
    input_cmd: Sequence[str] = ("xdotool",)
    available_tools: Sequence[str] = ("xdg-open", "wmctrl", "xdotool", "gnome-screenshot")
    notes: Sequence[str] = (
        "Wayland não expõe lista de janelas nem entrada global sem portais (xdg-desktop-portal).",
        "Em X11 as ferramentas xdotool e wmctrl dão controle real de janela e teclado.",
        "Em Wayland prefira automação por API (AT-SPI, D-Bus) a coordenadas.",
    )


_ADAPTERS: dict[str, SystemAdapter] = {
    "macos": MacAdapter(),
    "windows": WindowsAdapter(),
    "linux": LinuxAdapter(),
}


def get_adapter(os_name: str | None = None) -> SystemAdapter:
    """Adaptador da plataforma.

    Args:
        os_name: plataforma desejada; `None` usa a do ambiente atual.

    Returns:
        O adaptador correspondente; o adaptador genérico quando a plataforma é desconhecida.
    """
    key = os_name or current_os()
    if key in _ADAPTERS:
        return _ADAPTERS[key]
    return SystemAdapter(name=key, notes=("Plataforma sem adaptador específico: recursos limitados.",))


def session_kind() -> str:
    """Natureza da sessão gráfica do ambiente atual.

    Returns:
        `wayland`, `x11`, `aqua` (macOS), `windows` (Windows) ou `headless`.
    """
    system = current_os()
    if system == "macos":
        return "aqua"
    if system == "windows":
        return "windows" if os.environ.get("SESSIONNAME", "") not in {"", "Services"} else "headless"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"
