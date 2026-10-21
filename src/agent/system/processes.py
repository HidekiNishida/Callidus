"""
Arquivo: src/agent/system/processes.py
Nome: processes.py
Propósito: listar, inspecionar, encerrar e acompanhar processos autorizados do sistema.
Responsabilidade: camada de infraestrutura — inventário de processos e tarefas longas em segundo plano.
Componentes: ProcessInfo, ProcessHandle, ProcessManager, list_processes, process_info, terminate_process.
Dependências: agent.system.adapters, subprocess, signal, threading.
Observações: processos em segundo plano são rastreados pelo gerenciador, com saída parcial e cancelamento.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agent.system.adapters import current_os, get_adapter

#: Quantidade máxima de bytes de saída retidos por processo em segundo plano.
MAX_CAPTURED_BYTES = 512 * 1024


@dataclass(frozen=True)
class ProcessInfo:
    """Um processo do sistema, visto pelo agente.

    Atributos:
        pid: identificador do processo.
        ppid: identificador do processo pai.
        elapsed_seconds: idade do processo, em segundos, quando conhecida.
        command: linha de comando ou nome do executável.
    """

    pid: int
    ppid: int
    elapsed_seconds: int | None
    command: str

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável do processo.

        Returns:
            Um dicionário com `pid`, `ppid`, `elapsed_seconds` e `command`.
        """
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "elapsed_seconds": self.elapsed_seconds,
            "command": self.command,
        }


def _parse_elapsed(raw: str) -> int | None:
    """Converte a idade de processo do `ps` para segundos.

    Formatos aceitos: `MM:SS`, `HH:MM:SS` (macOS) e segundos inteiros (Linux).

    Args:
        raw: texto do campo de idade.

    Returns:
        A idade em segundos, ou `None` quando o texto não é reconhecido.
    """
    text = raw.strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return None
        seconds = 0
        for number in numbers:
            seconds = seconds * 60 + number
        return seconds
    try:
        return int(text)
    except ValueError:
        return None


def _parse_ps_output(text: str) -> list[ProcessInfo]:
    """Interpreta a saída do comando de listagem de processos.

    Args:
        text: saída de `ps`.

    Returns:
        A lista de processos interpretados.
    """
    processes: list[ProcessInfo] = []
    for line in text.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        try:
            pid = int(fields[0])
            ppid = int(fields[1])
        except ValueError:
            continue
        processes.append(
            ProcessInfo(
                pid=pid,
                ppid=ppid,
                elapsed_seconds=_parse_elapsed(fields[2]),
                command=fields[3].strip(),
            )
        )
    return processes


def list_processes(match: str | None = None, limit: int = 50) -> list[ProcessInfo]:
    """Lista os processos do sistema.

    Args:
        match: filtro opcional por substring do comando (sem distinção de maiúsculas).
        limit: quantidade máxima de processos devolvidos.

    Returns:
        A lista de processos, do mais novo para o mais antigo quando a idade é conhecida.
    """
    adapter = get_adapter()
    if not adapter.list_processes_cmd:
        return []
    try:
        completed = subprocess.run(
            list(adapter.list_processes_cmd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    processes = _parse_ps_output(completed.stdout or "")
    if match:
        needle = match.lower()
        processes = [item for item in processes if needle in item.command.lower()]
    processes.sort(key=lambda item: item.elapsed_seconds if item.elapsed_seconds is not None else 0)
    return processes[: max(1, int(limit))]


def process_info(pid: int) -> ProcessInfo | None:
    """Inspeciona um processo pelo identificador.

    Args:
        pid: identificador do processo.

    Returns:
        O processo, ou `None` quando ele não existe mais.
    """
    for item in list_processes(limit=5000):
        if item.pid == int(pid):
            return item
    return None


def terminate_process(pid: int, *, force: bool = False, timeout: float = 5.0) -> dict[str, Any]:
    """Encerra um processo autorizado.

    O pedido padrão é o sinal de término (`SIGTERM`); com `force`, o processo é
    eliminado. O encerramento é confirmado consultando o estado depois do pedido.

    Args:
        pid: identificador do processo.
        force: quando `True`, elimina o processo em vez de pedir que ele termine.
        timeout: espera máxima pela saída do processo.

    Returns:
        Um dicionário com o resultado e o estado observado depois do pedido.
    """
    target = int(pid)
    if target <= 0:
        return {"success": False, "error": "pid inválido"}
    if target == os.getpid():
        return {"success": False, "error": "recusado: o processo é o próprio Callidus"}
    if current_os() == "windows":
        command = ["taskkill", "/PID", str(target)] + (["/F"] if force else [])
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            ok = completed.returncode == 0
            detail = (completed.stdout or completed.stderr or "").strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "error": f"falha ao encerrar: {exc}"}
    else:
        try:
            os.kill(target, signal.SIGKILL if force else signal.SIGTERM)
            ok = True
            detail = "sinal enviado"
        except ProcessLookupError:
            return {"success": False, "error": "processo não existe", "pid": target}
        except PermissionError:
            return {
                "success": False,
                "error": "permissão negada ao encerrar o processo (permissão do sistema)",
                "pid": target,
            }
        except OSError as exc:
            return {"success": False, "error": f"falha ao encerrar: {exc}", "pid": target}
    deadline = time.monotonic() + timeout
    still_running = True
    while time.monotonic() < deadline:
        if process_info(target) is None:
            still_running = False
            break
        time.sleep(0.1)
    return {
        "success": ok,
        "pid": target,
        "forced": force,
        "detail": detail,
        "terminated": not still_running,
        "still_running": still_running,
    }


@dataclass
class ProcessHandle:
    """Tarefa longa em segundo plano, com saída parcial e cancelamento.

    Atributos:
        handle_id: identificador da tarefa.
        command: comando executado, como lista de argumentos.
        pid: identificador do processo do sistema.
        started_at: instante de início, em epoch.
        cwd: diretório de trabalho.
        stdout_path: arquivo que recebe a saída padrão.
        stderr_path: arquivo que recebe a saída de erro.
        returncode: código de saída, quando o processo já terminou.
        cancelled: quando `True`, o cancelamento foi pedido.
    """

    handle_id: str
    command: list[str]
    pid: int
    started_at: float
    cwd: str
    stdout_path: str
    stderr_path: str
    returncode: int | None = None
    cancelled: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável da tarefa.

        Returns:
            Um dicionário com o estado da tarefa em segundo plano.
        """
        return {
            "handle_id": self.handle_id,
            "command": self.command,
            "pid": self.pid,
            "started_at": self.started_at,
            "cwd": self.cwd,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "returncode": self.returncode,
            "cancelled": self.cancelled,
            "running": self.returncode is None,
        }


class ProcessManager:
    """Rastreia tarefas longas em segundo plano.

    Cada tarefa tem um identificador, um log em arquivo e um estado consultável. O
    cancelamento é cooperativo quando o processo respeita `SIGTERM` e forçado quando
    ele ignora o pedido.

    Observações:
        O gerenciador vive no processo do agente: as tarefas sobrevivem à etapa que as
        criou, mas não ao processo do Callidus.
    """

    def __init__(self, log_dir: str | None = None) -> None:
        """Cria o gerenciador.

        Args:
            log_dir: pasta onde os logs são gravados; `None` usa uma pasta temporária.
        """
        import tempfile

        self._log_dir = log_dir or os.path.join(tempfile.gettempdir(), "callidus-tasks")
        os.makedirs(self._log_dir, exist_ok=True)
        self._handles: dict[str, ProcessHandle] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessHandle:
        """Inicia um processo em segundo plano e devolve o identificador da tarefa.

        Args:
            command: comando e argumentos, já separados (sem shell).
            cwd: diretório de trabalho.
            env: variáveis extras; o ambiente atual é herdado.

        Returns:
            O `ProcessHandle` da tarefa.

        Raises:
            ValueError: quando o comando está vazio.
            OSError: quando o processo não pode ser iniciado.
        """
        argv = [str(item) for item in command]
        if not argv:
            raise ValueError("comando vazio")
        handle_id = uuid.uuid4().hex[:12]
        stdout_path = os.path.join(self._log_dir, f"{handle_id}.out.log")
        stderr_path = os.path.join(self._log_dir, f"{handle_id}.err.log")
        environment = dict(os.environ)
        environment.update(env or {})
        stdout = open(stdout_path, "wb")
        stderr = open(stderr_path, "wb")
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                start_new_session=(current_os() != "windows"),
            )
        finally:
            stdout.close()
            stderr.close()
        handle = ProcessHandle(
            handle_id=handle_id,
            command=argv,
            pid=process.pid,
            started_at=time.time(),
            cwd=str(cwd or os.getcwd()),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        with self._lock:
            self._handles[handle_id] = handle
            self._processes[handle_id] = process
        return handle

    def get(self, handle_id: str) -> ProcessHandle | None:
        """Tarefa pelo identificador, com o estado atualizado.

        Args:
            handle_id: identificador da tarefa.

        Returns:
            O `ProcessHandle` atualizado, ou `None` quando a tarefa não existe.
        """
        with self._lock:
            handle = self._handles.get(handle_id)
            process = self._processes.get(handle_id)
        if handle is None:
            return None
        if process is not None and handle.returncode is None:
            handle.returncode = process.poll()
        return handle

    def list(self) -> list[ProcessHandle]:
        """Todas as tarefas rastreadas, com o estado atualizado.

        Returns:
            A lista de tarefas em segundo plano.
        """
        with self._lock:
            ids = list(self._handles)
        return [handle for handle in (self.get(item) for item in ids) if handle is not None]

    def output(self, handle_id: str, *, tail_bytes: int = 8000) -> dict[str, Any]:
        """Saída parcial de uma tarefa em segundo plano.

        Args:
            handle_id: identificador da tarefa.
            tail_bytes: quantidade máxima de bytes lidos de cada fluxo.

        Returns:
            Um dicionário com o estado, a saída padrão e a saída de erro.
        """
        handle = self.get(handle_id)
        if handle is None:
            return {"success": False, "error": f"tarefa desconhecida: {handle_id}"}
        return {
            "success": True,
            "handle": handle.as_dict(),
            "stdout": _tail(handle.stdout_path, tail_bytes),
            "stderr": _tail(handle.stderr_path, tail_bytes),
        }

    def cancel(self, handle_id: str, *, force: bool = False) -> dict[str, Any]:
        """Cancela uma tarefa em segundo plano.

        Args:
            handle_id: identificador da tarefa.
            force: quando `True`, elimina o processo em vez de pedir que ele termine.

        Returns:
            Um dicionário com o resultado do cancelamento.
        """
        with self._lock:
            handle = self._handles.get(handle_id)
            process = self._processes.get(handle_id)
        if handle is None:
            return {"success": False, "error": f"tarefa desconhecida: {handle_id}"}
        handle.cancelled = True
        if process is not None and process.poll() is None:
            if current_os() == "windows":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid)] + (["/F"] if force else []),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL if force else signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        process.kill() if force else process.terminate()
                    except OSError:
                        pass
        handle.returncode = process.poll() if process is not None else None
        return {"success": True, "handle": handle.as_dict(), "forced": force}

    def reap(self) -> int:
        """Fecha os descritores e remove as tarefas já terminadas.

        Returns:
            A quantidade de tarefas removidas.
        """
        removed = 0
        with self._lock:
            for handle_id, handle in list(self._handles.items()):
                process = self._processes.get(handle_id)
                if process is not None and process.poll() is not None and handle.returncode is not None:
                    self._handles.pop(handle_id, None)
                    self._processes.pop(handle_id, None)
                    removed += 1
        return removed


def _tail(path: str, limit: int) -> str:
    """Lê a cauda de um arquivo de log.

    Args:
        path: caminho do arquivo.
        limit: quantidade máxima de bytes lidos do final.

    Returns:
        O texto final do arquivo; string vazia quando o arquivo não existe.
    """
    if not os.path.exists(path):
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def format_command(command: Sequence[str]) -> str:
    """Formata um comando para exibição.

    Args:
        command: comando e argumentos.

    Returns:
        O comando como texto, com as partes citadas quando há espaço.
    """
    return " ".join(shlex.quote(str(item)) for item in command)


#: Gerenciador de processos do processo — as tarefas em segundo plano são rastreadas aqui.
manager = ProcessManager()
