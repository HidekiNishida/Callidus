# src/agent/automation/actions/script.py — ação de script (determinística, sem inferência)
"""Executa um script previamente configurado.

Regras que esta ação garante:

- O script roda **sem depender de um LLM**: a execução é direta e o desfecho vem do
  código de saída e da saída capturada.
- O comando e o diretório são validados contra as permissões da definição aprovada
  antes de qualquer execução.
- O ambiente é controlado (herdado do processo + o que a definição diz) e nunca é
  gravado na evidência.
- O recibo (`receipt_path`) impede repetir um script que já produziu efeito.
- Destino remoto: o comando usa o shell e o caminho do computador de destino.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any

from agent.automation.actions.base import ActionContext, ActionResult
from agent.automation.contracts import ScriptAction
from agent.automation.enums import ActionKind, TargetKind
from agent.automation.security import (
    PermissionDenied,
    assert_path_allowed,
    assert_script_allowed,
    build_env,
    redact_evidence,
    resolve_workdir,
)

DEFAULT_TIMEOUT = 300.0
MAX_OUTPUT = 20_000


class ScriptActionRunner:
    """Ação de script."""

    kind = ActionKind.SCRIPT

    def __init__(self, spec: ScriptAction) -> None:
        self._spec = spec

    # ------------------------------------------------------------ comando

    def _command(self) -> list[str]:
        spec = self._spec
        if spec.command:
            command = list(spec.command)
        elif spec.script:
            command = [spec.script]
        else:
            raise PermissionDenied(
                "a ação de script não tem comando nem script", reason="no_command"
            )
        if spec.interpreter and not (
            len(command) > 1 and Path(command[0]).name == Path(spec.interpreter).name
        ):
            command = [spec.interpreter, *command]
        return command

    # ------------------------------------------------------------ execução

    async def execute(self, ctx: ActionContext) -> ActionResult:
        spec = self._spec
        permissions = ctx.target.get("permissions")
        project_root = ctx.target.get("project_root") or os.getcwd()
        timeout = float(spec.timeout_sec or ctx.timeout_sec or DEFAULT_TIMEOUT)

        try:
            command = self._command()
            assert_script_allowed(command, permissions)
        except PermissionDenied as exc:
            return ActionResult(
                ok=False,
                error=str(exc),
                category=exc.reason,
                retryable=False,
                evidence=redact_evidence({"command": self._safe_command()}),
            )

        target_kind = ctx.target.get("kind", TargetKind.LOCAL)
        if target_kind == TargetKind.REMOTE:
            return await self._run_remote(ctx, command, timeout)
        return await self._run_local(ctx, command, timeout, project_root)

    # ------------------------------------------------------------ local

    async def _run_local(
        self,
        ctx: ActionContext,
        command: list[str],
        timeout: float,
        project_root: str,
    ) -> ActionResult:
        spec = self._spec
        permissions = ctx.target.get("permissions")
        try:
            cwd = resolve_workdir(
                spec.cwd, project_root=project_root, permissions=permissions
            )
        except PermissionDenied as exc:
            return ActionResult(
                ok=False, error=str(exc), category=exc.reason, retryable=False
            )

        if spec.script and not Path(spec.script).is_absolute():
            script_path = cwd / spec.script
            if not script_path.exists():
                return ActionResult(
                    ok=False,
                    error=f"script não encontrado: {spec.script}",
                    category="script_missing",
                    retryable=False,
                )

        receipt = self._receipt_path(ctx, cwd)
        if receipt is not None:
            done = self._read_receipt(receipt)
            if done is not None:
                return ActionResult(
                    ok=True,
                    summary="execução anterior do script já registrada (efeito não repetido)",
                    evidence=redact_evidence(
                        {"command": command, "receipt": str(receipt), "skipped": True}
                    ),
                    finished=True,
                )

        env = build_env(spec.env)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, NotADirectoryError) as exc:
            return ActionResult(
                ok=False,
                error=f"não foi possível executar o script: {exc.strerror or exc}",
                category="script_missing",
                retryable=False,
                evidence=redact_evidence({"command": command}),
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except ProcessLookupError:  # pragma: no cover
                pass
            return ActionResult(
                ok=False,
                error=f"tempo esgotado no script ({timeout:.0f}s)",
                category="timeout",
                retryable=True,
                evidence=redact_evidence(
                    {
                        "command": command,
                        "cwd": str(cwd),
                        "timeout_sec": timeout,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    }
                ),
            )
        duration = int((time.monotonic() - started) * 1000)
        out = stdout.decode("utf-8", errors="replace")[-MAX_OUTPUT:]
        err = stderr.decode("utf-8", errors="replace")[-MAX_OUTPUT:]
        exit_code = proc.returncode or 0
        ok = exit_code in (spec.success_exit_codes or [0])
        if ok and spec.success_regex:
            ok = bool(re.search(spec.success_regex, out))
        evidence = {
            "command": command,
            "cwd": str(cwd),
            "exit_code": exit_code,
            "stdout": out,
            "stderr": err,
            "duration_ms": duration,
            "target": "local",
        }
        if ok and receipt is not None:
            self._write_receipt(receipt, ctx.idempotency_key)
        return ActionResult(
            ok=ok,
            summary=(
                f"script terminou com código {exit_code}"
                if ok
                else f"script falhou com código {exit_code}"
            ),
            evidence=redact_evidence(evidence),
            error=None if ok else (err.strip()[-500:] or f"código de saída {exit_code}"),
            category=None if ok else "nonzero_exit",
            retryable=not ok,
        )

    # ------------------------------------------------------------ remoto

    async def _run_remote(
        self, ctx: ActionContext, command: list[str], timeout: float
    ) -> ActionResult:
        spec = self._spec
        remote_cfg = ctx.target.get("remote")
        if not remote_cfg:
            return ActionResult(
                ok=False,
                error="destino remoto sem configuração de acesso",
                category="remote_unreachable",
                retryable=True,
            )
        from agent.remote.ssh import RemoteError, SshTransport

        shell = str(remote_cfg.get("shell") or "posix").lower()
        is_windows = bool(remote_cfg.get("is_windows")) or shell in {
            "powershell",
            "pwsh",
            "cmd",
            "windows",
        }
        cwd = spec.cwd or "."
        if is_windows:
            cwd = str(cwd).replace("/", "\\")
        started = time.monotonic()
        ssh = SshTransport(_remote_config(remote_cfg))
        try:
            result = await ssh.run(command, cwd=cwd, timeout=timeout)
        except RemoteError as exc:
            message = str(exc)
            unreachable = "tempo esgotado" in message or "não foi possível iniciar" in message
            return ActionResult(
                ok=False,
                error=message,
                category="timeout" if unreachable else "remote_unreachable",
                retryable=True,
                evidence=redact_evidence(
                    {"command": command, "cwd": cwd, "target": "remote", "timeout_sec": timeout}
                ),
            )
        duration = int((time.monotonic() - started) * 1000)
        out = result.stdout[-MAX_OUTPUT:]
        err = result.stderr[-MAX_OUTPUT:]
        ok = result.exit_code in (spec.success_exit_codes or [0])
        if ok and spec.success_regex:
            ok = bool(re.search(spec.success_regex, out))
        evidence = {
            "command": command,
            "cwd": cwd,
            "exit_code": result.exit_code,
            "stdout": out,
            "stderr": err,
            "duration_ms": duration,
            "target": "remote",
            "host": remote_cfg.get("host"),
        }
        return ActionResult(
            ok=ok,
            summary=(
                f"script remoto terminou com código {result.exit_code}"
                if ok
                else f"script remoto falhou com código {result.exit_code}"
            ),
            evidence=redact_evidence(evidence),
            error=None if ok else (err.strip()[-500:] or f"código de saída {result.exit_code}"),
            category=None if ok else "nonzero_exit",
            retryable=not ok,
        )

    # ------------------------------------------------------------ recibo

    def _receipt_path(self, ctx: ActionContext, cwd: Path) -> Path | None:
        spec = self._spec
        if not spec.receipt_path:
            return None
        permissions = ctx.target.get("permissions")
        try:
            return assert_path_allowed(
                spec.receipt_path,
                permissions,
                project_root=ctx.target.get("project_root") or cwd,
            )
        except PermissionDenied:
            return None

    def _read_receipt(self, receipt: Path) -> str | None:
        try:
            return receipt.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _write_receipt(self, receipt: Path, key: str) -> None:
        try:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(key, encoding="utf-8")
        except OSError:
            # Falhar o recibo não desfaz a execução: o resultado continua válido.
            pass

    def _safe_command(self) -> list[str]:
        spec = self._spec
        if spec.command:
            return list(spec.command)
        return [spec.script or ""]


def _remote_config(remote_cfg: dict[str, Any]):
    """Traduz a configuração do destino em `RemoteConfig` (o mesmo do projeto remoto)."""
    from agent.remote.ssh import RemoteConfig

    data = {
        "host": remote_cfg.get("host", ""),
        "port": int(remote_cfg.get("port", 22) or 22),
        "user": remote_cfg.get("user"),
        "key_path": remote_cfg.get("key_path"),
        "password": remote_cfg.get("password"),
        "root": remote_cfg.get("root", ".") or ".",
        "shell": remote_cfg.get("shell", "posix"),
        "timeout": float(remote_cfg.get("timeout", 120) or 120),
    }
    config = RemoteConfig(**data)
    return config
