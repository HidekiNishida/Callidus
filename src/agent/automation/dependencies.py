# src/agent/automation/dependencies.py — verificação e inicialização de dependências
"""Antes de executar, a automação confere se o que ela precisa existe.

O verificador é **read-only** por padrão: ele responde "está pronto?" para cada
dependência declarada. Só quando a dependência não está pronta é que a estratégia de
inicialização entra em cena — e ela só age quando o mecanismo está configurado **e**
autorizado. Nada é instalado, baixado ou reiniciado sem isso.

Cada dependência devolve um estado (`ready`, `missing`, `unreachable`, `blocked`) e um
motivo. Dependência crítica indisponível **bloqueia** o disparo e reagenda a
tentativa; não há consumo de inferência tentando executar o impossível.
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.automation.contracts import DependencySpec, StartStrategy
from agent.automation.enums import DependencyKind, StartMechanism


@dataclass
class DependencyReport:
    """Estado de uma dependência."""

    name: str
    kind: str
    ok: bool
    state: str = "ready"
    detail: str = ""
    # `True` quando a dependência é crítica: bloqueia a execução.
    required: bool = True
    started: bool = False
    start_detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "ok": self.ok,
            "state": self.state,
            "detail": self.detail,
            "required": self.required,
            "started": self.started,
            "start_detail": self.start_detail,
        }


@dataclass
class DependencyCheck:
    """Resultado agregado da verificação."""

    reports: list[DependencyReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Pronta quando toda dependência **crítica** está pronta."""
        return all(r.ok for r in self.reports if r.required)

    @property
    def blocking(self) -> list[DependencyReport]:
        return [r for r in self.reports if r.required and not r.ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dependencies": [r.as_dict() for r in self.reports],
            "blocking": [r.name for r in self.blocking],
        }


class DependencyResolver:
    """Resolve e verifica as dependências declaradas por uma automação."""

    def __init__(
        self,
        *,
        settings: Any,
        project_root: str | None = None,
        remote: dict[str, Any] | None = None,
        target_kind: str = "local",
    ) -> None:
        self._settings = settings
        self._project_root = project_root
        self._remote = remote
        self._target_kind = target_kind

    # ------------------------------------------------------------ verificação

    async def check_all(self, specs: list[DependencySpec]) -> DependencyCheck:
        reports: list[DependencyReport] = []
        for spec in specs or []:
            report = await self._check_one(spec)
            if not report.ok and report.required and self._can_start(spec):
                started_ok, started_detail = await self._start(spec)
                report.started = started_ok
                report.start_detail = started_detail
                if started_ok:
                    recheck = await self._check_one(spec)
                    recheck.started = True
                    recheck.start_detail = started_detail
                    report = recheck
            reports.append(report)
        return DependencyCheck(reports=reports)

    async def _check_one(self, spec: DependencySpec) -> DependencyReport:
        kind = DependencyKind(spec.kind)
        handler = {
            DependencyKind.PROJECT_DIR: self._check_project_dir,
            DependencyKind.WORKDIR: self._check_workdir,
            DependencyKind.OS: self._check_os,
            DependencyKind.INTERPRETER: self._check_interpreter,
            DependencyKind.SCRIPT: self._check_script,
            DependencyKind.REMOTE: self._check_remote,
            DependencyKind.PROVIDER: self._check_provider,
            DependencyKind.TOOL: self._check_tool,
            DependencyKind.MCP: self._check_mcp,
            DependencyKind.CREDENTIAL: self._check_credential,
        }.get(kind)
        if handler is None:
            return DependencyReport(
                name=spec.label(),
                kind=str(spec.kind),
                ok=not spec.required,
                state="blocked",
                detail=f"tipo de dependência desconhecido: {spec.kind}",
                required=spec.required,
            )
        return await handler(spec)

    # ── locais ───────────────────────────────────────────────────────────

    def _check_project_dir(self, spec: DependencySpec) -> DependencyReport:
        root = spec.params.get("path") or self._project_root
        if not root:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="projeto sem diretório raiz", required=spec.required,
            )
        path = Path(str(root)).expanduser()
        if not path.is_dir():
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"diretório inexistente: {path}", required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
            detail=str(path), required=spec.required,
        )

    def _check_workdir(self, spec: DependencySpec) -> DependencyReport:
        raw = spec.params.get("path")
        if not raw:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="diretório de trabalho não informado", required=spec.required,
            )
        path = Path(str(raw)).expanduser()
        if not path.is_dir():
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"diretório inexistente: {path}", required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
            detail=str(path), required=spec.required,
        )

    def _check_os(self, spec: DependencySpec) -> DependencyReport:
        wanted = str(spec.params.get("os_family") or "").lower()
        if not wanted:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
                detail="sem exigência de sistema", required=spec.required,
            )
        actual = self._target_os_family()
        if actual != wanted:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"destino é {actual}, a automação exige {wanted}",
                required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
            detail=actual, required=spec.required,
        )

    def _target_os_family(self) -> str:
        if self._target_kind == "remote" and self._remote:
            shell = str(self._remote.get("shell") or "posix").lower()
            return "windows" if shell in {"powershell", "pwsh", "cmd", "windows"} else "posix"
        if os.name == "nt":
            return "windows"
        return "posix"

    async def _check_interpreter(self, spec: DependencySpec) -> DependencyReport:
        name = str(spec.params.get("name") or spec.params.get("interpreter") or "").strip()
        if not name:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="interpretador não informado", required=spec.required,
            )
        if self._target_kind == "remote" and self._remote:
            found, detail = await self._remote_which(name)
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=found,
                state="ready" if found else "missing", detail=detail,
                required=spec.required,
            )
        found = shutil.which(name)
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=bool(found),
            state="ready" if found else "missing",
            detail=found or f"interpretador não encontrado: {name}",
            required=spec.required,
        )

    async def _check_script(self, spec: DependencySpec) -> DependencyReport:
        raw = str(spec.params.get("path") or "").strip()
        if not raw:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="script não informado", required=spec.required,
            )
        if self._target_kind == "remote" and self._remote:
            from agent.remote.ssh import RemoteError, SshTransport

            ssh = SshTransport(_remote_config(self._remote))
            cmd = (
                f"if (Test-Path -LiteralPath '{raw}') {{ 'ok' }} else {{ 'missing' }}"
                if self._target_os_family() == "windows"
                else f"if [ -f {sh_quote(raw)} ]; then echo ok; else echo missing; fi"
            )
            try:
                result = await ssh.run(cmd, cwd=".", timeout=30)
            except RemoteError as exc:
                return DependencyReport(
                    name=spec.label(), kind=str(spec.kind), ok=False,
                    state="unreachable", detail=str(exc), required=spec.required,
                )
            found = result.exit_code == 0 and "ok" in result.stdout
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=found,
                state="ready" if found else "missing",
                detail=raw if found else f"script não encontrado no destino: {raw}",
                required=spec.required,
            )
        path = Path(raw).expanduser()
        if not path.is_file():
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"script não encontrado: {path}", required=spec.required,
            )
        if not os.access(path, os.X_OK):
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"script sem permissão de execução: {path}", required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
            detail=str(path), required=spec.required,
        )

    async def _check_remote(self, spec: DependencySpec) -> DependencyReport:
        if self._target_kind != "remote" or not self._remote:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="unreachable",
                detail="automação não declara destino remoto", required=spec.required,
            )
        from agent.remote.ssh import RemoteError, SshTransport

        ssh = SshTransport(_remote_config(self._remote))
        try:
            health = await ssh.check()
        except RemoteError as exc:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="unreachable",
                detail=str(exc), required=spec.required,
            )
        ok = bool(health.get("ok"))
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=ok,
            state="ready" if ok else "unreachable",
            detail=str(health.get("system") or ""), required=spec.required,
        )

    async def _check_provider(self, spec: DependencySpec) -> DependencyReport:
        name = str(spec.params.get("name") or self._settings.default_provider or "")
        try:
            from agent.providers.registry import catalog_for_settings, build_provider_by_name

            catalog = catalog_for_settings(self._settings)
            if catalog.names() and name not in catalog.names():
                return DependencyReport(
                    name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                    detail=f"provedor não configurado: {name}", required=spec.required,
                )
            provider = build_provider_by_name(name, catalog, self._settings)
            health = await provider.health_check()
            ok = bool(getattr(health, "ok", False))
            detail = str(getattr(health, "detail", "") or "")
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=ok,
                state="ready" if ok else "unreachable",
                detail=detail or f"provedor {name}", required=spec.required,
            )
        except Exception as exc:  # noqa: BLE001 — indisponibilidade vira estado, não crash
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="unreachable",
                detail=f"provedor indisponível: {exc}", required=spec.required,
            )

    def _check_tool(self, spec: DependencySpec) -> DependencyReport:
        tool_id = str(spec.params.get("tool") or spec.params.get("name") or "")
        if not tool_id:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="ferramenta não informada", required=spec.required,
            )
        try:
            from agent.tools.registry import build_default_registry

            registry = build_default_registry()
            known = {spec_.id for spec_ in registry.list_specs()}
        except Exception as exc:  # noqa: BLE001
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"registro de ferramentas indisponível: {exc}", required=spec.required,
            )
        if tool_id in known:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
                detail=tool_id, required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
            detail=f"ferramenta ausente no registro: {tool_id}", required=spec.required,
        )

    def _check_mcp(self, spec: DependencySpec) -> DependencyReport:
        server = str(spec.params.get("server") or spec.params.get("name") or "")
        if not server:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="servidor MCP não informado", required=spec.required,
            )
        config_path = Path(self._settings.mcp_config_path) if self._settings.mcp_config_path else None
        if config_path is None or not config_path.is_file():
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail="arquivo de configuração MCP ausente", required=spec.required,
            )
        try:
            from agent.mcp.manager import McpManager

            manager = McpManager(config_path)
            servers = {s.id: s for s in manager.list_servers()}
        except Exception as exc:  # noqa: BLE001
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"configuração MCP ilegível: {exc}", required=spec.required,
            )
        entry = servers.get(server)
        if entry is None:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"servidor MCP não configurado: {server}", required=spec.required,
            )
        if not entry.enabled:
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
                detail=f"servidor MCP desabilitado: {server}", required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=True, state="ready",
            detail=server, required=spec.required,
        )

    def _check_credential(self, spec: DependencySpec) -> DependencyReport:
        """Confere a existência da credencial **sem** revelar o valor."""
        env_name = spec.params.get("env")
        secret_file = spec.params.get("file")
        if env_name:
            present = bool(os.environ.get(str(env_name)))
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=present,
                state="ready" if present else "missing",
                detail=(
                    f"variável de ambiente {env_name} definida"
                    if present
                    else f"variável de ambiente {env_name} ausente"
                ),
                required=spec.required,
            )
        if secret_file:
            path = Path(str(secret_file)).expanduser()
            present = path.is_file()
            return DependencyReport(
                name=spec.label(), kind=str(spec.kind), ok=present,
                state="ready" if present else "missing",
                detail=f"arquivo de credencial {'presente' if present else 'ausente'}",
                required=spec.required,
            )
        return DependencyReport(
            name=spec.label(), kind=str(spec.kind), ok=False, state="missing",
            detail="credencial não informada (env ou file)", required=spec.required,
        )

    # ── inicialização ────────────────────────────────────────────────────

    def _can_start(self, spec: DependencySpec) -> bool:
        strategy = spec.start
        if strategy is None:
            return False
        if strategy.mechanism is StartMechanism.NONE:
            return False
        if not strategy.authorized:
            return False
        if strategy.mechanism is StartMechanism.COMMAND and not strategy.command:
            return False
        if strategy.mechanism is StartMechanism.SERVICE and not strategy.service_name:
            return False
        if strategy.mechanism is StartMechanism.MCP_RESTART and not spec.params.get("server"):
            return False
        return True

    async def _start(self, spec: DependencySpec) -> tuple[bool, str]:
        strategy = spec.start
        assert strategy is not None
        try:
            if strategy.mechanism is StartMechanism.COMMAND:
                return await self._start_command(strategy)
            if strategy.mechanism is StartMechanism.SERVICE:
                return await self._start_service(strategy)
            if strategy.mechanism is StartMechanism.MCP_RESTART:
                return self._start_mcp(spec, strategy)
        except Exception as exc:  # noqa: BLE001
            return False, f"falha ao iniciar dependência: {exc}"
        return False, "mecanismo de inicialização não aplicável"

    async def _start_command(self, strategy: StartStrategy) -> tuple[bool, str]:
        command = list(strategy.command)
        if self._target_kind == "remote" and self._remote:
            from agent.remote.ssh import RemoteError, SshTransport

            ssh = SshTransport(_remote_config(self._remote))
            try:
                result = await ssh.run(command, cwd=".", timeout=strategy.timeout_sec)
            except RemoteError as exc:
                return False, str(exc)
            return (
                result.exit_code == 0,
                f"comando remoto executado (código {result.exit_code})",
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError) as exc:
            return False, f"não foi possível executar o comando de inicialização: {exc}"
        try:
            await asyncio.wait_for(proc.communicate(), timeout=strategy.timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            return False, f"tempo esgotado na inicialização ({strategy.timeout_sec:.0f}s)"
        code = proc.returncode or 0
        return code == 0, f"comando de inicialização retornou {code}"

    async def _start_service(self, strategy: StartStrategy) -> tuple[bool, str]:
        name = strategy.service_name or ""
        if self._target_kind == "remote" and self._remote:
            return await self._remote_service(name, strategy)
        system = platform.system()
        if system == "Darwin":
            command = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{name}"]
        elif system == "Linux":
            command = ["systemctl", "--user", "restart", name]
        else:
            command = ["sc", "stop", name, "&", "sc", "start", name]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except (FileNotFoundError, PermissionError) as exc:
            return False, f"gerenciador de serviços indisponível: {exc}"
        try:
            await asyncio.wait_for(proc.communicate(), timeout=strategy.timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            return False, f"tempo esgotado reiniciando o serviço ({strategy.timeout_sec:.0f}s)"
        code = proc.returncode or 0
        return code == 0, f"reinício do serviço '{name}' retornou {code}"

    async def _remote_service(self, name: str, strategy: StartStrategy) -> tuple[bool, str]:
        from agent.remote.ssh import RemoteError, SshTransport

        ssh = SshTransport(_remote_config(self._remote))
        if self._target_os_family() == "windows":
            command = f"Restart-Service -Name '{name}' -ErrorAction Stop"
        else:
            command = f"systemctl --user restart {sh_quote(name)}"
        try:
            result = await ssh.run(command, cwd=".", timeout=strategy.timeout_sec)
        except RemoteError as exc:
            return False, str(exc)
        return result.exit_code == 0, f"reinício remoto do serviço retornou {result.exit_code}"

    def _start_mcp(self, spec: DependencySpec, strategy: StartStrategy) -> tuple[bool, str]:
        """Reinicia um processo MCP gerenciado (o `McpManager` recarrega a configuração)."""
        config_path = self._settings.mcp_config_path
        if not config_path or not Path(config_path).is_file():
            return False, "arquivo de configuração MCP ausente"
        try:
            from agent.mcp.manager import McpManager

            manager = McpManager(Path(config_path))
            manager.reload()
            servers = {s.id for s in manager.list_servers()}
        except Exception as exc:  # noqa: BLE001
            return False, f"não foi possível reiniciar o MCP: {exc}"
        server = str(spec.params.get("server"))
        if server not in servers:
            return False, f"servidor MCP não configurado: {server}"
        return True, f"configuração MCP recarregada ({server})"

    # ── apoio ────────────────────────────────────────────────────────────

    async def _remote_which(self, name: str) -> tuple[bool, str]:
        from agent.remote.ssh import RemoteError, SshTransport

        ssh = SshTransport(_remote_config(self._remote))
        cmd = (
            f"(Get-Command {name} -ErrorAction SilentlyContinue) | Select-Object -First 1 -ExpandProperty Source"
            if self._target_os_family() == "windows"
            else f"command -v {sh_quote(name)}"
        )
        try:
            result = await ssh.run(cmd, cwd=".", timeout=30)
        except RemoteError as exc:
            return False, str(exc)
        found = result.exit_code == 0 and bool(result.stdout.strip())
        return found, result.stdout.strip() or f"interpretador ausente no destino: {name}"


def sh_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _remote_config(remote_cfg: dict[str, Any]):
    from agent.remote.ssh import RemoteConfig

    return RemoteConfig(
        host=remote_cfg.get("host", ""),
        port=int(remote_cfg.get("port", 22) or 22),
        user=remote_cfg.get("user"),
        key_path=remote_cfg.get("key_path"),
        password=remote_cfg.get("password"),
        root=remote_cfg.get("root", ".") or ".",
        shell=remote_cfg.get("shell", "posix"),
        timeout=float(remote_cfg.get("timeout", 120) or 120),
    )
