"""
Arquivo: src/agent/verification/integrity.py
Nome: integrity.py
Propósito: conferir, sem executar o modelo, que uma escrita em Python não quebrou o projeto — imports locais, quem depende do arquivo e os testes que já existiam.
Responsabilidade: camada de infraestrutura — análise estática (AST) dos módulos do projeto e localização dos testes.
Componentes: local_import_problems, dependents_problems, project_has_tests, entry_is_gui.
Dependências: ast, pathlib, agent.tools.app_runner.
Observações: só imports de módulos que existem no próprio projeto são conferidos; bibliotecas instaladas ficam de fora (não dá para saber o ambiente do projeto sem executá-lo).

Por que existe
--------------
Visto com o `qwen3-vl:8b` no pedido "termine a calculadora e abra para eu ver": o modelo trocou o
`main.py` de 62 linhas (a janela inteira) por três linhas que chamam `Calculator` — classe que não
existe em `calculator.py`. A verificação implícita (o trecho está no arquivo + sintaxe válida)
aprovou, e o run terminou "concluído" com a calculadora quebrada.
"""
from __future__ import annotations

import ast
from pathlib import Path

from agent.tools.app_runner import is_gui_script

_SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "build", "dist"}


def _python_files(root: Path) -> list[Path]:
    """Arquivos `.py` do projeto, fora das pastas de ambiente e de cache."""
    return [p for p in root.rglob("*.py") if p.is_file() and not any(part in _SKIP for part in p.relative_to(root).parts)]


def _module_file(root: Path, near: Path, module: str) -> Path | None:
    """Arquivo do módulo local `module` (ao lado do arquivo que importa ou a partir da raiz)."""
    parts = module.split(".")
    for base in (near.parent, root):
        candidate = base.joinpath(*parts)
        for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
            if path.is_file():
                return path
    return None


def _defined_names(path: Path) -> set[str] | None:
    """Nomes definidos no topo do módulo (funções, classes, atribuições, imports); `None` se não analisável.

    Um `from x import *` ou um `__getattr__` no módulo tornam a resposta incerta: devolve `None`
    (melhor não acusar do que acusar errado).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, ValueError):
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if node.name == "__getattr__":
                return None
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    return None
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            # Definições condicionais (try/except ImportError, if TYPE_CHECKING): contam como definidas.
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
                elif isinstance(sub, ast.alias):
                    names.add((sub.asname or sub.name).split(".")[0])
    return names


def _imports(path: Path) -> list[tuple[str, list[str], int]]:
    """`(módulo, nomes importados, linha)` de cada `from M import ...` absoluto do arquivo."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, ValueError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append((node.module, [a.name for a in node.names if a.name != "*"], node.lineno))
    return found


def local_import_problems(project_root: str, path: str) -> list[str]:
    """Imports do arquivo que apontam para módulos do projeto e pedem nomes que não existem.

    Args:
        project_root: raiz do projeto.
        path: arquivo `.py` recém-gravado (relativo à raiz ou absoluto).

    Returns:
        Uma frase por problema (ex.: "main.py:3 importa Calculator de calculator, que não define esse nome").
    """
    root = Path(project_root).resolve()
    file = (root / path).resolve() if not Path(path).is_absolute() else Path(path)
    problems = []
    for module, names, line in _imports(file):
        target = _module_file(root, file, module)
        if target is None or target == file:
            continue
        defined = _defined_names(target)
        if defined is None:
            continue
        for name in names:
            if name not in defined and _module_file(root, target, f"{module}.{name}") is None:
                problems.append(f"{file.relative_to(root)}:{line} importa {name} de {module}, que não define esse nome")
    return problems


def dependents_problems(project_root: str, path: str) -> list[str]:
    """Outros arquivos do projeto que importam do arquivo gravado nomes que ele deixou de definir.

    Args:
        project_root: raiz do projeto.
        path: arquivo `.py` recém-gravado.

    Returns:
        Uma frase por dependente quebrado.
    """
    root = Path(project_root).resolve()
    file = (root / path).resolve() if not Path(path).is_absolute() else Path(path)
    defined = _defined_names(file)
    if defined is None:
        return []
    problems = []
    for other in _python_files(root):
        if other == file:
            continue
        for module, names, line in _imports(other):
            if _module_file(root, other, module) != file:
                continue
            for name in names:
                if name not in defined:
                    problems.append(f"{other.relative_to(root)}:{line} importa {name} de {module}, que não define mais esse nome")
    return problems


def project_has_tests(project_root: str) -> bool:
    """Diz se o projeto tem testes Python (arquivos `test_*.py` ou `*_test.py`)."""
    root = Path(project_root).resolve()
    return any(p.name.startswith("test_") or p.name.endswith("_test.py") for p in _python_files(root))


def entry_is_gui(project_root: str, path: str) -> bool:
    """Diz se o arquivo gravado é um programa de janela com ponto de entrada (`__main__`)."""
    root = Path(project_root).resolve()
    file = (root / path).resolve() if not Path(path).is_absolute() else Path(path)
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "__main__" in text and is_gui_script(file)
