#!/usr/bin/env python3
"""Python 3.14 ignora .pth cujo nome começa com '_' ou '.'.

O editable do setuptools/hatch gera exatamente esse tipo de arquivo, então
`import agent` falha mesmo após `pip install -e`. Este script grava um .pth
visível apontando para src/.
"""
from __future__ import annotations

import os
import site
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def main() -> None:
    if not (SRC / "agent").is_dir():
        raise SystemExit(f"pacote não encontrado em {SRC}")
    paths = site.getsitepackages()
    if not paths:
        paths = [p for p in sys.path if p.endswith("site-packages")]
    if not paths:
        raise SystemExit("site-packages não encontrado; ative o .venv")
    target = Path(paths[0]) / "agente-local-src.pth"
    target.write_text(str(SRC) + "\n", encoding="utf-8")
    # Python 3.14 ignora .pth com a flag UF_HIDDEN (comum em arquivos criados por ferramentas).
    if hasattr(stat, "UF_HIDDEN"):
        try:
            os.chflags(target, os.stat(target).st_flags & ~stat.UF_HIDDEN)
        except OSError:
            pass
    print(f"gravado {target}")


if __name__ == "__main__":
    main()
