"""
Arquivo: src/agent/services/fs_browse.py
Nome: fs_browse.py
Propósito: listar e criar pastas para a escolha da pasta de trabalho do projeto.
Responsabilidade: camada de aplicação — navegação do sistema de arquivos dentro do alcance permitido.
Componentes: browse_directories, create_directory, pick_folder_native.
Dependências: pathlib, subprocess.
Observações: a navegação só alcança a pasta do usuário e as raízes de disco usuais.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _roots() -> list[Path]:
    """Raízes que a navegação pode alcançar.

    Returns:
        A lista de raízes permitidas (pasta do usuário e raízes de disco usuais).
    """
    home = Path.home().resolve()
    roots = [home]
    for extra in (Path("/Users"), Path("/Volumes"), Path("/home")):
        if extra.is_dir():
            roots.append(extra.resolve())
    return roots


def _allowed(path: Path) -> bool:
    """Indica se um caminho está dentro das raízes permitidas.

    Args:
        path: caminho a verificar.

    Returns:
        `True` quando o caminho está sob uma raiz permitida.
    """
    resolved = path.resolve()
    for root in _roots():
        if resolved == root or root in resolved.parents:
            return True
    return False


def browse_directories(path: str | None = None) -> dict:
    """Lista as subpastas de um diretório permitido.

    Args:
        path: pasta a listar; por padrão, a pasta do usuário.

    Returns:
        Um dicionário com o caminho atual, o caminho pai e as entradas encontradas.

    Raises:
        ValueError: quando a pasta é inválida ou está fora do alcance permitido.
    """
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

    Args:
        path: pasta base, que precisa estar no alcance permitido.
        name: nome da pasta a criar.

    Returns:
        A listagem da pasta base com o campo `created` preenchido.

    Raises:
        ValueError: quando a base é inválida, o nome não serve ou a pasta já existe.
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
    """Abre o seletor de pastas nativo do macOS.

    Returns:
        O caminho absoluto da pasta escolhida.

    Raises:
        ValueError: quando o seletor não está disponível, foi cancelado ou escolheu fora do alcance.
    """
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
