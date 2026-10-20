#!/usr/bin/env python3
"""
Arquivo: scripts/resume.py
Nome: resume.py
Propósito: manter o `resume.md` sincronizado com a estrutura real do projeto.
Responsabilidade: script de manutenção — inventário estrutural (arquivos, classes, funções) e conferência com o mapa vivo.
Componentes: `check` (confere), `faltando` (esqueleto do que falta), `carimbar` (grava o inventário), `hook` (hook do Cursor).
Dependências: ast, json, pathlib, subprocess (somente biblioteca padrão).
Observações: `carimbar` só grava quando nada está faltando — um inventário carimbado incompleto esconderia a falta.

Mantém o resume.md sincronizado com a estrutura do projeto.

O inventário estrutural (diretórios, arquivos, classes, métodos e funções com
assinatura) é extraído do código e comparado com:

1. o que o resume.md descreve (cada item precisa aparecer entre crases na seção
   do seu arquivo);
2. o último inventário carimbado em .cursor/resume-inventario.json (detecta itens
   novos, removidos ou com assinatura alterada desde a última revisão).

Uso:
  python3 scripts/resume.py check      # exit 1 se o resume.md estiver desatualizado
  python3 scripts/resume.py faltando   # esqueleto markdown dos itens sem descrição
  python3 scripts/resume.py carimbar   # grava o inventário atual (só se nada faltar)
  python3 scripts/resume.py hook       # hook `stop` do Cursor (JSON em stdin/stdout)
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESUME = ROOT / "resume.md"
STATE = ROOT / ".cursor" / "resume-inventario.json"

# Pastas descritas só como um todo (conteúdo repetitivo ou gerado).
COLLAPSED = ("media/icons/", "internal/tarefas/", "tests/fixtures/", ".planning/")
# Arquivos cujas classes/funções precisam ser descritas uma a uma.
SYMBOL_PREFIXES = ("src/", "scripts/", "web/static/assets/")
JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.M)
HEADING = re.compile(r"^(#{1,6})\s")


@dataclass(frozen=True)
class Item:
    """Item do inventário estrutural (arquivo, pasta, símbolo) com a chave de comparação."""
    kind: str  # dir | file | sym
    path: str
    name: str = ""
    signature: str = ""

    @property
    def key(self) -> str:
        """Chave estável do item, usada para comparar inventários."""
        if self.kind == "sym":
            return f"sym:{self.path}::{self.name}{self.signature}"
        return f"{self.kind}:{self.path}"

    @property
    def short(self) -> str:
        """Nome curto do símbolo, sem o qualificador do módulo."""
        return self.name.rsplit(".", 1)[-1]


IGNORADOS_INVENTARIO = ("web/static/assets/vendor/", "web/static/assets/brand/")


def project_files() -> list[str]:
    """Lista os arquivos do projeto que entram no inventário.

   ficam de fora bibliotecas de terceiros vendorizadas e assets gerados de marca:
    o `resume.md` mapeia o **código** do projeto, não arquivos que não são
    escritos nem mantidos aqui.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        f
        for f in out.splitlines()
        if f
        and (ROOT / f).is_file()
        and not f.startswith(IGNORADOS_INVENTARIO)
    )


def _py_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Monta a assinatura de um símbolo Python a partir da AST."""
    args = ast.unparse(node.args)
    args = re.sub(r"^(self|cls)(, )?", "", args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"({args}){ret}"


def python_symbols(path: str, source: str) -> list[Item]:
    """Extrai as classes e funções de um módulo Python."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    items: list[Item] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append(Item("sym", path, node.name, _py_signature(node)))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            items.append(Item("sym", path, node.name, f"({bases})" if bases else ""))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    items.append(Item("sym", path, f"{node.name}.{child.name}", _py_signature(child)))
    return items


def js_symbols(path: str, source: str) -> list[Item]:
    """Extrai as funções exportadas de um módulo JavaScript."""
    seen: set[str] = set()
    items: list[Item] = []
    for match in JS_FUNC.finditer(source):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        params = " ".join(match.group(2).split())
        items.append(Item("sym", path, name, f"({params})"))
    return items


def inventory(files: list[str] | None = None) -> list[Item]:
    """Monta o inventário estrutural do projeto (pastas, arquivos e símbolos)."""
    files = project_files() if files is None else files
    items: list[Item] = []
    dirs: set[str] = set()
    for path in files:
        if path == STATE.relative_to(ROOT).as_posix():
            continue
        collapsed = next((c for c in COLLAPSED if path.startswith(c)), None)
        if collapsed:
            dirs.add(collapsed)
            continue
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:depth]) + "/")
        items.append(Item("file", path))
        if not path.startswith(SYMBOL_PREFIXES):
            continue
        if path.endswith(".py"):
            items.extend(python_symbols(path, (ROOT / path).read_text(encoding="utf-8")))
        elif path.endswith(".js"):
            items.extend(js_symbols(path, (ROOT / path).read_text(encoding="utf-8")))
    for folder in list(dirs):
        parts = folder.rstrip("/").split("/")
        dirs.update("/".join(parts[:depth]) + "/" for depth in range(1, len(parts)))
    items.extend(Item("dir", d) for d in dirs)
    return sorted(items, key=lambda item: item.key)


def file_sections(text: str) -> dict[str, str]:
    """Mapeia cada `caminho` citado em um título ao texto da sua seção."""
    lines = text.splitlines()
    sections: dict[str, str] = {}
    for index, line in enumerate(lines):
        heading = HEADING.match(line)
        if not heading:
            continue
        level = len(heading.group(1))
        end = len(lines)
        for later in range(index + 1, len(lines)):
            other = HEADING.match(lines[later])
            if other and len(other.group(1)) <= level:
                end = later
                break
        body = "\n".join(lines[index:end])
        for path in re.findall(r"`([^`]+)`", line):
            sections.setdefault(path, body)
    return sections


def missing_items(items: list[Item], text: str) -> list[Item]:
    """Lista os itens do inventário que o `resume.md` ainda não descreve."""
    sections = file_sections(text)
    quoted = set(re.findall(r"`([^`\s]+)`", text))
    missing: list[Item] = []
    for item in items:
        if item.kind == "dir":
            if item.path not in quoted and item.path.rstrip("/") not in quoted:
                missing.append(item)
        elif item.kind == "file":
            if item.path not in quoted and item.path not in sections:
                missing.append(item)
        else:
            body = sections.get(item.path)
            pattern = rf"`(?:[\w.]+\.)?{re.escape(item.short)}(?=[`(\s])"
            if body is None or not re.search(pattern, body):
                missing.append(item)
    return missing


def load_state() -> list[str]:
    """Lê o inventário carimbado da última revisão."""
    if not STATE.is_file():
        return []
    return json.loads(STATE.read_text(encoding="utf-8")).get("items", [])


def report() -> tuple[list[Item], list[str], list[str]]:
    """Compara o inventário atual com o `resume.md` e com o carimbo anterior."""
    items = inventory()
    text = RESUME.read_text(encoding="utf-8") if RESUME.is_file() else ""
    current = {item.key for item in items}
    stored = set(load_state())
    added = sorted(current - stored)
    removed = sorted(stored - current)
    return missing_items(items, text), added, removed


def describe(missing: list[Item], added: list[str], removed: list[str], limit: int = 40) -> str:
    """Formata o relatório de itens faltantes, novos e removidos."""
    lines: list[str] = []
    if missing:
        lines.append(f"Sem descrição no resume.md ({len(missing)}):")
        lines += [f"  - {item.key}" for item in missing[:limit]]
    if added:
        lines.append(f"Novos ou alterados desde o último carimbo ({len(added)}):")
        lines += [f"  + {key}" for key in added[:limit]]
    if removed:
        lines.append(f"Removidos ou alterados desde o último carimbo ({len(removed)}):")
        lines += [f"  - {key}" for key in removed[:limit]]
    return "\n".join(lines)


def skeleton(missing: list[Item]) -> str:
    """Monta o esqueleto Markdown dos itens que faltam descrição."""
    out: list[str] = []
    current = None
    for item in missing:
        if item.kind == "dir":
            out.append(f"## `{item.path}`\n\nPropósito: …\n")
        elif item.kind == "file":
            out.append(f"### `{item.path}`\n\nPropósito: …\n")
        else:
            if item.path != current:
                out.append(f"\n### `{item.path}`\n")
                current = item.path
            out.append(f"- `{item.name}{item.signature}` — …")
    return "\n".join(out)


def cmd_check() -> int:
    """Comando `check`: confere o `resume.md` e devolve código 1 quando há divergência."""
    missing, added, removed = report()
    if not (missing or added or removed):
        print("resume.md em dia.")
        return 0
    print(describe(missing, added, removed))
    print("\nAtualize o resume.md e rode: python3 scripts/resume.py carimbar")
    return 1


def cmd_faltando() -> int:
    """Comando `faltando`: imprime o esqueleto do que falta descrever."""
    missing, _, _ = report()
    print(skeleton(missing) if missing else "Nada faltando.")
    return 0


def cmd_carimbar() -> int:
    """Comando `carimbar`: grava o inventário atual quando nada falta."""
    items = inventory()
    text = RESUME.read_text(encoding="utf-8") if RESUME.is_file() else ""
    missing = missing_items(items, text)
    if missing:
        print(describe(missing, [], []))
        print("\nDescreva esses itens antes de carimbar.")
        return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": [item.key for item in items]}
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Carimbado: {len(items)} itens.")
    return 0


def cmd_hook() -> int:
    """Comando `hook`: ponto de entrada do hook de parada do Cursor."""
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    if event.get("status") not in (None, "completed"):
        print("{}")
        return 0
    try:
        missing, added, removed = report()
    except Exception:  # o hook nunca deve travar o agente
        print("{}")
        return 0
    if not (missing or added or removed):
        print("{}")
        return 0
    message = (
        "O resume.md está desatualizado em relação ao código. Siga docs/regras/resumo-projeto.md: "
        "atualize as descrições (propósito, entradas e saídas) dos itens abaixo, remova os que "
        "não existem mais, rode `python3 scripts/resume.py carimbar` e inclua resume.md e "
        ".cursor/resume-inventario.json no commit da tarefa.\n\n" + describe(missing, added, removed)
    )
    print(json.dumps({"followup_message": message}, ensure_ascii=False))
    return 0


COMMANDS = {"check": cmd_check, "faltando": cmd_faltando, "carimbar": cmd_carimbar, "hook": cmd_hook}


def main(argv: list[str]) -> int:
    """Roteia o comando recebido pela linha de comando."""
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
