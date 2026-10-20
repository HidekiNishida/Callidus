"""
Arquivo: src/agent/automation/service/systemd.py
Nome: systemd.py
Propósito: instalar e controlar o runtime como unidade do `systemd` no Linux.
Responsabilidade: camada de infraestrutura — instalação por usuário ou de sistema, início, parada e status.
Componentes: SystemdAdapter, UNIT_NAME.
Dependências: agent.automation.service.base.
Observações: a diferença entre os escopos é do sistema operacional; instalação de sistema exige administrador.

Linux: unidade do `systemd`.

Dois escopos, com diferenças reais:

- **usuário** (`systemctl --user`, `~/.config/systemd/user/`): não exige privilégio
  administrativo; o serviço sobe no login do usuário e é reiniciado quando falha.
- **sistema** (`/etc/systemd/system/`): exige administrador e sobe no boot da
  máquina, mesmo sem login. Quem instala em nível de sistema assume essa
  responsabilidade — o instalador avisa e pede confirmação.

A diferença entre os dois é do sistema operacional, não do núcleo do Callidus.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.automation.service.base import ServiceAdapter, ServiceOptions, ServiceStatus

UNIT_NAME = "callidus-supervisor.service"


class SystemdAdapter(ServiceAdapter):
    """Adaptador do `systemd` (Linux).

    Atributos:
        platform_name: nome da plataforma servida por este adaptador.
    """

    platform_name = "linux"

    def _user_unit_path(self) -> Path:
        """Caminho da unidade de usuário.

        Returns:
            O caminho do arquivo em `~/.config/systemd/user`.
        """
        return self._home() / ".config" / "systemd" / "user" / UNIT_NAME

    def _system_unit_path(self) -> Path:
        """Caminho da unidade de sistema.

        Returns:
            O caminho do arquivo em `/etc/systemd/system`.
        """
        return Path("/etc/systemd/system") / UNIT_NAME

    def _unit_path(self, scope: str = "user") -> Path:
        """Caminho da unidade conforme o escopo.

        Args:
            scope: `user` ou `system`.

        Returns:
            O caminho do arquivo da unidade.
        """
        return self._system_unit_path() if scope == "system" else self._user_unit_path()

    def _ctl(self, args: list[str], scope: str) -> tuple[int, str, str]:
        """Chama o `systemctl` no escopo pedido.

        Args:
            args: argumentos do `systemctl`.
            scope: `user` ou `system`.

        Returns:
            Tupla com o código de saída, a saída padrão e a saída de erro.
        """
        if scope == "system":
            return self._run(["sudo", "systemctl", *args], timeout=90)
        return self._run(["systemctl", "--user", *args], timeout=90)

    def available(self) -> bool:
        """Indica se o `systemd` pode ser usado nesta máquina.

        Returns:
            `True` quando a plataforma é Linux e o `systemctl` existe.
        """
        import sys

        return sys.platform.startswith("linux") and self._which("systemctl") is not None

    def _unit_content(self, options: ServiceOptions) -> str:
        """Conteúdo do arquivo de unidade.

        Args:
            options: opções de como o serviço deve chamar o runtime.

        Returns:
            O texto da unidade, pronto para ser gravado.
        """
        env_lines = "\n".join(f"Environment={k}={v}" for k, v in sorted(options.env.items()))
        exec_line = " ".join(options.command)
        restart = "always" if options.restart_on_failure else "no"
        return f"""[Unit]
Description=Callidus — supervisor de automações
After=network.target

[Service]
Type=simple
ExecStart={exec_line}
WorkingDirectory={options.working_dir}
Restart={restart}
RestartSec=5
{env_lines}

[Install]
WantedBy={'multi-user.target' if options.scope == 'system' else 'default.target'}
"""

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        """Grava a unidade, recarrega o `systemd` e habilita o serviço.

        Args:
            options: opções de como o serviço deve chamar o runtime.

        Returns:
            O resultado da instalação, com o escopo, o caminho e o estado do serviço.
        """
        if not self.available():
            return {"installed": False, "error": "systemd não está disponível nesta máquina"}
        scope = options.scope if options.scope in {"user", "system"} else "user"
        path = self._unit_path(scope)
        if scope == "system" and os.geteuid() != 0:
            return {
                "installed": False,
                "error": "instalação em nível de sistema exige privilégio administrativo (sudo)",
                "hint": "use --scope user para instalar sem privilégios",
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._unit_content(options), encoding="utf-8")
        self._ctl(["daemon-reload"], scope)
        enable = self._ctl(["enable", UNIT_NAME], scope)
        start = self._ctl(["restart", UNIT_NAME], scope)
        return {
            "installed": True,
            "scope": scope,
            "path": str(path),
            "platform": self.platform_name,
            "enabled": enable[0] == 0,
            "started": start[0] == 0,
            "detail": start[1] or start[2],
        }

    def uninstall(self) -> dict[str, Any]:
        """Para, desabilita e apaga a unidade nos dois escopos.

        Returns:
            O resultado da remoção, com os caminhos afetados.
        """
        removed: list[str] = []
        for scope in ("user", "system"):
            path = self._unit_path(scope)
            if path.exists():
                self._ctl(["stop", UNIT_NAME], scope)
                self._ctl(["disable", UNIT_NAME], scope)
                try:
                    path.unlink()
                    removed.append(str(path))
                except OSError as exc:
                    return {"removed": False, "error": str(exc)}
        self._ctl(["daemon-reload"], "user")
        return {"removed": bool(removed), "paths": removed}

    def start(self) -> dict[str, Any]:
        """Inicia o serviço de usuário.

        Returns:
            O resultado do início.
        """
        code, out, err = self._ctl(["start", UNIT_NAME], "user")
        return {"started": code == 0, "detail": out or err}

    def stop(self) -> dict[str, Any]:
        """Para o serviço de usuário.

        Returns:
            O resultado da parada.
        """
        code, out, err = self._ctl(["stop", UNIT_NAME], "user")
        return {"stopped": code == 0, "detail": out or err}

    def status(self) -> ServiceStatus:
        """Situação do serviço, consultando o escopo de usuário e o de sistema.

        Returns:
            O status do serviço, com o caminho da unidade encontrada.
        """
        user_path = self._user_unit_path()
        system_path = self._system_unit_path()
        installed = user_path.exists() or system_path.exists()
        code, out, err = self._ctl(["is-active", UNIT_NAME], "user")
        active = out.strip() == "active"
        detail = out.strip() or err.strip()
        if not active and system_path.exists():
            code2, out2, err2 = self._ctl(["is-active", UNIT_NAME], "system")
            active = out2.strip() == "active"
            detail = out2.strip() or err2.strip()
        return ServiceStatus(
            installed=installed,
            active=active,
            detail=detail,
            platform=self.platform_name,
            unit_path=str(user_path if user_path.exists() else system_path),
        )
