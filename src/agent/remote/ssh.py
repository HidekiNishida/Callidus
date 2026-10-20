"""
Arquivo: src/agent/remote/ssh.py
Nome: ssh.py
Propósito: executar ações em um projeto remoto por SSH usando o binário do sistema.
Responsabilidade: camada de infraestrutura — transporte de comandos e arquivos para o computador remoto.
Componentes: RemoteConfig, RemoteError, CommandResult, SshTransport.
Dependências: asyncio, pydantic.
Observações: funciona com servidores POSIX e Windows (PowerShell); arquivos via base64 evitam problemas de quoting.
"""
from __future__ import annotations

import asyncio
import base64
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RemoteConfig(BaseModel):
    """Como alcançar o computador remoto do projeto."""

    host: str
    port: int = 22
    user: str | None = None
    key_path: str | None = None
    password: str | None = None
    root: str = "."
    # `posix` (linux/macOS) ou `powershell` (windows).
    shell: str = "posix"
    timeout: float = 120.0

    @field_validator("host")
    @classmethod
    def _host_preenchido(cls, value: str) -> str:
        """Valida que o host do computador remoto foi informado.

        Raises:
            ValueError: quando o host está vazio.
        """
        if not (value or "").strip():
            raise ValueError("host do computador remoto é obrigatório")
        return value.strip()

    @field_validator("shell")
    @classmethod
    def _shell_conhecido(cls, value: str) -> str:
        """Normaliza o shell do servidor para `posix` ou `powershell`.

        Raises:
            ValueError: quando o shell informado não é reconhecido.
        """
        clean = (value or "posix").strip().lower()
        if clean in {"powershell", "pwsh", "cmd", "windows"}:
            return "powershell"
        if clean in {"posix", "sh", "bash", ""}:
            return "posix"
        raise ValueError("shell inválido: use posix (Linux/macOS) ou powershell (Windows)")

    @property
    def target(self) -> str:
        """Destino da conexão, no formato `usuario@host` quando há usuário."""
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def is_windows(self) -> bool:
        """Indica se o servidor remoto usa PowerShell."""
        return self.shell.lower() in {"powershell", "pwsh", "cmd", "windows"}


class RemoteError(RuntimeError):
    """Falha ao falar com o servidor remoto."""


@dataclass
class CommandResult:
    """Desfecho de um comando remoto.

    Atributos:
        exit_code: código de saída do comando.
        stdout: saída padrão.
        stderr: saída de erro.
    """

    exit_code: int
    stdout: str
    stderr: str


def _resolve_key(key_path: str | None) -> str | None:
    """Resolve o caminho da chave SSH privada, quando informada.

    Args:
        key_path: caminho da chave; `None` significa autenticação por padrão do ssh.

    Returns:
        O caminho absoluto da chave, ou `None`.

    Raises:
        RemoteError: quando a chave informada não existe no disco.
    """
    if not key_path:
        return None
    path = Path(key_path).expanduser()
    if not path.is_file():
        raise RemoteError(f"chave SSH não encontrada: {path}")
    return str(path)


class SshTransport:
    """Fala com o servidor pelo binário `ssh` do sistema (sem dependências extras).

    Ações: rodar comandos (com saída em tempo real), ler e escrever arquivos, listar e
    criar pastas. Funciona com servidores Linux/macOS (shell POSIX) e Windows (PowerShell).
    """

    def __init__(self, config: RemoteConfig) -> None:
        """Monta o cliente SSH com a configuração do computador remoto."""
        self.config = config
        self._ssh = shutil.which("ssh")

    # ── baixo nível ──────────────────────────────────────────────────────
    def _base_args(self) -> list[str]:
        """Argumentos base da chamada ao `ssh`.

        Returns:
            A lista de argumentos com as opções de porta, host known e chave.

        Raises:
            RemoteError: quando o binário `ssh` não existe ou a chave configurada não foi encontrada.
        """
        if not self._ssh:
            raise RemoteError("o binário `ssh` não está disponível neste computador")
        args = [
            self._ssh,
            "-p",
            str(self.config.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=15",
        ]
        key = _resolve_key(self.config.key_path)
        if key:
            args += ["-i", key]
        args.append(self.config.target)
        return args

    def _quote(self, value: str) -> str:
        """Cita um valor para o shell do servidor (POSIX ou PowerShell).

        Args:
            value: texto a citar.

        Returns:
            O texto pronto para ser embutido no comando remoto.
        """
        if self.config.is_windows:
            return '"' + str(value).replace('"', '`"') + '"'
        return shlex.quote(str(value))

    def _remote_path(self, path: str) -> str:
        """Junta a pasta remota do projeto com o caminho relativo.

        Args:
            path: caminho relativo dentro do projeto remoto.

        Returns:
            O caminho completo no servidor, no formato do shell configurado.
        """
        base = (self.config.root or ".").strip()
        rel = str(path or ".").strip()
        if not rel or rel == ".":
            return base or "."
        if self.config.is_windows:
            base = base.replace("/", "\\")
            rel = rel.replace("/", "\\")
            if not base:
                return rel
            return f"{base}\\{rel}"
        if not base or base == ".":
            return rel
        return f"{base.rstrip('/')}/{rel}"

    async def run(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        on_output: Any = None,
    ) -> CommandResult:
        """Roda um comando no servidor remoto e devolve saída e código.

        Args:
            command: comando como texto ou lista de argumentos.
            cwd: pasta remota onde o comando roda.
            timeout: tempo limite em segundos; por padrão, o da configuração.
            on_output: callback opcional que recebe cada trecho de saída em tempo real.

        Returns:
            O resultado do comando, com código de saída, stdout e stderr.

        Raises:
            RemoteError: quando o `ssh` não pode ser iniciado ou o comando estoura o tempo.
        """
        text = command if isinstance(command, str) else " ".join(shlex.quote(part) for part in command)
        workdir = self._remote_path(cwd or ".")
        if self.config.is_windows:
            full = f"Set-Location -LiteralPath {self._quote(workdir)}; {text}"
        else:
            full = f"cd {shlex.quote(workdir)} && {text}"
        args = self._base_args() + [full]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise RemoteError(f"não foi possível iniciar o ssh: {exc}") from exc
        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []

        async def pump(stream, chunks, sink):
            """Transfere os dados entre a sessão local e o canal remoto."""
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if sink:
                    sink(chunk.decode("utf-8", errors="replace"))

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    pump(proc.stdout, out_chunks, on_output),
                    pump(proc.stderr, err_chunks, None),
                    proc.wait(),
                ),
                timeout=timeout or self.config.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RemoteError(f"tempo esgotado no comando remoto ({timeout or self.config.timeout}s)")
        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=b"".join(out_chunks).decode("utf-8", errors="replace"),
            stderr=b"".join(err_chunks).decode("utf-8", errors="replace"),
        )

    # ── arquivos ─────────────────────────────────────────────────────────
    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        """Lista o conteúdo de uma pasta remota.

        Args:
            path: caminho da pasta, relativo ao projeto remoto.

        Returns:
            A lista de entradas, cada uma com nome e caminho.

        Raises:
            RemoteError: quando a listagem falha no servidor.
        """
        if self.config.is_windows:
            cmd = f"Get-ChildItem -LiteralPath {self._quote(self._remote_path(path))} -Force | ForEach-Object {{ $_.Name }}"
        else:
            cmd = f"ls -1A -- {self._quote(self._remote_path(path))}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "não foi possível listar a pasta remota")
        entries = []
        for line in result.stdout.splitlines():
            name = line.strip()
            if name:
                entries.append({"name": name, "path": f"{str(path).rstrip('/')}/{name}" if path not in {"", "."} else name})
        return entries

    async def read_text(self, path: str) -> str:
        """Lê um arquivo remoto como texto.

        Args:
            path: caminho do arquivo, relativo ao projeto remoto.

        Returns:
            O conteúdo do arquivo.

        Raises:
            RemoteError: quando a leitura falha no servidor.
        """
        if self.config.is_windows:
            cmd = f"Get-Content -Raw -LiteralPath {self._quote(self._remote_path(path))}"
        else:
            cmd = f"cat -- {self._quote(self._remote_path(path))}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "arquivo remoto não encontrado")
        return result.stdout

    async def write_text(self, path: str, content: str) -> int:
        """Grava um arquivo remoto, enviando o conteúdo em base64.

        Args:
            path: caminho do arquivo, relativo ao projeto remoto.
            content: texto a gravar.

        Returns:
            A quantidade de bytes gravados.

        Raises:
            RemoteError: quando a escrita falha no servidor.
        """
        payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
        target = self._remote_path(path)
        if self.config.is_windows:
            cmd = (
                f"$b=[Convert]::FromBase64String('{payload}'); "
                f"[IO.File]::WriteAllBytes({self._quote(target)}, $b)"
            )
        else:
            cmd = f"printf %s {shlex.quote(payload)} | base64 -d > {shlex.quote(target)}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "não foi possível escrever no servidor remoto")
        return len(content.encode("utf-8"))

    async def make_dir(self, path: str) -> None:
        """Cria uma pasta remota (e os diretórios intermediários).

        Args:
            path: caminho da pasta, relativo ao projeto remoto.

        Raises:
            RemoteError: quando a criação falha no servidor.
        """
        target = self._remote_path(path)
        if self.config.is_windows:
            cmd = f"New-Item -ItemType Directory -Force -Path {self._quote(target)} | Out-Null"
        else:
            cmd = f"mkdir -p -- {shlex.quote(target)}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "não foi possível criar a pasta remota")

    async def remove(self, path: str) -> None:
        """Remove um arquivo ou pasta remoto, recursivamente.

        Args:
            path: caminho alvo, relativo ao projeto remoto.

        Raises:
            RemoteError: quando a remoção falha no servidor.
        """
        target = self._remote_path(path)
        if self.config.is_windows:
            cmd = f"Remove-Item -LiteralPath {self._quote(target)} -Force -Recurse"
        else:
            cmd = f"rm -rf -- {shlex.quote(target)}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "não foi possível remover no servidor remoto")

    async def move(self, source: str, target: str) -> None:
        """Move ou renomeia um caminho no servidor remoto.

        Args:
            source: caminho de origem, relativo ao projeto remoto.
            target: caminho de destino, relativo ao projeto remoto.

        Raises:
            RemoteError: quando a movimentação falha no servidor.
        """
        src = self._remote_path(source)
        dst = self._remote_path(target)
        if self.config.is_windows:
            cmd = f"Move-Item -LiteralPath {self._quote(src)} -Destination {self._quote(dst)} -Force"
        else:
            cmd = f"mv -- {shlex.quote(src)} {shlex.quote(dst)}"
        result = await self.run(cmd)
        if result.exit_code != 0:
            raise RemoteError(result.stderr.strip() or "não foi possível mover no servidor remoto")

    async def check(self) -> dict[str, Any]:
        """Diagnóstico: o servidor responde? Qual o sistema?

        Returns:
            Um dicionário com `ok`, o nome do sistema e o código de saída.
        """
        if self.config.is_windows:
            cmd = "$PSVersionTable.PSVersion.ToString()"
        else:
            cmd = "uname -s"
        result = await self.run(cmd, timeout=20)
        return {
            "ok": result.exit_code == 0,
            "system": result.stdout.strip() or result.stderr.strip(),
            "exit_code": result.exit_code,
        }
