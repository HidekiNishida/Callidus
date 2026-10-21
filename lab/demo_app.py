"""
Arquivo: lab/demo_app.py
Nome: demo_app.py
Propósito: aplicativo de demonstração que o Callidus abre, acompanha e inspeciona em teste real.
Responsabilidade: camada de laboratório — processo descartável que escreve um sinal de vida e serve HTTP local.
Componentes: main, _write_heartbeat, _serve.
Dependências: biblioteca padrão do Python (argparse, http.server, json, pathlib, signal).
Observações: o aplicativo não altera nada fora da pasta que recebe `--out`; ele encerra ao receber SIGTERM.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _Handler(BaseHTTPRequestHandler):
    """Responde a uma rota de estado, para que a verificação do resultado seja real."""

    def do_GET(self) -> None:  # noqa: N802 - nome imposto pela biblioteca padrão
        """Devolve o estado do aplicativo em JSON.

        Returns:
            Nada; a resposta é escrita em `self.wfile`.
        """
        body = json.dumps({"status": "ok", "pid": threading.get_ident()}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """Silencia o log de acesso: o aplicativo é silencioso por padrão.

        Args:
            fmt: formato da mensagem.
            args: argumentos da mensagem.
        """


def _write_heartbeat(out: Path, payload: dict) -> None:
    """Grava o sinal de vida do aplicativo.

    Args:
        out: arquivo de destino.
        payload: conteúdo a ser gravado em JSON.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Executa o aplicativo de demonstração.

    Args:
        argv: argumentos da linha de comando; `None` usa `sys.argv`.

    Returns:
        O código de saída do processo.
    """
    parser = argparse.ArgumentParser(description="Aplicativo de demonstração do Callidus")
    parser.add_argument("--out", required=True, help="arquivo que recebe o sinal de vida")
    parser.add_argument("--port", type=int, default=0, help="porta HTTP local (0 escolhe uma livre)")
    parser.add_argument("--seconds", type=float, default=30.0, help="tempo máximo de vida")
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser()
    server = HTTPServer(("127.0.0.1", args.port), _Handler)
    port = server.server_address[1]

    def _stop(_signum, _frame):
        server.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _write_heartbeat(
        out,
        {
            "pid": __import__("os").getpid(),
            "port": port,
            "url": f"http://127.0.0.1:{port}/",
            "started_at": time.time(),
        },
    )
    print(f"demo_app no ar em http://127.0.0.1:{port}/", flush=True)
    try:
        time.sleep(max(0.1, args.seconds))
    except KeyboardInterrupt:  # pragma: no cover - interrupção do terminal
        pass
    finally:
        server.shutdown()
        _write_heartbeat(out, {"pid": __import__("os").getpid(), "port": port, "stopped_at": time.time()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
