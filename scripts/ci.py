#!/usr/bin/env python3
"""
Arquivo: scripts/ci.py
Nome: ci.py
Propósito: rodar, num único comando, todos os portões de qualidade do Callidus.
Responsabilidade: script de verificação — agrega lint, testes Python, testes da interface e as verificações de documentação e de regras.
Componentes: Passo, passos, rodar_passo, main.
Dependências: argparse, shutil, subprocess, sys, time, pathlib (somente biblioteca padrão).
Observações: roda todos os passos mesmo quando um falha, para mostrar o quadro inteiro; sai com 1 se qualquer passo obrigatório falhar. Ferramenta ausente (ruff, node) reprova o passo em vez de ser ignorada em silêncio.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass(frozen=True)
class Passo:
    """Um portão de qualidade: nome, comando e a regra que ele fiscaliza."""

    nome: str
    comando: list[str]
    regra: str
    lento: bool = False
    exige: str = ""
    reprova_se_saida_contem: str = ""


def passos() -> list[Passo]:
    """Lista os portões na ordem em que rodam (do mais barato ao mais caro).

    Returns:
        Os passos do comando único de verificação.
    """
    web_tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests" / "web").glob("*.test.mjs"))
    return [
        Passo("lint (ruff)", [PY, "-m", "ruff", "check", "src", "tests", "scripts"],
              "código sem erro de lint (AGENTS.md §16)", exige="ruff"),
        Passo("cabeçalhos", [PY, "scripts/padronizar_cabecalhos.py", "--check", "src", "tests", "scripts"],
              "cabeçalho obrigatório (AGENTS.md §3)", reprova_se_saida_contem="precisa de cabeçalho"),
        Passo("links e âncoras", [PY, "scripts/check_docs.py"], "documentação navegável (AGENTS.md §11)"),
        Passo("referências", [PY, "scripts/check_references.py"], "nada citado que não exista (AGENTS.md §12)"),
        Passo("estrutura Markdown", [PY, "scripts/check_markdown.py"], "padrão de forma (docs/regras/documentacao.md)"),
        Passo("resume.md", [PY, "scripts/resume.py", "check"], "resumo vivo sincronizado (AGENTS.md §13)"),
        Passo("testes da interface", ["node", "--test", *web_tests], "comportamento da SPA (AGENTS.md §10)",
              exige="node"),
        Passo("testes Python", [PY, "-m", "pytest", "-q"], "comportamento e contratos (AGENTS.md §9 e §10)",
              lento=True, exige="pytest"),
    ]


def _disponivel(exige: str) -> bool:
    """Diz se a ferramenta exigida pelo passo está instalada."""
    if not exige:
        return True
    if exige == "node":
        return shutil.which("node") is not None
    probe = subprocess.run([PY, "-c", f"import {exige}"], cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def rodar_passo(passo: Passo, verbose: bool) -> tuple[bool, float, str]:
    """Executa um passo e devolve se passou, quanto durou e um resumo.

    Args:
        passo: o portão a executar.
        verbose: mostra a saída completa do comando.

    Returns:
        (passou, segundos, resumo de uma linha ou saída final quando reprova).
    """
    if not _disponivel(passo.exige):
        dica = "instale o Node.js" if passo.exige == "node" else f"pip install {passo.exige}"
        return False, 0.0, f"{passo.exige} não está instalado ({dica})"
    inicio = time.monotonic()
    proc = subprocess.run(passo.comando, cwd=ROOT, capture_output=True, text=True)
    segundos = time.monotonic() - inicio
    saida = (proc.stdout + proc.stderr).strip()
    passou = proc.returncode == 0
    if passo.reprova_se_saida_contem and passo.reprova_se_saida_contem in saida:
        passou = False
    if verbose or not passou:
        linhas = saida.splitlines()
        return passou, segundos, "\n".join(linhas[-25:])
    ultima = saida.splitlines()[-1] if saida else "ok"
    return passou, segundos, ultima


def main(argv: list[str] | None = None) -> int:
    """Roda os portões e imprime o placar.

    Args:
        argv: argumentos da linha de comando (`--rapido` pula a suíte Python; `-v` mostra a saída).

    Returns:
        0 quando todos os passos rodados passaram; 1 caso contrário.
    """
    parser = argparse.ArgumentParser(description="Comando único de verificação do Callidus.")
    parser.add_argument("--rapido", action="store_true", help="pula os passos lentos (suíte Python)")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra a saída de cada passo")
    args = parser.parse_args(argv)

    falhas: list[str] = []
    for passo in passos():
        if args.rapido and passo.lento:
            print(f"⏭  {passo.nome}: pulado (--rapido)")
            continue
        passou, segundos, resumo = rodar_passo(passo, args.verbose)
        marca = "✅" if passou else "❌"
        print(f"{marca} {passo.nome} ({segundos:.1f}s) — {passo.regra}")
        if resumo and (args.verbose or not passou):
            print("   " + resumo.replace("\n", "\n   "))
        if not passou:
            falhas.append(passo.nome)

    if falhas:
        print(f"\nReprovado em {len(falhas)} passo(s): {', '.join(falhas)}")
        return 1
    print("\nTodos os portões passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
