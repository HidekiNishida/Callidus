#!/usr/bin/env python3
"""
Arquivo: scripts/check_references.py
Nome: check_references.py
Propósito: conferir que os documentos apontam para arquivos e símbolos que realmente existem.
Responsabilidade: script de verificação — extrai referências de caminho e de símbolo do Markdown e confronta com o código.
Componentes: main, indexar_codigo, referencias.
Dependências: ast, re, pathlib (somente biblioteca padrão).
Observações: só são checadas referências inequívocas (caminho de arquivo e símbolo qualificado com classe ou módulo conhecidos).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODIGO = ("src", "scripts", "web")
IGNORED = {".venv", ".git", "node_modules", ".pytest_cache", "__pycache__", "fixtures"}
CODIGO_SPAN = re.compile(r"`([^`\n]+)`")


def _modulos() -> dict[str, set[str]]:
    """Índice de símbolos por módulo Python do projeto.

    Returns:
        Dicionário `nome_do_módulo -> {símbolos definidos}`.
    """
    index: dict[str, set[str]] = {}
    for base in CODIGO:
        for path in sorted((ROOT / base).rglob("*.py")):
            if IGNORED & set(path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            nomes: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    nomes.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            nomes.add(target.id)
            index[path.stem] = nomes
            index[path.as_posix().removeprefix("src/").removesuffix(".py").replace("/", ".")] = nomes
    return index


RAIZES = (
    "", "src/agent/", "src/", "tests/", "docs/", "docs/architecture/", "docs/regras/",
    "data/", "scripts/", "web/", "web/static/", "web/static/assets/app/", "internal/",
    "media/", "lab/", "providers/", "tools/", "skills/", "verification/", "observability/",
    "orchestrator/", "services/", "domain/", "providers/", "context/", "memory/",
    "mcp/", "knowledge/", "security/", "i18n/", "util/", "vision/", "guides/", "automation/",
)


def _caminhos_documentados() -> set[str]:
    """Caminhos de arquivo citados na documentação (para resolver relativos).

    Returns:
        Conjunto de caminhos relativos já existentes.
    """
    existentes: set[str] = set()
    for base in ("src", "docs", "tests", "scripts", "web", "internal"):
        for path in (ROOT / base).rglob("*"):
            if path.is_file() and not (IGNORED & set(path.parts)):
                existentes.add(path.relative_to(ROOT).as_posix())
                existentes.add(path.relative_to(ROOT).as_posix().removesuffix(".py"))
    return existentes


def _candidatos(texto: str) -> list[tuple[str, str]]:
    """Extrai (tipo, valor) das referências de um trecho entre crases.

    Args:
        texto: conteúdo entre crases.

    Returns:
        Lista de tuplas ("arquivo" ou "simbolo", valor).
    """
    found: list[tuple[str, str]] = []
    if "/" in texto and not texto.startswith(("/", "http", "@")) and " " not in texto:
        found.append(("arquivo", texto))
    elif texto.endswith(".py") and " " not in texto:
        found.append(("arquivo", texto))
    if "(" in texto and ")" in texto and "." in texto and " " not in texto:
        found.append(("simbolo", texto.split("(", 1)[0]))
    return found


def _avaliar(
    tipo: str,
    valor: str,
    arquivo: Path,
    rel: str,
    linha: int,
    modulos: dict[str, set[str]],
    caminhos: set[str],
    problemas: list[str],
) -> None:
    """Confere uma referência e registra o problema, se houver.

    Args:
        tipo: "arquivo" ou "simbolo".
        valor: referência encontrada.
        arquivo: documento onde a referência está.
        rel: caminho do documento, para as mensagens.
        linha: número da linha da referência.
        modulos: índice de símbolos por módulo.
        caminhos: caminhos já existentes no repositório.
        problemas: lista onde o problema é registrado.
    """
    if tipo == "arquivo":
        alvo_rel = valor.lstrip("/")
        if any(marca in alvo_rel for marca in ("*", "?", "<", ">")):
            return
        # Caminhos de runtime (gerados em execução) não vivem no repositório.
        if alvo_rel.startswith(("data/", "lab/out/")):
            return
        # Nome solto sem pasta: pode ser um exemplo (app.py, calc.py).
        if "/" not in alvo_rel:
            return
        if (arquivo.parent / valor).exists() or (ROOT / alvo_rel).exists():
            return
        if any((ROOT / raiz / alvo_rel).exists() for raiz in RAIZES):
            return
        if any(alvo_rel.endswith(ext) for ext in (".md", ".py", ".yaml", ".json", ".mjs", ".sh")):
            problemas.append(f"{rel}:{linha}: caminho inexistente «{valor}»")
        return
    partes = valor.split(".")
    if len(partes) < 2:
        return
    base_nome = partes[0]
    if base_nome in modulos:
        conhecidos = modulos[base_nome]
        if partes[1] not in conhecidos and partes[-1] not in conhecidos:
            problemas.append(f"{rel}:{linha}: símbolo inexistente «{valor}»")


def main(argv: list[str]) -> int:
    """Verifica as referências da documentação contra o código.

    Args:
        argv: pastas ou arquivos Markdown (padrão: README.md, AGENTS.md, docs, src, internal, web, tests, scripts).

    Returns:
        0 quando toda referência existe; 1 quando há referências quebradas.
    """
    paths = argv[1:] or ["README.md", "AGENTS.md", "docs", "src", "internal", "web", "tests", "scripts"]
    modulos = _modulos()
    caminhos = _caminhos_documentados()
    problemas: list[str] = []

    for base in paths:
        alvo = Path(base)
        if not alvo.is_absolute():
            alvo = ROOT / base
        arquivos = sorted(alvo.rglob("*.md")) if alvo.is_dir() else [alvo]
        for arquivo in arquivos:
            if not arquivo.exists() or (IGNORED & set(arquivo.parts)):
                continue
            rel = arquivo.relative_to(ROOT).as_posix()
            texto = arquivo.read_text(encoding="utf-8")
            dentro_de_bloco = False
            contraexemplo = False
            linhas = texto.splitlines()
            for linha, conteudo in enumerate(linhas, start=1):
                if conteudo.strip().startswith("```"):
                    dentro_de_bloco = not dentro_de_bloco
                    continue
                if dentro_de_bloco:
                    continue
                # As tabelas "Bom vs ruim" do projeto marcam o contraexemplo na primeira
                # coluna com ❌: o caminho citado ali é propositalmente inexistente.
                celulas = [c.strip() for c in conteudo.strip().strip("|").split("|")]
                if len(celulas) > 1 and all(set(c) <= set("-: ") and c for c in celulas):
                    cabecalho = linhas[linha - 2].strip() if linha >= 2 else ""
                    contraexemplo = "❌" in cabecalho
                    continue
                if contraexemplo and conteudo.strip().startswith("|"):
                    # ignora a primeira célula (o contraexemplo)
                    celulas = [c for c in conteudo.strip().strip("|").split("|")]
                    resto = "|".join(celulas[1:])
                    for trecho in CODIGO_SPAN.findall(resto):
                        for tipo, valor in _candidatos(trecho):
                            _avaliar(tipo, valor, arquivo, rel, linha, modulos, caminhos, problemas)
                    continue
                for trecho in CODIGO_SPAN.findall(conteudo):
                    for tipo, valor in _candidatos(trecho):
                        _avaliar(tipo, valor, arquivo, rel, linha, modulos, caminhos, problemas)
    if not problemas:
        print("Referências da documentação conferidas: todas existem no código.")
        return 0
    print(f"Referências quebradas ({len(problemas)}):")
    for item in sorted(set(problemas)):
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
