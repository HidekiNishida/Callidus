# src/agent/services/fs_browse.py — escolha de pasta do projeto
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _roots() -> list[Path]:
    home = Path.home().resolve()
    roots = [home]
    for extra in (Path("/Users"), Path("/Volumes"), Path("/home")):
        if extra.is_dir():
            roots.append(extra.resolve())
    return roots


def _allowed(path: Path) -> bool:
    resolved = path.resolve()
    for root in _roots():
        if resolved == root or root in resolved.parents:
            return True
    return False


def browse_directories(path: str | None = None) -> dict:
    target = Path(path).expanduser() if path else Path.home()
    try:
        target = target.resolve()
    except OSError as exc:
        raise ValueError("pasta inválida") from exc
    if not _allowed(target) or not target.is_dir():
        raise ValueError("pasta fora do alcance permitido")
    parent = target.parent if target != target.parent and _allowed(target.parent) else None
    entries: list[dict] = []
    try:
        children = sorted(target.iterdir(), key=lambda item: item.name.lower())
    except PermissionError:
        children = []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            if not child.is_dir() or child.is_symlink():
                continue
            resolved = child.resolve()
        except OSError:
            continue
        if not _allowed(resolved):
            continue
        entries.append({"name": child.name, "path": str(resolved)})
        if len(entries) >= 200:
            break
    return {
        "path": str(target),
        "parent": str(parent) if parent else None,
        "entries": entries,
    }


def create_directory(path: str, name: str) -> dict:
    """Cria uma pasta dentro de `path` (que precisa estar no alcance permitido).

    Devolve a pasta criada e a listagem atualizada, para o seletor seguir sem recarregar.
    """
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except OSError as exc:
        raise ValueError("pasta inválida") from exc
    if not _allowed(base) or not base.is_dir():
        raise ValueError("pasta fora do alcance permitido")
    clean = (name or "").strip()
    if not clean or "/" in clean or clean in {".", ".."}:
        raise ValueError("nome de pasta inválido")
    target = base / clean
    try:
        target.mkdir(parents=False, exist_ok=True)
    except FileExistsError as exc:
        raise ValueError("a pasta já existe") from exc
    except OSError as exc:
        raise ValueError(f"não foi possível criar a pasta: {exc.strerror or exc}") from exc
    listing = browse_directories(str(base))
    listing["created"] = str(target.resolve())
    return listing


def pick_folder_native() -> str:
    if sys.platform != "darwin":
        raise ValueError("o seletor nativo só está disponível no macOS")
    proc = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Escolha a pasta do projeto")',
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    chosen = (proc.stdout or "").strip()
    if proc.returncode != 0 or not chosen:
        raise ValueError("seleção cancelada")
    path = Path(chosen).resolve()
    if not _allowed(path) or not path.is_dir():
        raise ValueError("pasta fora do alcance permitido")
    return str(path)
