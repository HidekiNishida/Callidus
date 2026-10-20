"""
Arquivo: src/agent/automation/service/base.py
Nome: base.py
Propósito: definir o contrato dos adaptadores de inicialização nativa do runtime.
Responsabilidade: camada de infraestrutura — interface comum e apoio aos adaptadores por sistema operacional.
Componentes: ServiceOptions, ServiceStatus, ServiceAdapter, default_options.
Dependências: subprocess, shutil, pathlib.
Observações: a instalação por usuário é preferida; garantia em nível de sistema é informada com clareza.

Cada sistema operacional tem o seu jeito de iniciar um processo no arranque e de
recuperá-lo depois de uma falha. O **núcleo** do Callidus é o mesmo; o que muda fica
nestes adaptadores.

Todos os adaptadores:

- Preferem instalação por usuário (sem privilégio administrativo).
- Falam com o sistema por comandos do próprio sistema operacional (`launchctl`,
  `systemctl`, `schtasks`) — nada de biblioteca específica de plataforma.
- Informam com clareza quando uma garantia exige instalação em nível de sistema.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServiceOptions:
    """Como o serviço nativo deve chamar o runtime."""

    label: str = "callidus-supervisor"
    # Comando que roda o supervisor em primeiro plano.
    command: list[str] = field(default_factory=lambda: [sys.executable, "-m", "agent.automation.cli", "run"])
    working_dir: str = field(default_factory=lambda: str(Path.cwd()))
    # Arquivo de log do serviço (stdout/stderr).
    log_path: str = ""
    # `user` (sem privilégio) ou `system` (exige administrador).
    scope: str = "user"
    # Variáveis de ambiente passadas ao serviço.
    env: dict[str, str] = field(default_factory=dict)
    # Reiniciar automaticamente quando o processo morre.
    restart_on_failure: bool = True


@dataclass
class ServiceStatus:
    """Situação do serviço nativo."""

    installed: bool = False
    active: bool = False
    detail: str = ""
    platform: str = ""
    unit_path: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Situação do serviço como dicionário serializável.

        Returns:
            Um dicionário com os campos do status.
        """
        return {
            "installed": self.installed,
            "active": self.active,
            "detail": self.detail,
            "platform": self.platform,
            "unit_path": self.unit_path,
            "error": self.error,
        }


class ServiceAdapter:
    """Interface dos adaptadores de serviço."""

    platform_name: str = "desconhecido"

    def available(self) -> bool:
        """Este adaptador funciona nesta máquina?

        Returns:
            `True` quando o adaptador pode ser usado nesta plataforma.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        """Instala o serviço nativo.

        Args:
            options: opções de como o serviço deve chamar o runtime.

        Returns:
            O resultado da instalação.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    def uninstall(self) -> dict[str, Any]:
        """Remove o serviço nativo.

        Returns:
            O resultado da remoção.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    def start(self) -> dict[str, Any]:
        """Inicia o serviço.

        Returns:
            O resultado do início.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    def stop(self) -> dict[str, Any]:
        """Para o serviço.

        Returns:
            O resultado da parada.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    def status(self) -> ServiceStatus:
        """Situação do serviço.

        Returns:
            O status do serviço.

        Raises:
            NotImplementedError: quando o adaptador não foi implementado.
        """
        raise NotImplementedError

    # ── apoio ────────────────────────────────────────────────────────────

    def _run(self, args: list[str], *, timeout: float = 60.0) -> tuple[int, str, str]:
        """Executa um comando do sistema operacional.

        Args:
            args: comando e argumentos.
            timeout: tempo limite da execução, em segundos.

        Returns:
            Tupla com o código de saída, a saída padrão e a saída de erro.
        """
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def _which(self, executable: str) -> str | None:
        """Localiza um executável no `PATH`.

        Args:
            executable: nome do executável.

        Returns:
            O caminho absoluto, ou `None` quando ele não existe.
        """
        return shutil.which(executable)

    def _home(self) -> Path:
        """Pasta pessoal do usuário.

        Returns:
            O caminho da pasta pessoal.
        """
        return Path(os.path.expanduser("~"))


def default_options() -> ServiceOptions:
    """Opções padrão: executa o supervisor a partir do pacote instalado.

    Returns:
        As opções de serviço com o comando, a pasta de trabalho e o log já resolvidos.
    """
    settings_env: dict[str, str] = {}
    try:
        from agent.config import get_settings

        settings = get_settings()
        # `DATA_DIR` é a variável de ambiente do `Settings.data_dir`.
        settings_env["DATA_DIR"] = str(settings.data_dir)
    except Exception:  # noqa: BLE001 — sem config, o serviço usa o padrão do ambiente
        pass
    package_root = str(Path(__file__).resolve().parents[3])
    log_dir = Path(settings_env.get("DATA_DIR", "data"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path(os.getcwd())
    return ServiceOptions(
        command=[sys.executable, "-m", "agent.automation.cli", "run"],
        working_dir=package_root,
        log_path=str(log_dir / "supervisor.log"),
        env=settings_env,
    )
