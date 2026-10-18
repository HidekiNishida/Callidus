# src/agent/verification/fingerprint.py — impressão digital dos arquivos que uma verificação avaliou
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
_SKIP_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".pyc")
_MAX_FILES = 2000
_HASH_LIMIT = 2_000_000


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
    return []


def _files(base: Path, rel: str) -> list[Path]:
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
    """Hash do conteúdo (ou tamanho e data, acima de 2 MB) dos arquivos sob `paths`; arquivo ausente entra
    como ausente, então criar, apagar ou mudar qualquer um muda a impressão."""
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
                digest.update(name.encode())
                if stat.st_size <= _HASH_LIMIT:
                    digest.update(hashlib.sha256(path.read_bytes()).digest())
                else:
                    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
            except OSError:
                digest.update(b"<ilegivel>")
    return digest.hexdigest()


def snapshot(root: str, spec: dict[str, Any], tool_args: dict[str, Any] | None = None) -> dict[str, Any] | None:
    paths = artifact_paths(spec, tool_args)
    if not paths:
        return None
    return {"root": root, "paths": paths, "fingerprint": fingerprint(root, paths)}


def is_current(artifacts: dict[str, Any] | None) -> bool:
    """Evidência sem impressão (antiga ou que não depende de arquivo) continua válida."""
    if not artifacts or not artifacts.get("fingerprint"):
        return True
    return fingerprint(artifacts.get("root") or ".", list(artifacts.get("paths") or [])) == artifacts["fingerprint"]
