"""
Arquivo: src/agent/tools/system_tools.py
Nome: system_tools.py
Propósito: expor ao agente o gerenciamento de processos, aplicativos e diagnóstico do sistema.
Responsabilidade: camada de apresentação — handlers das ferramentas de sistema e de rede.
Componentes: register_all, e os handlers de diagnóstico, processos, aplicativos, recursos, rede e arquivos.
Dependências: agent.system, agent.tools.registry, agent.security.paths, agent.tools.availability.
Observações: leitura e diagnóstico são separados de escrita; toda escrita exige aprovação.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from agent.observability import emit
from agent.security.paths import PathSecurityError, resolve_under_root
from agent.system.adapters import current_os, get_adapter
from agent.system.apps import launch_app, list_apps, open_path
from agent.system.platform_info import (
    describe_system,
    diagnose_permissions,
    platform_summary,
)
from agent.system.processes import (
    ProcessManager,
    format_command,
    list_processes,
    process_info,
    terminate_process,
)
from agent.tools.availability import check_requirements, environment_report
from agent.tools.contracts import ExecutionMode, ToolFamily, ToolRisk
from agent.tools.policy import is_secret_env
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec

#: Gerenciador de tarefas longas em segundo plano do processo.
TASKS = ProcessManager()

#: Limite de bytes devolvidos por uma resposta de rede.
MAX_HTTP_BODY = 200_000


def _root(ctx: ToolContext) -> Path:
    """Raiz absoluta do projeto autorizada no contexto.

    Args:
        ctx: contexto da ferramenta.

    Returns:
        A raiz do projeto já resolvida.
    """
    return Path(ctx.project_root).resolve()


def _resolve(ctx: ToolContext, raw: str) -> tuple[Path | None, dict | None]:
    """Resolve um caminho dentro da raiz do projeto, devolvendo o erro em vez de levantá-lo.

    Args:
        ctx: contexto da ferramenta.
        raw: caminho informado pelo modelo.

    Returns:
        Tupla com o caminho resolvido (`None` quando inválido) e o resultado de erro.
    """
    try:
        return resolve_under_root(ctx.project_root, raw), None
    except PathSecurityError as exc:
        return None, {"success": False, "error": str(exc)}


async def _diagnose(ctx: ToolContext, args: dict) -> dict:
    """Diagnostica o ambiente: sistema, sessão, permissões e dependências.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (não usados).

    Returns:
        Um dicionário com o diagnóstico completo.
    """
    return {
        "success": True,
        "system": describe_system(),
        "permissions": diagnose_permissions(),
        "summary": platform_summary(),
        "adapter": get_adapter().name,
    }


async def _list_processes(ctx: ToolContext, args: dict) -> dict:
    """Lista os processos em execução.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`match` opcional, `limit` opcional).

    Returns:
        Um dicionário com a lista de processos.
    """
    found = list_processes(match=args.get("match"), limit=int(args.get("limit") or 50))
    return {"success": True, "count": len(found), "processes": [item.as_dict() for item in found]}


async def _process_info(ctx: ToolContext, args: dict) -> dict:
    """Inspeciona um processo pelo identificador.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`pid`).

    Returns:
        Um dicionário com os dados do processo.
    """
    try:
        pid = int(args.get("pid"))
    except (TypeError, ValueError):
        return {"success": False, "error": "informe o pid do processo"}
    found = process_info(pid)
    if found is None:
        return {"success": False, "error": f"processo não encontrado: {pid}"}
    return {"success": True, "process": found.as_dict()}


async def _kill_process(ctx: ToolContext, args: dict) -> dict:
    """Encerra um processo autorizado.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`pid`, `force` opcional).

    Returns:
        Um dicionário com o resultado do encerramento.
    """
    try:
        pid = int(args.get("pid"))
    except (TypeError, ValueError):
        return {"success": False, "error": "informe o pid do processo"}
    result = terminate_process(pid, force=bool(args.get("force")))
    emit("process.terminated", {"pid": pid, "success": result.get("success")})
    return result


async def _list_apps(ctx: ToolContext, args: dict) -> dict:
    """Lista os aplicativos instalados.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`match` opcional, `limit` opcional).

    Returns:
        Um dicionário com a lista de aplicativos.
    """
    found = list_apps(match=args.get("match"), limit=int(args.get("limit") or 50))
    return {
        "success": True,
        "count": len(found),
        "apps": [item.as_dict() for item in found],
        "system": current_os(),
    }


async def _launch_app(ctx: ToolContext, args: dict) -> dict:
    """Abre um aplicativo, com argumentos, diretório de trabalho e ambiente controlados.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`, `args`, `cwd`, `env`, `background`).

    Returns:
        Um dicionário com o modo de lançamento e o estado do processo.
    """
    name = str(args.get("name") or args.get("app") or "")
    command_args = args.get("args")
    if isinstance(command_args, str):
        command_args = command_args.split()
    env = args.get("env")
    if not isinstance(env, dict):
        env = None
    result = launch_app(
        name,
        args=command_args or [],
        cwd=str(args.get("cwd")) if args.get("cwd") else None,
        env=env,
        background=bool(args.get("background")),
        manager=TASKS,
    )
    if result.get("success"):
        emit("app.launched", {"app": name, "mode": result.get("mode")})
    return result


async def _open_path(ctx: ToolContext, args: dict) -> dict:
    """Abre um arquivo, pasta ou URL com o manipulador padrão do sistema.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path`).

    Returns:
        Um dicionário com o resultado da abertura.
    """
    target = str(args.get("path") or args.get("url") or "")
    return open_path(target)


async def _task_start(ctx: ToolContext, args: dict) -> dict:
    """Inicia uma tarefa longa em segundo plano e devolve o identificador.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`command`, `cwd`, `env`).

    Returns:
        Um dicionário com o identificador e o estado da tarefa.
    """
    command = args.get("command")
    if isinstance(command, str):
        import shlex

        command = shlex.split(command)
    if not isinstance(command, list) or not command:
        return {"success": False, "error": "informe o comando como lista de argumentos"}
    env = args.get("env") if isinstance(args.get("env"), dict) else None
    try:
        handle = TASKS.start([str(item) for item in command], cwd=str(args.get("cwd")) if args.get("cwd") else None, env=env)
    except (OSError, ValueError) as exc:
        return {"success": False, "error": f"falha ao iniciar a tarefa: {exc}"}
    emit("task.started", {"handle": handle.handle_id, "command": format_command(command)})
    return {"success": True, "handle": handle.as_dict()}


async def _task_status(ctx: ToolContext, args: dict) -> dict:
    """Consulta o estado e a saída parcial de uma tarefa em segundo plano.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`handle_id`).

    Returns:
        Um dicionário com o estado e a saída parcial.
    """
    handle_id = str(args.get("handle_id") or args.get("handle") or "")
    if not handle_id:
        return {"success": False, "error": "informe o handle_id da tarefa"}
    return TASKS.output(handle_id)


async def _task_cancel(ctx: ToolContext, args: dict) -> dict:
    """Cancela uma tarefa em segundo plano.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`handle_id`, `force` opcional).

    Returns:
        Um dicionário com o resultado do cancelamento.
    """
    handle_id = str(args.get("handle_id") or args.get("handle") or "")
    if not handle_id:
        return {"success": False, "error": "informe o handle_id da tarefa"}
    result = TASKS.cancel(handle_id, force=bool(args.get("force")))
    if result.get("success"):
        emit("task.cancelled", {"handle": handle_id})
    return result


async def _list_env(ctx: ToolContext, args: dict) -> dict:
    """Lista as variáveis de ambiente, ocultando os valores sensíveis.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`match` opcional).

    Returns:
        Um dicionário com as variáveis; as secretas aparecem só com o nome.
    """
    needle = str(args.get("match") or "").lower()
    visible: dict[str, str] = {}
    secret: list[str] = []
    for name, value in sorted(os.environ.items()):
        if needle and needle not in name.lower():
            continue
        if is_secret_env(name):
            secret.append(name)
            visible[name] = "[REDACTED]"
        else:
            visible[name] = value
    return {"success": True, "count": len(visible), "env": visible, "redacted": secret}


async def _system_resources(ctx: ToolContext, args: dict) -> dict:
    """Informa uso de disco, memória e carga da CPU.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional para o disco).

    Returns:
        Um dicionário com os recursos do sistema.
    """
    target = str(args.get("path") or ctx.project_root)
    usage = shutil.disk_usage(target if os.path.exists(target) else "/")
    try:
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    except OSError:
        load = (0.0, 0.0, 0.0)
    memory_total = 0
    if current_os() == "macos":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10, check=False
            )
            memory_total = int((completed.stdout or "0").strip() or 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            memory_total = 0
    return {
        "success": True,
        "disk": {
            "path": target,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        },
        "memory": {"total_bytes": memory_total} if memory_total else {"total_bytes": None},
        "load_average": {"1m": load[0], "5m": load[1], "15m": load[2]},
        "cpu_count": os.cpu_count(),
    }


async def _list_ports(ctx: ToolContext, args: dict) -> dict:
    """Lista as conexões de rede ativas do sistema.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`state` opcional, `port` opcional).

    Returns:
        Um dicionário com as conexões encontradas.
    """
    system = current_os()
    if system == "windows":
        command = ["netstat", "-ano"]
    else:
        command = ["lsof", "-nP", "-iTCP"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"ferramenta de rede ausente: {command[0]}",
            "hint": "instale lsof (macOS/Linux) ou use netstat no Windows.",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"falha ao listar portas: {exc}"}
    if completed.returncode != 0 and not (completed.stdout or "").strip():
        return {"success": False, "error": (completed.stderr or "consulta de portas falhou").strip()[:200]}
    wanted_state = str(args.get("state") or "").upper()
    wanted_port = args.get("port")
    rows: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        address = fields[1]
        if ":" not in address:
            continue
        port = address.rsplit(":", 1)[-1]
        state = fields[-1] if len(fields) > 2 else ""
        if wanted_state and state.upper() != wanted_state:
            continue
        if wanted_port and port != str(wanted_port):
            continue
        rows.append({"address": address, "port": port, "state": state, "process": fields[0]})
    return {"success": True, "count": len(rows), "connections": rows[:200]}


async def _check_dependencies(ctx: ToolContext, args: dict) -> dict:
    """Verifica se as dependências pedidas estão disponíveis.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`requirements` lista opcional).

    Returns:
        Um dicionário com o resultado da verificação.
    """
    requirements = args.get("requirements")
    if isinstance(requirements, str):
        requirements = [item.strip() for item in requirements.split(",") if item.strip()]
    if not isinstance(requirements, list) or not requirements:
        adapter = get_adapter()
        requirements = [f"binary:{tool}" for tool in adapter.available_tools]
    result = check_requirements([str(item) for item in requirements])
    return {
        "success": True,
        "available": result.available,
        "missing": result.missing,
        "hints": result.hints,
        "details": result.details,
        "environment": environment_report(),
    }


async def _download(ctx: ToolContext, args: dict) -> dict:
    """Baixa um arquivo para a pasta do projeto, com verificação de tamanho e destino.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`url`, `path` opcional, `max_bytes` opcional).

    Returns:
        Um dicionário com o caminho do arquivo baixado.
    """
    url = str(args.get("url") or "")
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "só http e https são aceitos"}
    import httpx

    max_bytes = int(args.get("max_bytes") or 20 * 1024 * 1024)
    target = args.get("path")
    if target:
        resolved, error = _resolve(ctx, str(target))
        if error:
            return error
    else:
        resolved = _root(ctx) / "downloads" / (url.rsplit("/", 1)[-1] or "download.bin")
    try:
        with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with resolved.open("wb") as handle:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        handle.close()
                        resolved.unlink(missing_ok=True)
                        return {"success": False, "error": f"download maior que o limite de {max_bytes} bytes"}
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"download falhou: {exc}"}
    except OSError as exc:
        return {"success": False, "error": f"falha ao gravar o download: {exc}"}
    return {"success": True, "path": str(resolved), "bytes": written, "url": url}


async def _file_hash(ctx: ToolContext, args: dict) -> dict:
    """Calcula o resumo de um arquivo (sha256 por padrão).

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path`, `algorithm` opcional).

    Returns:
        Um dicionário com o resumo e o tamanho do arquivo.
    """
    resolved, error = _resolve(ctx, str(args.get("path") or ""))
    if error:
        return error
    if not resolved.is_file():
        return {"success": False, "error": f"arquivo não encontrado: {resolved.name}"}
    algorithm = str(args.get("algorithm") or "sha256").lower()
    try:
        digest = hashlib.new(algorithm)
    except ValueError:
        return {"success": False, "error": f"algoritmo desconhecido: {algorithm}"}
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "success": True,
        "path": str(resolved),
        "algorithm": algorithm,
        "hash": digest.hexdigest(),
        "bytes": resolved.stat().st_size,
    }


async def _archive(ctx: ToolContext, args: dict) -> dict:
    """Compacta uma pasta ou um arquivo em `.zip` ou `.tar.gz`.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`source`, `target` opcional, `format` opcional).

    Returns:
        Um dicionário com o caminho do arquivo compactado.
    """
    source, error = _resolve(ctx, str(args.get("source") or ""))
    if error:
        return error
    if not source.exists():
        return {"success": False, "error": f"origem inexistente: {source.name}"}
    fmt = str(args.get("format") or "zip").lower()
    target = args.get("target")
    resolved = (
        _resolve(ctx, str(target))[0]
        if target
        else _root(ctx) / f"{source.name}.{'zip' if fmt == 'zip' else 'tar.gz'}"
    )
    try:
        if fmt == "zip":
            with zipfile.ZipFile(resolved, "w", zipfile.ZIP_DEFLATED) as bundle:
                if source.is_dir():
                    for path in sorted(source.rglob("*")):
                        if path.is_file():
                            bundle.write(path, path.relative_to(source))
                else:
                    bundle.write(source, source.name)
        else:
            mode = "w:gz" if fmt in {"tar.gz", "tgz"} else "w"
            with tarfile.open(resolved, mode) as bundle:
                bundle.add(source, arcname=source.name)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {"success": False, "error": f"falha ao compactar: {exc}"}
    return {"success": True, "path": str(resolved), "bytes": resolved.stat().st_size, "format": fmt}


async def _extract_archive(ctx: ToolContext, args: dict) -> dict:
    """Extrai um arquivo compactado dentro da pasta do projeto.

    A extração recusa caminhos que escapem do destino — o mesmo cuidado do *zip slip*.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path`, `target` opcional).

    Returns:
        Um dicionário com a lista de arquivos extraídos.
    """
    source, error = _resolve(ctx, str(args.get("path") or ""))
    if error:
        return error
    if not source.is_file():
        return {"success": False, "error": f"arquivo inexistente: {source.name}"}
    destination = (
        _resolve(ctx, str(args.get("target")))[0]
        if args.get("target")
        else _root(ctx) / "extracted" / source.stem
    )
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    extracted: list[str] = []
    try:
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as bundle:
                for member in bundle.namelist():
                    target_path = (destination / member).resolve()
                    if root not in target_path.parents and target_path != root:
                        return {"success": False, "error": f"o arquivo '{member}' escaparia do destino"}
                bundle.extractall(destination)
                extracted = bundle.namelist()
        elif tarfile.is_tarfile(source):
            with tarfile.open(source) as bundle:
                for member in bundle.getmembers():
                    target_path = (destination / member.name).resolve()
                    if root not in target_path.parents and target_path != root:
                        return {"success": False, "error": f"o arquivo '{member.name}' escaparia do destino"}
                bundle.extractall(destination, filter="data")
                extracted = [member.name for member in bundle.getmembers()]
        else:
            return {"success": False, "error": "formato de compactação não reconhecido"}
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {"success": False, "error": f"falha ao extrair: {exc}"}
    return {"success": True, "target": str(destination), "count": len(extracted), "files": extracted[:200]}


async def _http_request(ctx: ToolContext, args: dict) -> dict:
    """Faz uma requisição HTTP para diagnóstico ou integração.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`url`, `method`, `headers`, `body`, `timeout`).

    Returns:
        Um dicionário com o status e o corpo da resposta (limitado).
    """
    import httpx

    url = str(args.get("url") or "")
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "só http e https são aceitos"}
    method = str(args.get("method") or "GET").upper()
    headers = args.get("headers") if isinstance(args.get("headers"), dict) else {}
    body = args.get("body")
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
    timeout = float(args.get("timeout") or 30)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(method, url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"requisição falhou: {exc}"}
    text = response.text[:MAX_HTTP_BODY]
    return {
        "success": response.status_code < 400,
        "status_code": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "body": text,
        "truncated": len(response.text) > MAX_HTTP_BODY,
    }


def register_all(registry: ToolRegistry) -> None:
    """Registra as ferramentas de sistema, processos, aplicativos e rede.

    Args:
        registry: registro onde as ferramentas são cadastradas.
    """
    specs = [
        ToolSpec(
            id="system_diagnose",
            description="Diagnostica sistema, sessão gráfica, permissões e dependências",
            input_schema={},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira os campos 'system' e 'permissions.blocked'",
        ),
        ToolSpec(
            id="list_processes",
            description="Lista processos em execução",
            input_schema={"match": "str?", "limit": "int?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="process_info",
            description="Inspeciona um processo pelo pid",
            input_schema={"pid": "int"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'process'",
        ),
        ToolSpec(
            id="kill_process",
            description="Encerra um processo (SIGTERM; force elimina)",
            input_schema={"pid": "int", "force": "bool?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.signal"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'terminated'",
        ),
        ToolSpec(
            id="list_apps",
            description="Lista aplicativos instalados",
            input_schema={"match": "str?", "limit": "int?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="launch_app",
            description="Abre um aplicativo, com argumentos, cwd e ambiente",
            input_schema={"name": "str", "args": "list[str]?", "cwd": "str?", "env": "dict?", "background": "bool?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.spawn"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confirme com process_info ou list_processes que o processo existe",
        ),
        ToolSpec(
            id="open_path",
            description="Abre arquivo, pasta ou URL no programa padrão",
            input_schema={"path": "str"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.EXECUTE.value,
            permissions=["process.spawn"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'exit_code'",
        ),
        ToolSpec(
            id="task_start",
            description="Inicia tarefa longa em segundo plano e devolve handle_id",
            input_schema={"command": "list[str]", "cwd": "str?", "env": "dict?"},
            family=ToolFamily.COMMAND.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.spawn"],
            side_effects=True,
            execution=ExecutionMode.BACKGROUND.value,
            verify="consulte task_status até o processo terminar",
        ),
        ToolSpec(
            id="task_status",
            description="Estado e saída parcial de uma tarefa em segundo plano",
            input_schema={"handle_id": "str"},
            family=ToolFamily.COMMAND.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira 'handle.running' e 'stdout'",
        ),
        ToolSpec(
            id="task_cancel",
            description="Cancela uma tarefa em segundo plano",
            input_schema={"handle_id": "str", "force": "bool?"},
            family=ToolFamily.COMMAND.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.signal"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira 'handle.running'",
        ),
        ToolSpec(
            id="list_env",
            description="Lista variáveis de ambiente; segredos aparecem como [REDACTED]",
            input_schema={"match": "str?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="system_resources",
            description="Uso de disco, memória e carga da CPU",
            input_schema={"path": "str?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira 'disk.used_percent'",
        ),
        ToolSpec(
            id="list_ports",
            description="Lista conexões de rede ativas",
            input_schema={"state": "str?", "port": "str?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="check_dependencies",
            description="Verifica se dependências estão disponíveis",
            input_schema={"requirements": "list[str]?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'missing'",
        ),
        ToolSpec(
            id="download_file",
            description="Baixa um arquivo para o projeto, com limite de tamanho",
            input_schema={"url": "str", "path": "str?", "max_bytes": "int?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["fs.write", "net.fetch"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'bytes'",
        ),
        ToolSpec(
            id="file_hash",
            description="Calcula o resumo de um arquivo",
            input_schema={"path": "str", "algorithm": "str?"},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'hash'",
        ),
        ToolSpec(
            id="archive_files",
            description="Compacta arquivos ou pasta em zip ou tar.gz",
            input_schema={"source": "str", "target": "str?", "format": "str?"},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'bytes'",
        ),
        ToolSpec(
            id="extract_archive",
            description="Extrai um arquivo compactado dentro do projeto",
            input_schema={"path": "str", "target": "str?"},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="http_request",
            description="Requisição HTTP para diagnóstico e integração",
            input_schema={"url": "str", "method": "str?", "headers": "dict?", "body": "str?", "timeout": "int?"},
            family=ToolFamily.SYSTEM.value,
            risk=ToolRisk.EXECUTE.value,
            permissions=["net.fetch"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            hard_timeout_seconds=90,
            verify="confira 'status_code'",
        ),
    ]
    handlers = {
        "system_diagnose": _diagnose,
        "list_processes": _list_processes,
        "process_info": _process_info,
        "kill_process": _kill_process,
        "list_apps": _list_apps,
        "launch_app": _launch_app,
        "open_path": _open_path,
        "task_start": _task_start,
        "task_status": _task_status,
        "task_cancel": _task_cancel,
        "list_env": _list_env,
        "system_resources": _system_resources,
        "list_ports": _list_ports,
        "check_dependencies": _check_dependencies,
        "download_file": _download,
        "file_hash": _file_hash,
        "archive_files": _archive,
        "extract_archive": _extract_archive,
        "http_request": _http_request,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])


__all__ = ["TASKS", "register_all"]
