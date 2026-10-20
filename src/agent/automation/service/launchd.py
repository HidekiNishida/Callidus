# src/agent/automation/service/launchd.py — adaptador macOS (launchd)
"""macOS: agente de usuário em `launchd`.

`launchd` já é o supervisor nativo do macOS: reinicia o processo quando ele morre e
sobe no login do usuário. A instalação é por usuário (`~/Library/LaunchAgents`), sem
privilégio administrativo — a garantia de "iniciar depois de reiniciar a máquina"
depende do usuário ter feito login.
"""
from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

from agent.automation.service.base import ServiceAdapter, ServiceOptions, ServiceStatus

BUNDLE_ID = "com.callidus.supervisor"


class LaunchdAdapter(ServiceAdapter):
    platform_name = "macos"

    def _plist_path(self, label: str = BUNDLE_ID) -> Path:
        return self._home() / "Library" / "LaunchAgents" / f"{label}.plist"

    def available(self) -> bool:
        import sys

        return sys.platform == "darwin" and self._which("launchctl") is not None

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        if not self.available():
            return {"installed": False, "error": "launchd não está disponível nesta máquina"}
        path = self._plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "Label": BUNDLE_ID,
            "ProgramArguments": list(options.command),
            "RunAtLoad": True,
            "WorkingDirectory": options.working_dir,
            "StandardOutPath": options.log_path or "/tmp/callidus-supervisor.log",
            "StandardErrorPath": options.log_path or "/tmp/callidus-supervisor.err.log",
            "EnvironmentVariables": dict(options.env),
            "ProcessType": "Background",
        }
        if options.restart_on_failure:
            payload["KeepAlive"] = True
        with path.open("wb") as handle:
            plistlib.dump(payload, handle)
        code, out, err = self._run(["launchctl", "unload", str(path)], timeout=30)
        loaded = self._run(["launchctl", "load", "-w", str(path)], timeout=30)
        return {
            "installed": True,
            "path": str(path),
            "platform": self.platform_name,
            "loaded": loaded[0] == 0,
            "detail": loaded[1] or loaded[2],
            "previous_unload": err if code != 0 else "",
        }

    def uninstall(self) -> dict[str, Any]:
        path = self._plist_path()
        if path.exists():
            self._run(["launchctl", "unload", "-w", str(path)], timeout=30)
            path.unlink()
            return {"removed": True, "path": str(path)}
        return {"removed": False, "path": str(path)}

    def start(self) -> dict[str, Any]:
        path = self._plist_path()
        if not path.exists():
            return {"started": False, "error": "serviço não instalado"}
        code, out, err = self._run(["launchctl", "start", BUNDLE_ID], timeout=30)
        return {"started": code == 0, "detail": out or err}

    def stop(self) -> dict[str, Any]:
        code, out, err = self._run(["launchctl", "stop", BUNDLE_ID], timeout=30)
        return {"stopped": code == 0, "detail": out or err}

    def status(self) -> ServiceStatus:
        path = self._plist_path()
        installed = path.exists()
        code, out, err = self._run(["launchctl", "list", BUNDLE_ID], timeout=30)
        active = code == 0 and "PID" in out
        return ServiceStatus(
            installed=installed,
            active=active,
            detail=out or err,
            platform=self.platform_name,
            unit_path=str(path),
        )
