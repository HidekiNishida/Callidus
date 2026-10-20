"""
Arquivo: src/agent/verification/fingerprint.py
Nome: fingerprint.py
Propósito: calcular a impressão digital dos arquivos de que uma verificação depende.
Responsabilidade: camada de aplicação — detecção de artefato obsoleto pela mudança do disco.
Componentes: artifact_paths, fingerprint, snapshot, is_current.
Dependências: hashlib, pathlib.
Observações: a impressão é barata o bastante para rodar a cada passo; arquivo ausente entra como ausente.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
_SKIP_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".pyc")
_MAX_FILES = 2000


def artifact_paths(spec: dict[str, Any], tool_args: dict[str, Any] | None = None) -> list[str]:
    """Caminhos de que o resultado da verificação depende; vazio quando não depende de arquivo."""
    vtype = spec.get("type") or spec.get("verification")
    if vtype == "file_contains":
        return [spec.get("path") or ""]
    if vtype in {"script", "run_script"}:
        return [spec.get("path") or (tool_args or {}).get("path") or ""]
    if vtype == "pytest":
        return [spec.get("path") or "."]
    if vtype in {"command", "run_command"}:
        return [spec.get("cwd") or "."]
    # Verificadores que leem um arquivo específico também dependem do estado desse arquivo:
    # sem a impressão, a evidência continuaria válida depois de o arquivo sumir ou mudar.
    if vtype in {"file_exists", "syntax"}:
        return [spec.get("path") or ""]
    if vtype in {"static_analysis", "ast_check"}:
        return [spec.get("path") or "."]
    return []


def _files(base: Path, rel: str) -> list[Path]:
    """Lista os arquivos relevantes de um caminho relativo à raiz.

    Args:
        base: raiz do projeto.
        rel: caminho relativo; vazio significa a própria raiz.

    Returns:
        A lista de arquivos considerados, ignorando caches, bancos e dependências.
    """
    target = (base / rel).resolve() if rel else base
    if target.is_file():
        return [target]
    if not target.is_dir():
        return []
    found = []
    for path in sorted(target.rglob("*")):
        if (
            path.is_file()
            and not path.name.endswith(_SKIP_SUFFIXES)
            and not any(part in _SKIP_DIRS for part in path.relative_to(target).parts)
        ):
            found.append(path)
            if len(found) >= _MAX_FILES:
                break
    return found


def fingerprint(root: str, paths: list[str]) -> str:
    """Hash de nome, tamanho e data de modificação dos arquivos sob `paths` (barato o bastante para rodar a
    cada passo); arquivo ausente entra como ausente, então criar, apagar ou mudar qualquer um muda a
    impressão. Regravar o mesmo conteúdo também muda: custa só uma reverificação."""
    base = Path(root).resolve()
    digest = hashlib.sha256()
    for rel in sorted(set(paths)):
        digest.update(f"\0{rel}\0".encode())
        files = _files(base, rel)
        if not files:
            digest.update(b"<ausente>")
        for path in files:
            try:
                stat = path.stat()
                name = str(path.relative_to(base)) if path.is_relative_to(base) else str(path)
                digest.update(f"{name}:{stat.st_size}:{stat.st_mtime_ns}".encode())
            except OSError:
                digest.update(b"<ilegivel>")
    return digest.hexdigest()


def snapshot(root: str, spec: dict[str, Any], tool_args: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Registra os artefatos avaliados e a impressão digital correspondente.

    Args:
        root: raiz do projeto avaliado.
        spec: especificação da verificação.
        tool_args: argumentos da ferramenta usados na verificação.

    Returns:
        O snapshot com raiz, caminhos e impressão; `None` quando a verificação não depende de arquivo.
    """
    paths = artifact_paths(spec, tool_args)
    if not paths:
        return None
    return {"root": root, "paths": paths, "fingerprint": fingerprint(root, paths)}


def is_current(artifacts: dict[str, Any] | None) -> bool:
    """Indica se a evidência ainda corresponde ao estado do disco.

    Args:
        artifacts: snapshot gravado com a evidência.

    Returns:
        `True` quando a evidência continua válida; `False` quando os artefatos mudaram.
    """
    if not artifacts or not artifacts.get("fingerprint"):
        return True
    return fingerprint(artifacts.get("root") or ".", list(artifacts.get("paths") or [])) == artifacts["fingerprint"]
