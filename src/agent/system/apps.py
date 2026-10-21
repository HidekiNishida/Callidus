"""
Arquivo: src/agent/system/apps.py
Nome: apps.py
Propósito: descobrir aplicativos instalados e abrir aplicativos, arquivos, pastas e URLs.
Responsabilidade: camada de infraestrutura — catálogo de aplicativos e abertura de recursos do sistema.
Componentes: list_apps, find_app, launch_app, open_path, AppInfo.
Dependências: agent.system.adapters, agent.system.processes, pathlib, subprocess.
Observações: abrir nunca contorna permissões do sistema; a recusa do SO é repassada como erro.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.system.adapters import current_os, get_adapter
from agent.system.processes import ProcessManager, format_command

#: Pastas onde os aplicativos instalados costumam ficar, por plataforma.
_APP_DIRS: dict[str, tuple[str, ...]] = {
    "macos": ("/Applications", "/System/Applications", str(Path.home() / "Applications")),
    "linux": ("/usr/share/applications", "/usr/local/share/applications", str(Path.home() / ".local/share/applications")),
    "windows": (
        str(Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"),
        str(Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs"),
    ),
}


@dataclass(frozen=True)
class AppInfo:
    """Um aplicativo discovered no sistema.

    Atributos:
        name: nome legível do aplicativo.
        path: caminho do executável ou do atalho.
        bundle_id: identificador do pacote, quando conhecido (macOS).
    """

    name: str
    path: str
    bundle_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável do aplicativo.

        Returns:
            Um dicionário com `name`, `path` e `bundle_id`.
        """
        return {"name": self.name, "path": self.path, "bundle_id": self.bundle_id}


def _macos_apps() -> list[AppInfo]:
    """Descobre aplicativos do macOS lendo o `Info.plist` de cada bundle.

    Returns:
        A lista de aplicativos encontrados nas pastas de instalação.
    """
    found: list[AppInfo] = []
    for folder in _APP_DIRS.get("macos", ()):  # pragma: no branch - lista fixa
        base = Path(folder)
        if not base.is_dir():
            continue
        for bundle in sorted(base.glob("*.app")):
            info = bundle / "Contents" / "Info.plist"
            name = bundle.stem
            bundle_id = ""
            if info.is_file():
                try:
                    with info.open("rb") as handle:
                        data = plistlib.load(handle)
                    name = str(data.get("CFBundleDisplayName") or data.get("CFBundleName") or bundle.stem)
                    bundle_id = str(data.get("CFBundleIdentifier") or "")
                except (OSError, plistlib.InvalidFileException):
                    pass
            found.append(AppInfo(name=name, path=str(bundle), bundle_id=bundle_id))
    return found


def _linux_apps() -> list[AppInfo]:
    """Descobre aplicativos do Linux pelos arquivos `.desktop`.

    Returns:
        A lista de aplicativos encontrados nas pastas de menu.
    """
    found: list[AppInfo] = []
    for folder in _APP_DIRS.get("linux", ()):  # pragma: no branch - lista fixa
        base = Path(folder)
        if not base.is_dir():
            continue
        for entry in sorted(base.glob("*.desktop")):
            name = entry.stem
            try:
                for line in entry.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("Name="):
                        name = line.split("=", 1)[1].strip()
                        break
            except OSError:
                continue
            found.append(AppInfo(name=name, path=str(entry)))
    return found


def _windows_apps() -> list[AppInfo]:
    """Descobre aplicativos do Windows pelos atalhos do menu Iniciar.

    Returns:
        A lista de aplicativos encontrados.
    """
    found: list[AppInfo] = []
    for folder in _APP_DIRS.get("windows", ()):  # pragma: no branch - lista fixa
        base = Path(folder)
        if not base.is_dir():
            continue
        for entry in sorted(base.rglob("*.lnk")):
            found.append(AppInfo(name=entry.stem, path=str(entry)))
    return found


def list_apps(match: str | None = None, limit: int = 100) -> list[AppInfo]:
    """Descobre os aplicativos instalados no sistema.

    Args:
        match: filtro opcional por substring do nome (sem distinção de maiúsculas).
        limit: quantidade máxima de aplicativos devolvidos.

    Returns:
        A lista de aplicativos encontrados, ordenada por nome.
    """
    system = current_os()
    if system == "macos":
        apps = _macos_apps()
    elif system == "windows":
        apps = _windows_apps()
    else:
        apps = _linux_apps()
    if match:
        needle = match.lower()
        apps = [app for app in apps if needle in app.name.lower()]
    apps.sort(key=lambda app: app.name.lower())
    return apps[: max(1, int(limit))]


def find_app(name: str) -> AppInfo | None:
    """Procura um aplicativo pelo nome, exato ou parcial.

    Args:
        name: nome do aplicativo.

    Returns:
        O aplicativo encontrado, ou `None` quando não há correspondência.
    """
    needle = (name or "").strip().lower()
    if not needle:
        return None
    apps = list_apps(limit=5000)
    for app in apps:
        if app.name.lower() == needle:
            return app
    for app in apps:
        if needle in app.name.lower():
            return app
    return None


def _resolve_executable(name: str) -> str | None:
    """Localiza o executável de um aplicativo pelo `PATH`.

    Args:
        name: nome do executável.

    Returns:
        O caminho absoluto do executável, ou `None` quando ele não está no `PATH`.
    """
    if not name:
        return None
    return shutil.which(name)


def launch_app(
    name: str,
    *,
    args: Sequence[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    background: bool = False,
    manager: ProcessManager | None = None,
) -> dict[str, Any]:
    """Abre um aplicativo pelo nome, caminho ou executável disponível.

    A aplicação é iniciada de verdade: quando o mecanismo nativo não confirma o
    processo (o `open` do macOS desliga o processo pai), o agente recebe o caminho
    resolvido e a ordem de execução, para conferir por fora.

    Args:
        name: nome do aplicativo, caminho do bundle ou executável.
        args: argumentos passados ao aplicativo.
        cwd: diretório de trabalho.
        env: variáveis de ambiente adicionais.
        background: quando `True`, o processo é rastreado como tarefa em segundo plano.
        manager: gerenciador de processos, quando a tarefa for de segundo plano.

    Returns:
        Um dicionário com o modo de lançamento, o comando executado e o estado.
    """
    target = (name or "").strip()
    if not target:
        return {"success": False, "error": "informe o nome do aplicativo"}
    extra = [str(item) for item in (args or [])]
    adapter = get_adapter()
    system = current_os()

    if system == "macos":
        executable = _resolve_executable(target)
        if executable:
            command = [executable, *extra]
        else:
            app = find_app(target)
            if app is None and not Path(target).exists():
                return {
                    "success": False,
                    "error": f"aplicativo não encontrado: {target}",
                    "hint": "use list_apps para ver os aplicativos disponíveis.",
                }
            command = [*adapter.launch_cmd, target, *extra]
    elif system == "windows":
        executable = _resolve_executable(target)
        if executable:
            command = [executable, *extra]
        else:
            app = find_app(target)
            if app is None and not Path(target).exists():
                return {
                    "success": False,
                    "error": f"aplicativo não encontrado: {target}",
                    "hint": "use list_apps para ver os aplicativos disponíveis.",
                }
            command = [*adapter.launch_cmd, app.path if app else target, *extra]
    else:
        executable = _resolve_executable(target)
        if executable:
            command = [executable, *extra]
        else:
            app = find_app(target)
            if app is None:
                return {
                    "success": False,
                    "error": f"aplicativo não encontrado: {target}",
                    "hint": "use list_apps para ver os aplicativos disponíveis.",
                }
            command = [*adapter.open_cmd, app.path]

    if background:
        tracker = manager or ProcessManager()
        try:
            handle = tracker.start(command, cwd=cwd, env=env)
        except (OSError, ValueError) as exc:
            return {"success": False, "error": f"falha ao iniciar: {exc}", "command": format_command(command)}
        return {
            "success": True,
            "mode": "background",
            "app": target,
            "command": format_command(command),
            "handle": handle.as_dict(),
        }

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return {"success": False, "error": f"executável não encontrado: {command[0]}", "command": format_command(command)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"falha ao abrir: {exc}", "command": format_command(command)}
    return {
        "success": completed.returncode == 0,
        "mode": "foreground",
        "app": target,
        "command": format_command(command),
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "").strip()[:2000],
        "stderr": (completed.stderr or "").strip()[:2000],
    }


def open_path(path: str, *, manager: ProcessManager | None = None) -> dict[str, Any]:
    """Abre um arquivo, pasta ou URL com o manipulador padrão do sistema.

    Args:
        path: caminho absoluto, caminho relativo ou URL `http(s)`.
        manager: gerenciador de processos, quando o uso for em segundo plano.

    Returns:
        Um dicionário com o resultado da abertura.
    """
    target = (path or "").strip()
    if not target:
        return {"success": False, "error": "informe o caminho ou a URL"}
    adapter = get_adapter()
    if target.startswith(("http://", "https://")):
        command = [*adapter.open_cmd, target]
    else:
        resolved = Path(target).expanduser()
        if not resolved.exists():
            return {"success": False, "error": f"caminho inexistente: {target}"}
        command = [*adapter.open_cmd, str(resolved)]
    if not command:
        return {"success": False, "error": f"abertura de recursos não suportada em {adapter.name}"}
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"mecanismo de abertura ausente: {command[0]}",
            "hint": "instale o manipulador padrão do sistema ou use launch_app com o executável.",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"falha ao abrir: {exc}"}
    return {
        "success": completed.returncode == 0,
        "target": target,
        "command": format_command(command),
        "exit_code": completed.returncode,
        "stderr": (completed.stderr or "").strip()[:1000],
    }
