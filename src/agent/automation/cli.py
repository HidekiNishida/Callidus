"""
Arquivo: src/agent/automation/cli.py
Nome: cli.py
Propósito: expor o runtime de automações como linha de comando.
Responsabilidade: camada de apresentação — comandos de execução e de gestão do serviço nativo.
Componentes: cmd_run, cmd_install, cmd_uninstall, cmd_start, cmd_stop, cmd_status, cmd_diagnose, cmd_list, build_parser, main.
Dependências: agent.automation.service, agent.automation.supervisor, agent.automation.store.
Observações: `run` também sobe o worker autônomo; sem ele, um run registrado nunca executa.

O mesmo núcleo que a API usa, exposto como comando.

    callidus-supervisor run          # primeiro plano (é o que o serviço nativo executa)
    callidus-supervisor install      # instala o serviço nativo do sistema operacional
    callidus-supervisor status       # situação do runtime e do serviço
    callidus-supervisor diagnose     # detalhe: automações, disparos pendentes, dependências
    callidus-supervisor uninstall    # remove o serviço nativo

`run` também sobe o worker autônomo: sem ele, uma automação que cria um trabalho
Callidus ficaria com o run registrado e nunca executado.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from agent.automation.service import (
    adapters_status,
    current_adapter,
    default_options,
)
from agent.automation.supervisor import build_supervisor

logger = logging.getLogger("callidus.automation")


def _print(payload: Any) -> None:
    """Imprime um payload em JSON.

    Args:
        payload: conteúdo a exibir.
    """
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


# ─────────────────────────────────────────────────────────── run

async def _run_forever(settings, interval: float) -> None:
    """Roda o supervisor e o worker autônomo até receber um sinal de parada.

    Args:
        settings: configurações do processo.
        interval: segundos entre tiques do supervisor.
    """
    from agent.services.autonomous_worker import autonomous_loop

    supervisor = build_supervisor(settings)
    worker = asyncio.create_task(autonomous_loop())
    stop = asyncio.Event()

    def _request_stop(*_args: Any) -> None:
        """Envia o pedido de parada do supervisor e devolve a resposta do comando."""
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):  # pragma: no cover — Windows
            pass

    try:
        await supervisor.run_forever(interval_sec=interval)
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


def cmd_run(args: argparse.Namespace) -> int:
    """Roda o supervisor em primeiro plano.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    from agent.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    interval = args.interval or float(settings.automation_tick_seconds or 5.0)
    asyncio.run(_run_forever(settings, interval))
    return 0


# ─────────────────────────────────────────────────────────── serviço

def cmd_install(args: argparse.Namespace) -> int:
    """Instala o serviço nativo do sistema operacional.

    Args:
        args: argumentos da linha de comando (escopo, pasta de dados e comando).

    Returns:
        `0` quando a instalação deu certo, `1` caso contrário.
    """
    adapter = current_adapter()
    options = default_options()
    options.scope = args.scope
    if args.data_dir:
        # `DATA_DIR` é a variável de ambiente do `Settings.data_dir`.
        options.env["DATA_DIR"] = args.data_dir
        options.log_path = str(Path(args.data_dir) / "supervisor.log")
    if args.exec_command:
        options.command = list(args.exec_command)
    result = adapter.install(options)
    _print(result)
    return 0 if result.get("installed") else 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Remove o serviço nativo.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    adapter = current_adapter()
    _print(adapter.uninstall())
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Inicia o serviço nativo.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    adapter = current_adapter()
    _print(adapter.start())
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Para o serviço nativo.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    adapter = current_adapter()
    _print(adapter.stop())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Mostra a situação do runtime e do serviço nativo.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    supervisor = build_supervisor()
    adapter = current_adapter()
    payload = {
        "runtime": supervisor.status(),
        "service": adapter.status().as_dict(),
        "adapters": adapters_status(),
    }
    _print(payload)
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Mostra o diagnóstico detalhado do runtime.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    supervisor = build_supervisor()
    payload = supervisor.diagnose()
    payload["service"] = current_adapter().status().as_dict()
    payload["adapters"] = adapters_status()
    _print(payload)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Lista as automações registradas.

    Args:
        args: argumentos da linha de comando.

    Returns:
        O código de saída do processo.
    """
    from agent.automation.store import AutomationService
    from agent.persistence.database import build_session_factory, create_db_engine, init_db
    from agent.config import get_settings

    settings = get_settings()
    engine = init_db(create_db_engine(settings), settings)
    session = build_session_factory(engine)()
    try:
        service = AutomationService(session)
        rows = service.list()
        _print(
            [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "state": row.state,
                    "target": row.target_kind,
                    "trigger": (row.trigger_json or {}).get("kind"),
                    "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                    "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                }
                for row in rows
            ]
        )
    finally:
        session.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Monta o interpretador de argumentos da linha de comando.

    Returns:
        O interpretador com os subcomandos do runtime.
    """
    parser = argparse.ArgumentParser(
        prog="callidus-supervisor",
        description="Runtime autônomo de automações do Callidus",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="roda o supervisor em primeiro plano")
    run.add_argument(
        "--interval",
        type=float,
        default=None,
        help="segundos entre tiques (padrão: a configuração do Callidus)",
    )
    run.set_defaults(func=cmd_run)

    install = sub.add_parser("install", help="instala o serviço nativo de inicialização")
    install.add_argument(
        "--scope",
        choices=["user", "system"],
        default="user",
        help="usuário (sem privilégio) ou sistema (exige administrador)",
    )
    install.add_argument("--data-dir", default="", help="pasta de dados do Callidus")
    install.add_argument(
        "--command",
        dest="exec_command",
        nargs="+",
        default=[],
        help="comando que o serviço deve executar",
    )
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall", help="remove o serviço nativo")
    uninstall.set_defaults(func=cmd_uninstall)

    start = sub.add_parser("start", help="inicia o serviço nativo")
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser("stop", help="para o serviço nativo")
    stop.set_defaults(func=cmd_stop)

    status = sub.add_parser("status", help="situação do runtime e do serviço")
    status.set_defaults(func=cmd_status)

    diagnose = sub.add_parser("diagnose", help="diagnóstico detalhado")
    diagnose.set_defaults(func=cmd_diagnose)

    listing = sub.add_parser("list", help="lista as automações")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da linha de comando.

    Args:
        argv: argumentos a interpretar; quando ausentes, usa `sys.argv`.

    Returns:
        O código de saída do processo.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
