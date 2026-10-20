#!/usr/bin/env python3
"""
Arquivo: scripts/padronizar_cabecalhos.py
Nome: padronizar_cabecalhos.py
Propósito: aplicar o cabeçalho padrão (campos `Arquivo`, `Nome`, `Propósito`, …) nos módulos Python.
Responsabilidade: script de manutenção — insere a docstring de cabeçalho sem alterar o código do módulo.
Componentes: main, header_for, insert_header.
Dependências: ast, pathlib, argparse (somente biblioteca padrão).
Observações: os campos derivados do próprio módulo (componentes e dependências) são gerados por leitura do código;
o propósito usa a narrativa existente no arquivo; nada de lógica é tocado.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LAYERS: dict[str, str] = {
    "api": "camada de apresentação/transport",
    "orchestrator": "camada de aplicação",
    "orchestrator/execution": "camada de aplicação",
    "services": "camada de aplicação",
    "domain": "camada de domínio",
    "persistence": "camada de infraestrutura",
    "providers": "camada de infraestrutura",
    "tools": "camada de infraestrutura",
    "mcp": "camada de infraestrutura",
    "remote": "camada de infraestrutura",
    "context": "camada de aplicação",
    "verification": "camada de aplicação",
    "observability": "camada de aplicação",
    "knowledge": "camada de infraestrutura",
    "memory": "camada de aplicação",
    "skills": "camada de aplicação",
    "security": "camada de infraestrutura",
    "i18n": "camada de aplicação",
    "util": "camada de aplicação",
    "vision": "camada de aplicação",
    "guides": "camada de aplicação",
    "automation": "camada de aplicação",
    "tests": "camada de testes",
    "scripts": "script de manutenção",
}

NOTES: dict[str, str] = {
    "api": "a rota valida, delega e serializa — a regra de negócio vive no serviço.",
    "orchestrator": "o estado canônico é o SQLite; a verificação é independente de quem executa.",
    "orchestrator/execution": "quem escreve não aprova o próprio resultado.",
    "domain": "sem dependência de FastAPI, SQLAlchemy ou HTTP.",
    "persistence": "o formato persistido é contrato: mudar coluna exige migração e teste.",
    "providers": "a escolha do provedor é explícita; o mock só entra com autorização.",
    "tools": "toda escrita passa pela raiz autorizada do projeto.",
    "verification": "a evidência é gravada mesmo quando a verificação reprova.",
    "tests": "banco e filesystem temporários; nunca depender de credencial real ou serviço externo.",
}


def _relative(path: Path) -> str:
    """Caminho do arquivo relativo à raiz do repositório.

    Args:
        path: caminho absoluto ou relativo do arquivo.

    Returns:
        O caminho relativo, com separadores de pasta.
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _layer(relative: str) -> tuple[str, str]:
    """Camada arquitetural e nota de observância a partir do caminho.

    Args:
        relative: caminho relativo ao repositório.

    Returns:
        Tupla (camada, observação) — a observação pode ser vazia.
    """
    parts = relative.split("/")
    if parts[:2] == ["src", "agent"]:
        parts = parts[2:]
    elif parts[:1] == ["tests"]:
        return LAYERS["tests"], NOTES.get("tests", "")
    elif parts[:1] == ["scripts"]:
        return LAYERS["scripts"], NOTES.get("scripts", "")
    for size in (2, 1):
        key = "/".join(parts[:size]) if size > 1 else parts[0]
        if key in LAYERS:
            return LAYERS[key], NOTES.get(key, "")
    return "camada de aplicação", ""


def _purpose(relative: str, tree: ast.Module, lines: list[str]) -> str:
    """Propósito do módulo: narrativa existente, título do arquivo ou docstring atual.

    Args:
        relative: caminho relativo ao repositório.
        tree: árvore sintática do módulo.
        lines: linhas do arquivo.

    Returns:
        Uma frase com o propósito do arquivo.
    """
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") and "—" in stripped:
            return stripped.lstrip("# ").split("—", 1)[1].strip()
        if stripped.startswith("/*") or stripped.startswith('"""'):
            break
    doc = ast.get_docstring(tree)
    if doc:
        first = doc.strip().splitlines()[0].strip()
        if first:
            return first.rstrip(".")
    return f"implementa {relative.rsplit('/', 1)[-1].removesuffix('.py').replace('_', ' ')}"


def _components(tree: ast.Module) -> str:
    """Símbolos públicos de nível superior do módulo.

    Args:
        tree: árvore sintática do módulo.

    Returns:
        Lista de nomes, separada por vírgula.
    """
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    if not names:
        return "funções internas"
    return ", ".join(names[:6]) + ("…" if len(names) > 6 else "")


def _dependencies(tree: ast.Module) -> str:
    """Módulos importados pelo arquivo (internos primeiro).

    Args:
        tree: árvore sintática do módulo.

    Returns:
        Lista de módulos, separada por vírgula.
    """
    internal: list[str] = []
    external: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                (internal if alias.name.startswith("agent") else external).append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not module:
                continue
            (internal if module.startswith("agent") else external).append(module)
    ordered = sorted(set(internal)) + sorted(set(external))
    return ", ".join(ordered[:6]) + ("…" if len(ordered) > 6 else "")


def header_for(path: Path) -> str:
    """Monta o cabeçalho padrão de um módulo.

    Args:
        path: caminho do arquivo Python.

    Returns:
        O texto da docstring de cabeçalho (sem aspas).
    """
    relative = _relative(path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    layer, note = _layer(relative)
    fields = [
        f"Arquivo: {relative}",
        f"Nome: {path.name}",
        f"Propósito: {_purpose(relative, tree, lines)}.",
        f"Responsabilidade: {layer}.",
        f"Componentes: {_components(tree)}.",
        f"Dependências: {_dependencies(tree)}.",
    ]
    if note:
        fields.append(f"Observações: {note}")
    return "\n".join(fields)


def _sem_comentario_de_caminho(lines: list[str], path: Path) -> list[str]:
    """Remove a linha `# caminho — propósito` (ela duplica o cabeçalho).

    Args:
        lines: linhas do arquivo já emendado.
        path: caminho do arquivo (usado para casar o nome).

    Returns:
        As linhas sem o comentário de caminho.
    """
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and "—" in stripped and path.name in stripped:
            return lines[:index] + lines[index + 1:]
    return lines


def insert_header(path: Path, header: str, narrative: str | None) -> bool:
    """Insere (ou funde) o cabeçalho na primeira instrução do módulo.

    Args:
        path: caminho do arquivo Python.
        header: campos do cabeçalho, sem as aspas.
        narrative: docstring narrativa existente, quando houver.

    Returns:
        `True` quando o arquivo foi alterado.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(
        getattr(tree.body[0], "value", None), ast.Constant
    ):
        first = tree.body[0]
        if isinstance(first.value.value, str):
            if "Arquivo:" in first.value.value:
                return False
            body = header + ("\n\n" + narrative.strip() if narrative else "")
            start = first.lineno - 1
            end = first.end_lineno
            new_lines = lines[:start] + ['"""\n' + body + '\n"""\n'] + lines[end:]
            path.write_text("".join(_sem_comentario_de_caminho(new_lines, path)), encoding="utf-8")
            return True
    # Sem docstring: insere antes da primeira instrução, preservando shebang e `__future__`.
    insert_at = 0
    for index, line in enumerate(lines):
        if line.strip().startswith("#!") or line.strip().startswith("# -*- coding"):
            insert_at = index + 1
    if tree.body:
        node = tree.body[0]
        insert_at = min(insert_at, node.lineno - 1)
    body = header + ("\n\n" + narrative.strip() if narrative else "")
    new_lines = lines[:insert_at] + ['"""\n' + body + '\n"""\n\n'] + lines[insert_at:]
    path.write_text("".join(_sem_comentario_de_caminho(new_lines, path)), encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    """Aplica o cabeçalho nos arquivos informados.

    Args:
        argv: argumentos da linha de comando (pastas ou arquivos).

    Returns:
        0 quando tudo deu certo.
    """
    parser = argparse.ArgumentParser(description="Aplica o cabeçalho padrão nos módulos Python.")
    parser.add_argument("paths", nargs="*", default=["src", "tests", "scripts"])
    parser.add_argument("--check", action="store_true", help="apenas informa o que faria")
    args = parser.parse_args(argv)

    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / raw
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.py")))
        elif path.is_file():
            targets.append(path)

    changed = 0
    for target in targets:
        if "fixtures" in target.parts:
            # Fixtures são produtos de exemplo (o "projeto do usuário"), não código do Callidus.
            continue
        if "__pycache__" in target.parts or target.name.startswith("_"):
            if target.name != "__init__.py":
                continue
        try:
            tree = ast.parse(target.read_text(encoding="utf-8"))
        except SyntaxError:
            print(f"ignorado (sintaxe): {target}")
            continue
        doc = ast.get_docstring(tree)
        if doc and "Arquivo:" in doc:
            continue
        if args.check:
            print(f"precisa de cabeçalho: {_relative(target)}")
            changed += 1
            continue
        narrative = doc
        header = header_for(target)
        if insert_header(target, header, narrative):
            changed += 1
            print(f"cabeçalho aplicado: {_relative(target)}")
    print(f"total: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
