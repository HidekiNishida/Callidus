"""
Arquivo: src/agent/automation/service/launchd.py
Nome: launchd.py
Propósito: instalar e controlar o runtime como agente de usuário do `launchd` no macOS.
Responsabilidade: camada de infraestrutura — instalação, início, parada e status do serviço nativo.
Componentes: LaunchdAdapter, BUNDLE_ID.
Dependências: agent.automation.service.base, plistlib.
Observações: a instalação é por usuário, sem privilégio administrativo; subir após reiniciar depende do login.

macOS: agente de usuário em `launchd`.

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
    """Adaptador do `launchd` (macOS).

    Atributos:
        platform_name: nome da plataforma servida por este adaptador.
    """

    platform_name = "macos"

    def _plist_path(self, label: str = BUNDLE_ID) -> Path:
        """Caminho do arquivo `plist` do agente.

        Args:
            label: rótulo do serviço.

        Returns:
            O caminho do arquivo dentro de `~/Library/LaunchAgents`.
        """
        return self._home() / "Library" / "LaunchAgents" / f"{label}.plist"

    def available(self) -> bool:
        """Indica se o `launchd` pode ser usado nesta máquina.

        Returns:
            `True` quando a plataforma é macOS e o `launchctl` existe.
        """
        import sys

        return sys.platform == "darwin" and self._which("launchctl") is not None

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        """Grava o `plist` e carrega o agente no `launchd`.

        Args:
            options: opções de como o serviço deve chamar o runtime.

        Returns:
            O resultado da instalação, com o caminho do `plist` e o estado do carregamento.
        """
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
        """Descarrega o agente e apaga o `plist`.

        Returns:
            O resultado da remoção, com o caminho afetado.
        """
        path = self._plist_path()
        if path.exists():
            self._run(["launchctl", "unload", "-w", str(path)], timeout=30)
            path.unlink()
            return {"removed": True, "path": str(path)}
        return {"removed": False, "path": str(path)}

    def start(self) -> dict[str, Any]:
        """Inicia o agente do `launchd`.

        Returns:
            O resultado do início.
        """
        path = self._plist_path()
        if not path.exists():
            return {"started": False, "error": "serviço não instalado"}
        code, out, err = self._run(["launchctl", "start", BUNDLE_ID], timeout=30)
        return {"started": code == 0, "detail": out or err}

    def stop(self) -> dict[str, Any]:
        """Para o agente do `launchd`.

        Returns:
            O resultado da parada.
        """
        code, out, err = self._run(["launchctl", "stop", BUNDLE_ID], timeout=30)
        return {"stopped": code == 0, "detail": out or err}

    def status(self) -> ServiceStatus:
        """Situação do agente do `launchd`.

        Returns:
            O status do serviço, com o caminho do `plist`.
        """
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
