#!/usr/bin/env python3
"""
Arquivo: scripts/preencher_resume.py
Nome: preencher_resume.py
Propósito: preencher as lacunas do `resume.md` com as descrições que já existem no código.
Responsabilidade: script de manutenção — cria seções ausentes e completa símbolos não descritos, sem reescrever texto existente.
Componentes: main, secoes, descricao_de, entradas_de.
Dependências: ast, re, pathlib (somente biblioteca padrão).
Observações: a fonte da verdade é a docstring do próprio símbolo; o texto já escrito no `resume.md` nunca é sobrescrito.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESUME = ROOT / "resume.md"
FIM = "## Links cruzados"


def _assinatura(no: ast.AST) -> str:
    """Assinatura legível de uma função ou método.

    Args:
        no: nó da AST.

    Returns:
        A assinatura entre parênteses, com os tipos anotados quando existem.
    """
    if isinstance(no, ast.ClassDef):
        return ""
    args = no.args
    partes: list[str] = []
    for arg in list(args.posonlyargs) + list(args.args):
        partes.append(arg.arg)
    if args.vararg:
        partes.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        partes.append("*")
    for arg in args.kwonlyargs:
        partes.append(arg.arg)
    if args.kwarg:
        partes.append("**" + args.kwarg.arg)
    return "(" + ", ".join(partes) + ")"


def _retorno(no: ast.AST) -> str:
    """Tipo de retorno declarado, quando houver.

    Args:
        no: nó da AST.

    Returns:
        O tipo anotado ou string vazia.
    """
    anotacao = getattr(no, "returns", None)
    if anotacao is None:
        return ""
    try:
        return ast.unparse(anotacao)
    except Exception:  # pragma: no cover - anotação exótica
        return ""


def _primeira_linha(texto: str) -> str:
    """Primeira linha útil de uma docstring.

    Args:
        texto: docstring completa.

    Returns:
        A primeira linha, sem quebras nem aspas.
    """
    linhas = [linha.strip() for linha in (texto or "").strip().splitlines()]
    for linha in linhas:
        if linha:
            return linha.rstrip(".")
    return ""


def _simbolos(caminho: Path) -> list[tuple[str, str, str]]:
    """Símbolos públicos de um arquivo Python, com a descrição de cada um.

    Args:
        caminho: arquivo Python.

    Returns:
        Lista de tuplas (nome, assinatura com retorno, descrição).
    """
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    encontrados: list[tuple[str, str, str]] = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if no.name.startswith("__") and no.name.endswith("__") and no.name != "__init__":
            continue
        qualificado = no.name
        for pai in ast.walk(arvore):
            if isinstance(pai, ast.ClassDef) and no in pai.body:
                qualificado = f"{pai.name}.{no.name}"
                break
        doc = ast.get_docstring(no) or ""
        descricao = _primeira_linha(doc)
        if isinstance(no, ast.ClassDef):
            encontrados.append((no.name, "", descricao))
        else:
            assinatura = _assinatura(no)
            retorno = _retorno(no)
            completo = f"{assinatura} → {retorno}" if retorno else assinatura
            encontrados.append((qualificado, completo, descricao))
    return encontrados


def _funcoes_js(caminho: Path) -> list[tuple[str, str, str]]:
    """Funções exportadas de um arquivo JavaScript, com a descrição do JSDoc.

    Args:
        caminho: arquivo JavaScript.

    Returns:
        Lista de tuplas (nome, assinatura vazia, descrição).
    """
    try:
        texto = caminho.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    encontrados: list[tuple[str, str, str]] = []
    padrao = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)|export\s+const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
        re.M,
    )
    for achado in padrao.finditer(texto):
        nome = achado.group(1) or achado.group(3)
        if not nome:
            continue
        antes = texto[: achado.start()]
        bloco = antes.rsplit("/**", 1)[-1] if "/**" in antes else ""
        descricao = ""
        if bloco.endswith("*/"):
            linhas = [l.strip().lstrip("*").strip() for l in bloco[:-2].splitlines()]
            descricao = next((l for l in linhas if l and not l.startswith("@")), "")
        encontrados.append((nome, "", descricao))
    return encontrados


def secoes(texto: str) -> dict[str, tuple[int, int]]:
    """Seções de arquivo do `resume.md` e seus limites de linha.

    Uma seção termina no próximo título de nível igual ou superior — é a mesma
    regra usada pela verificação (`scripts/resume.py`), para que uma entrada
    escrita aqui caia inequivocamente dentro da seção do seu arquivo.

    Args:
        texto: conteúdo do `resume.md`.

    Returns:
        Dicionário `caminho -> (início, fim)` das seções de arquivo.
    """
    linhas = texto.splitlines()
    limites: dict[str, tuple[int, int]] = {}
    for indice, linha in enumerate(linhas):
        achado = re.match(r"^(#{2,3}) `([^`]+)`\s*$", linha)
        if not achado:
            continue
        nivel = len(achado.group(1))
        fim = len(linhas)
        for posterior in range(indice + 1, len(linhas)):
            outro = re.match(r"^(#{1,6}) ", linhas[posterior])
            if outro and len(outro.group(1)) <= nivel:
                fim = posterior
                break
        caminho = achado.group(2)
        if caminho not in limites:
            limites[caminho] = (indice, fim)
    return limites


def _proposito_de(caminho: Path) -> str:
    """Propósito de um arquivo, lido do próprio documento ou do docstring do módulo.

    Args:
        caminho: arquivo do projeto.

    Returns:
        Uma frase com o propósito, ou string vazia.
    """
    if caminho.suffix in (".md", ".mjs", ".js"):
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return ""
        proposito = ""
        for indice, linha in enumerate(linhas):
            if linha.startswith("# ") and indice + 2 < len(linhas):
                for seguinte in linhas[indice + 1:]:
                    if seguinte.strip() and not seguinte.startswith("!["):
                        proposito = seguinte.strip()
                        break
                break
        return proposito.rstrip(".")
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return ""
    doc = ast.get_docstring(arvore) or ""
    return _primeira_linha(doc).rstrip(".")


def _proposito_de_ativo(caminho: Path) -> str:
    """Propósito de um arquivo de asset (SVG, CSS, YAML, JSON).

    Args:
        caminho: arquivo do projeto.

    Returns:
        Uma frase com o propósito, ou string vazia.
    """
    nome = caminho.name.lower()
    if caminho.suffix == ".svg":
        if "wordmark" in nome or "name" in nome:
            return "Logotipo em texto da marca (fonte)."
        if "horizontal" in nome:
            return "Logotipo horizontal da marca (fonte)."
        if "vertical" in nome:
            return "Logotipo vertical da marca (fonte)."
        if "favicon" in nome:
            return "Ícone de aba do navegador."
        if "mark" in nome:
            return "Símbolo da marca (fonte)."
        return "Recurso visual da marca."
    if caminho.suffix == ".css":
        return "Folha de estilo da interface (design system, temas e layout)."
    if caminho.suffix in (".yaml", ".yml"):
        return "Exemplo de configuração de provedores (modelo de referência)."
    if caminho.suffix == ".json":
        return "Configuração de runtime do Callidus."
    return ""


def _simbolos_por_arquivo(raiz: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Símbolos de cada arquivo do inventário, indexados pelo caminho relativo.

    Args:
        raiz: pasta do inventário.

    Returns:
        Dicionário `caminho relativo -> lista de (nome, assinatura, descrição)`.
    """
    indice: dict[str, list[tuple[str, str, str]]] = {}
    for base in ("src", "scripts", "web/static/assets"):
        for caminho in sorted((raiz / base).rglob("*")):
            if not caminho.is_file() or caminho.suffix not in (".py", ".js", ".mjs"):
                continue
            if "__pycache__" in caminho.parts or "vendor" in caminho.parts:
                continue
            rel = caminho.relative_to(raiz).as_posix()
            indice[rel] = (
                _simbolos(caminho) if caminho.suffix == ".py" else _funcoes_js(caminho)
            )
    return indice


def _falta_simbolo(corpo: str, nome: str) -> bool:
    """O símbolo já é citado no corpo da seção?

    Args:
        corpo: texto da seção.
        nome: nome do símbolo.

    Returns:
        `True` quando o símbolo ainda não aparece entre crases.
    """
    padrao = rf"`(?:[\w.]+\.)?{re.escape(nome)}(?=[`(\s])"
    return not re.search(padrao, corpo)


def main(argv: list[str]) -> int:
    """Preenche as lacunas do `resume.md` e informa o que foi acrescentado.

    Args:
        argv: sem uso.

    Returns:
        0 quando o preenchimento termina sem erro.
    """
    texto = RESUME.read_text(encoding="utf-8")
    indice = _simbolos_por_arquivo(ROOT)
    limites = secoes(texto)
    linhas = texto.splitlines()

    # 1) completa símbolos dentro das seções que já existem
    acrescentados = 0
    for caminho, (inicio, fim) in sorted(limites.items(), key=lambda par: par[1][0], reverse=True):
        if caminho not in indice:
            continue
        corpo = "\n".join(linhas[inicio:fim])
        novos = [
            (nome, assinatura, descricao)
            for nome, assinatura, descricao in indice[caminho]
            if _falta_simbolo(corpo, nome)
        ]
        if not novos:
            continue
        entradas = []
        for nome, assinatura, descricao in novos:
            cabecalho = f"`{nome}{assinatura}`" if assinatura else f"`{nome}`"
            entradas.append(f"- {cabecalho} — {descricao}." if descricao else f"- {cabecalho}")
        # As entradas entram logo após a linha de propósito: assim ficam
        # inequivocamente dentro da seção, mesmo com blocos de índice depois dela.
        ancora = inicio + 1
        while ancora < fim and not linhas[ancora].startswith("**Propósito"):
            ancora += 1
        ancora = min(ancora + 1, fim)
        bloco = linhas[:ancora] + [""] + entradas + linhas[ancora:]
        linhas = bloco
        acrescentados += len(novos)
        limites = secoes("\n".join(linhas))

    # 2) cria seções que faltam (código, documentos e ativos)
    novas: list[str] = []
    for caminho in sorted(ROOT.rglob("*")):
        if not caminho.is_file() or caminho.suffix not in (".py", ".js", ".mjs", ".md", ".svg", ".css", ".yaml", ".yml", ".json"):
            continue
        if any(parte in caminho.parts for parte in ("__pycache__", "vendor", ".venv", ".git")):
            continue
        rel = caminho.relative_to(ROOT).as_posix()
        if rel in limites:
            continue
        proposito = _proposito_de(caminho) or _proposito_de_ativo(caminho)
        bloco = [f"### `{rel}`", "", f"**Propósito:** {proposito}.", ""]
        for nome, assinatura, descricao in indice.get(rel, []):
            cabecalho = f"`{nome}{assinatura}`" if assinatura else f"`{nome}`"
            bloco.append(f"- {cabecalho} — {descricao}." if descricao else f"- {cabecalho}")
        novas.append("\n".join(bloco) + "\n")

    texto = "\n".join(linhas)
    if novas:
        ancora = FIM if FIM in texto else None
        if ancora:
            cabecalho, _, resto = texto.partition(ancora)
            texto = cabecalho + "\n".join(novas) + "\n" + ancora + resto
        else:
            texto = texto.rstrip("\n") + "\n\n" + "\n".join(novas)
    RESUME.write_text(texto, encoding="utf-8")
    print(f"seções novas: {len(novas)} · símbolos acrescentados: {acrescentados}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
