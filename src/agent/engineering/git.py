"""
Arquivo: src/agent/engineering/git.py
Nome: git.py
Propósito: inspecionar o repositório Git: estado, branch, histórico e diferenças.
Responsabilidade: camada de infraestrutura — leitura do repositório sem alterar o trabalho do usuário.
Componentes: git_status, git_branch, git_log, git_diff, is_repository.
Dependências: subprocess.
Observações: as funções são somente leitura; nada aqui altera índice, árvore ou histórico.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

#: Tempo limite das consultas Git, em segundos.
_TIMEOUT = 30


def _run(root: str | Path, args: list[str]) -> subprocess.CompletedProcess:
    """Executa um comando Git na pasta do projeto.

    Args:
        root: raiz do repositório.
        args: argumentos do Git, sem o executável.

    Returns:
        O resultado da execução; em falha de sistema, um resultado sintético com código 127.
    """
    command = ["git", "-C", str(root), *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, "", "git não está instalado")
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def is_repository(root: str | Path) -> bool:
    """Indica se a pasta é um repositório Git.

    Args:
        root: pasta a verificar.

    Returns:
        `True` quando a pasta (ou um diretório acima dela) é um repositório.
    """
    completed = _run(root, ["rev-parse", "--is-inside-work-tree"])
    return completed.returncode == 0 and (completed.stdout or "").strip() == "true"


def git_status(root: str | Path) -> dict[str, Any]:
    """Estado do repositório: arquivos modificados, staged e não rastreados.

    A saída é em formato porcelain, estável entre versões do Git.

    Args:
        root: raiz do repositório.

    Returns:
        Um dicionário com a lista de alterações e a branch atual.
    """
    if not is_repository(root):
        return {"success": False, "error": "não é um repositório git", "changes": []}
    status = _run(root, ["status", "--porcelain=v1", "--branch"])
    if status.returncode != 0:
        return {"success": False, "error": (status.stderr or "git status falhou").strip()[:300], "changes": []}
    changes: list[dict[str, str]] = []
    branch = ""
    for line in (status.stdout or "").splitlines():
        if line.startswith("##"):
            branch = line[2:].strip()
            continue
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip()
        changes.append(
            {
                "status": code.strip() or "?",
                "path": path,
                "staged": code[0] not in {" ", "?"},
            }
        )
    return {"success": True, "branch": branch, "changes": changes, "count": len(changes)}


def git_branch(root: str | Path) -> dict[str, Any]:
    """Branches do repositório, com a branch atual em destaque.

    Args:
        root: raiz do repositório.

    Returns:
        Um dicionário com a branch atual e a lista de branches.
    """
    if not is_repository(root):
        return {"success": False, "error": "não é um repositório git", "branches": []}
    completed = _run(root, ["branch", "--format=%(refname:short)|%(upstream:short)|%(HEAD)"])
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "git branch falhou").strip()[:300], "branches": []}
    branches: list[dict[str, Any]] = []
    current = ""
    for line in (completed.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name, upstream, head = parts[0], parts[1], parts[2]
        if head == "*":
            current = name
        branches.append({"name": name, "upstream": upstream, "current": head == "*"})
    return {"success": True, "current": current, "branches": branches, "count": len(branches)}


def git_log(root: str | Path, limit: int = 20, path: str | None = None) -> dict[str, Any]:
    """Histórico recente de commits.

    Args:
        root: raiz do repositório.
        limit: quantidade máxima de commits.
        path: caminho opcional para restringir o histórico.

    Returns:
        Um dicionário com a lista de commits (hash, autor, data e mensagem).
    """
    if not is_repository(root):
        return {"success": False, "error": "não é um repositório git", "commits": []}
    args = ["log", f"-{max(1, int(limit))}", "--format=%H|%an|%aI|%s"]
    if path:
        args += ["--", path]
    completed = _run(root, args)
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "git log falhou").strip()[:300], "commits": []}
    commits: list[dict[str, str]] = []
    for line in (completed.stdout or "").splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        commits.append({"hash": parts[0][:12], "author": parts[1], "date": parts[2], "message": parts[3]})
    return {"success": True, "commits": commits, "count": len(commits)}


def git_diff(root: str | Path, *, staged: bool = False, path: str | None = None, stat: bool = True) -> dict[str, Any]:
    """Diferenças do repositório.

    Args:
        root: raiz do repositório.
        staged: quando `True`, mostra só o que está no índice.
        path: caminho opcional para restringir o diff.
        stat: quando `True`, devolve o resumo por arquivo.

    Returns:
        Um dicionário com o diff textual e, quando pedido, o resumo por arquivo.
    """
    if not is_repository(root):
        return {"success": False, "error": "não é um repositório git", "diff": ""}
    args = ["diff"]
    if staged:
        args.append("--staged")
    if stat:
        args.append("--stat")
    if path:
        args += ["--", path]
    completed = _run(root, args)
    if completed.returncode != 0:
        return {"success": False, "error": (completed.stderr or "git diff falhou").strip()[:300], "diff": ""}
    return {
        "success": True,
        "diff": completed.stdout or "",
        "staged": staged,
        "path": path or "",
        "changed": bool((completed.stdout or "").strip()),
    }
