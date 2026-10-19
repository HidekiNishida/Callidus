#!/usr/bin/env python3
"""Faz `import agent` funcionar num venv, apesar do Python 3.14.

Dois problemas se combinam aqui:

1. O editable do setuptools grava um `.pth` cujo nome começa com `_`, e o
   Python 3.14 pula `.pth` assim-named.
2. No macOS, um agente externo aplica a flag `UF_HIDDEN` nos arquivos de
   `site-packages` — e o Python 3.14 também pula `.pth` ocultos. Como a flag
   volta sozinha em ~1s, limpar o atributo não resolve.

Por isso o script usa duas vias:

- grava `callidus-src.pth` com o caminho de `src/` (via padrão), e
- cria um link simbólico `site-packages/agent` → `src/agent`.

O link simbólico resolve os dois problemas: o importador do Python ignora a
flag `UF_HIDDEN`, e o nome do alvo não começa com `_`.

Uso: python scripts/fix-python314-editable.py
"""
from __future__ import annotations

import os
import site
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PTH_NAME = "callidus-src.pth"
LEGACY_PTH_NAME = "agente-local-src.pth"


def _site_packages() -> Path:
    paths = site.getsitepackages()
    if not paths:
        paths = [p for p in sys.path if p.endswith("site-packages")]
    if not paths:
        raise SystemExit("site-packages não encontrado; ative o .venv")
    return Path(paths[0])


def _unhide(path: Path) -> None:
    """Remove a flag UF_HIDDEN (macOS) do arquivo, se houver."""
    if not hasattr(stat, "UF_HIDDEN"):
        return
    try:
        flags = os.stat(path).st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(path, flags & ~stat.UF_HIDDEN)
    except OSError:
        pass


def _write_pth(site_packages: Path) -> Path:
    target = site_packages / PTH_NAME
    target.write_text(str(SRC) + "\n", encoding="utf-8")
    _unhide(target)
    return target


def _write_symlink(site_packages: Path) -> Path:
    """Link simbólico `site-packages/agent` → `src/agent`."""
    link = site_packages / "agent"
    target = SRC / "agent"
    if link.is_symlink() and link.resolve() == target.resolve():
        return link
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            return link  # instalação real; não mexe.
        link.unlink()
    link.symlink_to(target, target_is_directory=True)
    return link


def main() -> None:
    if not (SRC / "agent").is_dir():
        raise SystemExit(f"pacote não encontrado em {SRC}")
    site_packages = _site_packages()

    pth = _write_pth(site_packages)
    link = _write_symlink(site_packages)

    legacy = site_packages / LEGACY_PTH_NAME
    if legacy.exists():
        legacy.unlink()

    # O editable do setuptools também gera .pth; garante que nenhum fique oculto.
    for editable in site_packages.glob("__editable__*.pth"):
        _unhide(editable)

    print(f"gravado {pth}")
    print(f"link {link} → {SRC / 'agent'}")


if __name__ == "__main__":
    main()
