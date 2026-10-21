"""
Arquivo: src/agent/tools/devtools.py
Nome: devtools.py
Propósito: expor ao agente a descoberta de projetos, o Git e a execução de verificações de qualidade.
Responsabilidade: camada de apresentação — handlers das ferramentas de engenharia de software.
Componentes: register_all e os handlers de projeto, comandos, histórico Git e verificações.
Dependências: agent.engineering, agent.tools.registry.
Observações: a descoberta é somente leitura; executar lint, teste ou build exige aprovação.
"""
from __future__ import annotations

import shlex
from pathlib import Path

from agent.engineering.discovery import detect_project, discover_commands, read_manifest
from agent.engineering.git import git_branch, git_log
from agent.engineering.quality import run_check
from agent.observability import emit
from agent.tools.contracts import ExecutionMode, ToolFamily, ToolRisk
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec


async def _project_info(ctx: ToolContext, args: dict) -> dict:
    """Descreve o projeto: linguagem, manifestos, gerenciadores e instruções.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional).

    Returns:
        Um dicionário com a descoberta do projeto.
    """
    root = str(args.get("path") or ctx.project_root)
    return {"success": True, "project": detect_project(root).as_dict()}


async def _project_commands(ctx: ToolContext, args: dict) -> dict:
    """Deriva os comandos de instalação, build, lint, teste e execução.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional).

    Returns:
        Um dicionário com os comandos e a origem de cada um.
    """
    root = str(args.get("path") or ctx.project_root)
    return {"success": True, **discover_commands(root)}


async def _read_manifest(ctx: ToolContext, args: dict) -> dict:
    """Lê um manifesto de projeto (package.json, pyproject.toml, Cargo.toml).

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path`).

    Returns:
        Um dicionário com os campos de alto nível do manifesto.
    """
    path = str(args.get("path") or "")
    if not path:
        return {"success": False, "error": "informe o caminho do manifesto"}
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path(ctx.project_root) / resolved
    if not resolved.is_file():
        return {"success": False, "error": f"manifesto inexistente: {path}"}
    return {"success": True, "path": str(resolved), "manifest": read_manifest(resolved)}


async def _git_branch(ctx: ToolContext, args: dict) -> dict:
    """Branches do repositório Git, com a atual em destaque.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional).

    Returns:
        Um dicionário com a lista de branches.
    """
    return git_branch(str(args.get("path") or ctx.project_root))


async def _git_log(ctx: ToolContext, args: dict) -> dict:
    """Histórico recente de commits.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional, `limit` opcional).

    Returns:
        Um dicionário com a lista de commits.
    """
    root = str(args.get("path") or ctx.project_root)
    return git_log(root, limit=int(args.get("limit") or 20))


async def _run_check(ctx: ToolContext, args: dict) -> dict:
    """Executa uma verificação de qualidade (lint, teste ou build) e resume o resultado.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`command`, `cwd` opcional, `timeout` opcional).

    Returns:
        Um dicionário com o código de saída, a saída e o resumo interpretado.
    """
    command = args.get("command")
    if isinstance(command, str):
        command = shlex.split(command)
    if not isinstance(command, list) or not command:
        return {"success": False, "error": "informe o comando como lista de argumentos"}
    result = run_check(
        [str(item) for item in command],
        cwd=str(args.get("cwd") or ctx.project_root),
        timeout=float(args.get("timeout") or 300),
    )
    emit("check.completed", {"command": command[0], "success": result.get("success")})
    return result


def register_all(registry: ToolRegistry) -> None:
    """Registra as ferramentas de engenharia de software.

    Args:
        registry: registro onde as ferramentas são cadastradas.
    """
    specs = [
        ToolSpec(
            id="project_info",
            description="Identifica linguagem, manifestos, gerenciadores e instruções do projeto",
            input_schema={"path": "str?"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'project.languages'",
        ),
        ToolSpec(
            id="project_commands",
            description="Deriva os comandos de install, build, lint, test e run do projeto",
            input_schema={"path": "str?"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'commands'",
        ),
        ToolSpec(
            id="read_manifest",
            description="Lê package.json, pyproject.toml ou Cargo.toml",
            input_schema={"path": "str"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'manifest'",
        ),
        ToolSpec(
            id="git_branch",
            description="Branches do repositório Git",
            input_schema={"path": "str?"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'current'",
        ),
        ToolSpec(
            id="git_log",
            description="Histórico recente de commits",
            input_schema={"path": "str?", "limit": "int?"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="run_check",
            description="Executa lint, teste ou build e resume o resultado real",
            input_schema={"command": "list[str]", "cwd": "str?", "timeout": "int?"},
            family=ToolFamily.ENGINEERING.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.spawn"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            hard_timeout_seconds=600,
            verify="confira 'status' e 'exit_code'",
        ),
    ]
    handlers = {
        "project_info": _project_info,
        "project_commands": _project_commands,
        "read_manifest": _read_manifest,
        "git_branch": _git_branch,
        "git_log": _git_log,
        "run_check": _run_check,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])


__all__ = ["register_all"]
