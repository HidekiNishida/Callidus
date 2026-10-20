# src/agent/automation/service/base.py — contrato dos adaptadores de inicialização nativa
"""Cada sistema operacional tem o seu jeito de iniciar um processo no arranque e de
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
        """Este adaptador funciona nesta máquina?"""
        raise NotImplementedError

    def install(self, options: ServiceOptions) -> dict[str, Any]:
        raise NotImplementedError

    def uninstall(self) -> dict[str, Any]:
        raise NotImplementedError

    def start(self) -> dict[str, Any]:
        raise NotImplementedError

    def stop(self) -> dict[str, Any]:
        raise NotImplementedError

    def status(self) -> ServiceStatus:
        raise NotImplementedError

    # ── apoio ────────────────────────────────────────────────────────────

    def _run(self, args: list[str], *, timeout: float = 60.0) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def _which(self, executable: str) -> str | None:
        return shutil.which(executable)

    def _home(self) -> Path:
        return Path(os.path.expanduser("~"))


def default_options() -> ServiceOptions:
    """Opções padrão: executa o supervisor a partir do pacote instalado."""
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
