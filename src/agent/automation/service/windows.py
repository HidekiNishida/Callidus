"""
Arquivo: src/agent/automation/service/windows.py
Nome: windows.py
Propósito: instalar e controlar o runtime como tarefa do Agendador de Tarefas do Windows.
Responsabilidade: camada de infraestrutura — instalação, início, parada e status da tarefa agendada.
Componentes: WindowsTaskAdapter, TASK_NAME.
Dependências: agent.automation.service.base.
Observações: a instalação por usuário é o padrão; a tarefa de sistema exige administrador.

Windows: tarefa agendada no Agendador de Tarefas do Windows.

Duas modalities, com a mesma ressalva do Linux:

- **usuário** (`/SC ONLOGON`): não exige administrador; o serviço sobe quando o
  usuário entra na máquina. É o padrão.
- **sistema** (`/SC ONSTART`): exige administrador e sobe no boot, sem login.

O Agendador de Tarefas é nativo do Windows: reinicia a tarefa quando ela falha
(`/RI`/configuração de reinício via XML) e o Callidus registra o próprio processo
em arquivo de log.
"""
from __future__ import annotations

import os
from typing import Any

from agent.automation.service.base import ServiceAdapter, ServiceOptions, ServiceStatus

TASK_NAME = "CallidusSupervisor"


class WindowsTaskAdapter(ServiceAdapter):
    """Adaptador do Agendador de Tarefas (Windows).

    Atributos:
        platform_name: nome da plataforma servida por este adaptador.
    """

    platform_name = "windows"

    def available(self) -> bool:
        """Indica se o Agendador de Tarefas pode ser usado nesta máquina.

        Returns:
            `True` quando a plataforma é Windows e o `schtasks` existe.
        """
        return os.name == "nt" and self._which("schtasks") is not None

    def _task_name(self) -> str:
        """Nome da tarefa agendada.

        Returns:
            O nome registrado no Agendador de Tarefas.
        """
        return TASK_NAME

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        """Cria a tarefa agendada, no escopo de usuário ou de sistema.

        Args:
            options: opções de como o serviço deve chamar o runtime.

        Returns:
            O resultado da instalação, com o escopo, o nome da tarefa e a programação.
        """
        if not self.available():
            return {"installed": False, "error": "Agendador de Tarefas não está disponível"}
        scope = options.scope if options.scope in {"user", "system"} else "user"
        if scope == "system" and not self._is_admin():
            return {
                "installed": False,
                "error": "tarefa em nível de sistema exige privilégio administrativo",
                "hint": "use --scope user para instalar sem privilégios",
            }
        schedule = "ONSTART" if scope == "system" else "ONLOGON"
        args = [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            self._task_name(),
            "/TR",
            " ".join(options.command),
            "/SC",
            schedule,
        ]
        if scope == "user":
            args += ["/RL", "LIMITED"]
        code, out, err = self._run(args, timeout=90)
        if code != 0:
            return {"installed": False, "error": err or out}
        return {
            "installed": True,
            "scope": scope,
            "task_name": self._task_name(),
            "platform": self.platform_name,
            "schedule": schedule,
            "detail": out,
        }

    def uninstall(self) -> dict[str, Any]:
        """Apaga a tarefa agendada.

        Returns:
            O resultado da remoção.
        """
        code, out, err = self._run(["schtasks", "/Delete", "/F", "/TN", self._task_name()], timeout=60)
        return {"removed": code == 0, "detail": out or err}

    def start(self) -> dict[str, Any]:
        """Executa a tarefa agendada agora.

        Returns:
            O resultado do início.
        """
        code, out, err = self._run(["schtasks", "/Run", "/TN", self._task_name()], timeout=60)
        return {"started": code == 0, "detail": out or err}

    def stop(self) -> dict[str, Any]:
        """Interrompe a execução da tarefa agendada.

        Returns:
            O resultado da parada.
        """
        code, out, err = self._run(["schtasks", "/End", "/TN", self._task_name()], timeout=60)
        return {"stopped": code == 0, "detail": out or err}

    def status(self) -> ServiceStatus:
        """Situação da tarefa agendada.

        Returns:
            O status do serviço, com o nome da tarefa.
        """
        code, out, err = self._run(["schtasks", "/Query", "/TN", self._task_name()], timeout=60)
        installed = code == 0
        active = "Running" in out
        return ServiceStatus(
            installed=installed,
            active=active,
            detail=out or err,
            platform=self.platform_name,
            unit_path=self._task_name(),
        )

    def _is_admin(self) -> bool:
        """Indica se o processo roda com privilégio administrativo.

        Returns:
            `True` quando o usuário é administrador do Windows.
        """
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False
