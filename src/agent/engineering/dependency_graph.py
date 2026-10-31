"""
Arquivo: src/agent/engineering/dependency_graph.py
Nome: dependency_graph.py
Propósito: grafo de dependências do projeto com análise de impacto e propagação de mudanças.
Responsabilidade: camada de infraestrutura — construção, atualização e consulta do grafo de dependências.
Componentes: DependencyGraph, NodeInfo, ImpactAnalyzer, compute_transitive_closure.
Dependências: networkx, pathlib, ast, json.
Observações: o grafo é atualizado incrementalmente; suporta múltiplas linguagens via AST e manifests.
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import networkx as nx
except ImportError:  # pragma: no cover - networkx é dependência opcional
    nx = None


@dataclass
class NodeInfo:
    """Informações de um nó no grafo de dependências.

    Atributos:
        id: identificador único do nó (caminho relativo ou símbolo).
        kind: tipo do nó (file, class, function, module, symbol).
        label: rótulo legível.
        language: linguagem do nó.
        path: caminho absoluto do arquivo, quando aplicável.
        metadata: metadados adicionais (linha, assinatura, etc.).
    """
    id: str
    kind: str
    label: str
    language: str = ""
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeInfo:
    """Informações de uma aresta no grafo de dependências.

    Atributos:
        src: identificador do nó de origem.
        dst: identificador do nó de destino.
        kind: tipo da relação (imports, defines, calls, tests, references).
        weight: peso da relação (1.0 = forte, <1.0 = fraca).
        metadata: metadados adicionais.
    """
    src: str
    dst: str
    kind: str
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImpactResult:
    """Resultado da análise de impacto de uma mudança.

    Atributos:
        changed_files: arquivos diretamente alterados.
        affected_nodes: nós afetados pela mudança (inclui transitivos).
        affected_files: arquivos afetados (únicos).
        test_files: arquivos de teste que precisam rodar.
        risk_score: pontuação de risco (0-100).
        breaking_changes: mudanças potencialmente quebradoras de contrato.
        propagation_depth: profundidade máxima de propagação detectada.
    """
    changed_files: list[str]
    affected_nodes: list[str]
    affected_files: list[str]
    test_files: list[str]
    risk_score: float
    breaking_changes: list[dict[str, Any]]
    propagation_depth: int


class DependencyGraph:
    """Grafo de dependências do projeto com suporte a análise de impacto.

    O grafo é direcionado e ponderado. Nós representam arquivos, símbolos e módulos.
    Arestas representam relações: imports, defines, calls, tests, references.
    """

    def __init__(self, project_root: str) -> None:
        """Inicializa o grafo para um projeto.

        Args:
            project_root: raiz do projeto a analisar.
        """
        self.project_root = Path(project_root).expanduser().resolve()
        self._graph: nx.DiGraph | None = None
        self._node_index: dict[str, NodeInfo] = {}
        self._file_to_nodes: dict[str, list[str]] = defaultdict(list)
        self._symbol_to_node: dict[str, str] = {}
        self._version = 0
        self._initialized = False

    def _ensure_nx(self) -> None:
        """Garante que networkx está disponível."""
        if nx is None:
            raise RuntimeError("networkx não está instalado. Execute: pip install networkx")

    def initialize(self, *, max_files: int = 1000, force: bool = False) -> None:
        """Constrói o grafo completo do projeto.

        Args:
            max_files: limite de arquivos a processar.
            force: reconstrói mesmo se já inicializado.
        """
        if self._initialized and not force:
            return
        self._ensure_nx()
        self._graph = nx.DiGraph()
        self._node_index.clear()
        self._file_to_nodes.clear()
        self._symbol_to_node.clear()
        self._version += 1
        self._build_graph(max_files=max_files)
        self._initialized = True

    def _build_graph(self, *, max_files: int = 1000) -> None:
        """Constrói o grafo a partir do código-fonte."""
        assert self._graph is not None
        count = 0
        skip_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build", ".next", ".turbo"}

        for file_path in self.project_root.rglob("*"):
            if count >= max_files:
                break
            if not file_path.is_file():
                continue
            if any(part in skip_dirs for part in file_path.parts):
                continue

            rel_path = str(file_path.relative_to(self.project_root))
            self._add_file_node(rel_path, file_path)
            count += 1

        self._add_cross_file_edges()

    def _add_file_node(self, rel_path: str, file_path: Path) -> None:
        """Adiciona nó de arquivo e extrai símbolos."""
        assert self._graph is not None

        file_id = f"file:{rel_path}"
        suffix = file_path.suffix.lower()

        self._graph.add_node(file_id, kind="file", label=file_path.name, path=rel_path)
        self._node_index[file_id] = NodeInfo(
            id=file_id, kind="file", label=file_path.name, path=rel_path
        )
        self._file_to_nodes[rel_path].append(file_id)

        if suffix == ".py":
            self._extract_python_symbols(rel_path, file_path)
        elif suffix in {".js", ".ts", ".jsx", ".tsx"}:
            self._extract_js_ts_symbols(rel_path, file_path)
        elif suffix in {".json", ".toml", ".yaml", ".yml"}:
            self._extract_config_symbols(rel_path, file_path)

    def _extract_python_symbols(self, rel_path: str, file_path: Path) -> None:
        """Extrai símbolos Python (classes, funções, imports)."""
        assert self._graph is not None

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=rel_path)
        except (SyntaxError, OSError):
            return

        file_id = f"file:{rel_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_id = f"module:{alias.name}"
                    if not self._graph.has_node(mod_id):
                        self._graph.add_node(mod_id, kind="module", label=alias.name)
                        self._node_index[mod_id] = NodeInfo(id=mod_id, kind="module", label=alias.name)
                    self._graph.add_edge(file_id, mod_id, kind="imports", weight=1.0)
                    self._symbol_to_node[f"import:{alias.name}"] = mod_id

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod_id = f"module:{node.module}"
                    if not self._graph.has_node(mod_id):
                        self._graph.add_node(mod_id, kind="module", label=node.module)
                        self._node_index[mod_id] = NodeInfo(id=mod_id, kind="module", label=node.module)
                    self._graph.add_edge(file_id, mod_id, kind="imports", weight=1.0)
                    for alias in node.names:
                        sym_id = f"symbol:{node.module}.{alias.name}"
                        self._symbol_to_node[sym_id] = mod_id

            elif isinstance(node, ast.ClassDef):
                sym_id = f"symbol:{rel_path}::{node.name}"
                self._graph.add_node(sym_id, kind="class", label=node.name, path=rel_path, line=node.lineno)
                self._node_index[sym_id] = NodeInfo(
                    id=sym_id, kind="class", label=node.name, language="python", path=rel_path,
                    metadata={"line": node.lineno, "bases": [b.id for b in node.bases if isinstance(b, ast.Name)]}
                )
                self._graph.add_edge(file_id, sym_id, kind="defines", weight=1.0)
                self._file_to_nodes[rel_path].append(sym_id)
                self._symbol_to_node[f"{rel_path}::{node.name}"] = sym_id

                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_id = f"symbol:{rel_path}::{node.name}.{item.name}"
                        self._graph.add_node(method_id, kind="method", label=item.name, path=rel_path, line=item.lineno)
                        self._node_index[method_id] = NodeInfo(
                            id=method_id, kind="method", label=item.name, language="python", path=rel_path,
                            metadata={"line": item.lineno, "class": node.name}
                        )
                        self._graph.add_edge(sym_id, method_id, kind="defines", weight=1.0)
                        self._symbol_to_node[f"{rel_path}::{node.name}.{item.name}"] = method_id

            elif isinstance(node, ast.FunctionDef):
                if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree) if hasattr(parent, 'body') and node in getattr(parent, 'body', [])):
                    sym_id = f"symbol:{rel_path}::{node.name}"
                    self._graph.add_node(sym_id, kind="function", label=node.name, path=rel_path, line=node.lineno)
                    self._node_index[sym_id] = NodeInfo(
                        id=sym_id, kind="function", label=node.name, language="python", path=rel_path,
                        metadata={"line": node.lineno, "args": [a.arg for a in node.args.args]}
                    )
                    self._graph.add_edge(file_id, sym_id, kind="defines", weight=1.0)
                    self._file_to_nodes[rel_path].append(sym_id)
                    self._symbol_to_node[f"{rel_path}::{node.name}"] = sym_id

            elif isinstance(node, ast.Call):
                self._extract_call_edges(file_id, rel_path, node)

    def _extract_call_edges(self, file_id: str, rel_path: str, node: ast.Call) -> None:
        """Extrai arestas de chamada de função."""
        assert self._graph is not None

        if isinstance(node.func, ast.Name):
            called = node.func.id
            called_id = self._resolve_symbol(called, rel_path)
            if called_id and called_id != file_id:
                self._graph.add_edge(file_id, called_id, kind="calls", weight=0.7)
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj = node.func.value.id
                method = node.func.attr
                called_id = self._resolve_symbol(f"{obj}.{method}", rel_path)
                if called_id and called_id != file_id:
                    self._graph.add_edge(file_id, called_id, kind="calls", weight=0.7)

    def _resolve_symbol(self, name: str, current_file: str) -> str | None:
        """Resolve um símbolo para seu nó no grafo."""
        # Tenta símbolo qualificado
        for key, node_id in self._symbol_to_node.items():
            if key.endswith(f"::{name}") or key == name:
                return node_id
        return None

    def _extract_js_ts_symbols(self, rel_path: str, file_path: Path) -> None:
        """Extrai símbolos JavaScript/TypeScript (básico via regex)."""
        assert self._graph is not None

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        file_id = f"file:{rel_path}"

        # Imports
        import_pattern = re.compile(r'import\s+(?:(?:\w+|\{[\w\s,]+\})\s+from\s+)?[\'"]([^\'"]+)[\'"]')
        for match in import_pattern.finditer(content):
            mod = match.group(1)
            mod_id = f"module:{mod}"
            if not self._graph.has_node(mod_id):
                self._graph.add_node(mod_id, kind="module", label=mod)
                self._node_index[mod_id] = NodeInfo(id=mod_id, kind="module", label=mod)
            self._graph.add_edge(file_id, mod_id, kind="imports", weight=1.0)

        # Functions
        func_pattern = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)')
        for match in func_pattern.finditer(content):
            name = match.group(1)
            sym_id = f"symbol:{rel_path}::{name}"
            self._graph.add_node(sym_id, kind="function", label=name, path=rel_path)
            self._node_index[sym_id] = NodeInfo(id=sym_id, kind="function", label=name, language="javascript", path=rel_path)
            self._graph.add_edge(file_id, sym_id, kind="defines", weight=1.0)
            self._file_to_nodes[rel_path].append(sym_id)
            self._symbol_to_node[f"{rel_path}::{name}"] = sym_id

        # Classes
        class_pattern = re.compile(r'(?:export\s+)?class\s+(\w+)')
        for match in class_pattern.finditer(content):
            name = match.group(1)
            sym_id = f"symbol:{rel_path}::{name}"
            self._graph.add_node(sym_id, kind="class", label=name, path=rel_path)
            self._node_index[sym_id] = NodeInfo(id=sym_id, kind="class", label=name, language="javascript", path=rel_path)
            self._graph.add_edge(file_id, sym_id, kind="defines", weight=1.0)
            self._file_to_nodes[rel_path].append(sym_id)
            self._symbol_to_node[f"{rel_path}::{name}"] = sym_id

    def _extract_config_symbols(self, rel_path: str, file_path: Path) -> None:
        """Extrai símbolos de arquivos de configuração."""
        assert self._graph is not None

        file_id = f"file:{rel_path}"
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        if rel_path.endswith("package.json"):
            try:
                data = json.loads(content)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for dep in deps:
                    mod_id = f"module:{dep}"
                    if not self._graph.has_node(mod_id):
                        self._graph.add_node(mod_id, kind="module", label=dep)
                        self._node_index[mod_id] = NodeInfo(id=mod_id, kind="module", label=dep)
                    self._graph.add_edge(file_id, mod_id, kind="imports", weight=0.8)
            except json.JSONDecodeError:
                pass

    def _add_cross_file_edges(self) -> None:
        """Adiciona arestas entre arquivos baseadas em imports e referências."""
        assert self._graph is not None

        # Test files -> implementation files
        for file_id in list(self._graph.nodes):
            node_data = self._graph.nodes[file_id]
            if node_data.get("kind") == "file" and "test" in node_data.get("path", ""):
                path = node_data.get("path", "")
                # Heurística: test_foo.py -> foo.py
                impl_candidates = [
                    path.replace("test_", "").replace("_test", "").replace("tests/", ""),
                    path.replace("test_", "").replace("_test", ""),
                ]
                for cand in impl_candidates:
                    impl_id = f"file:{cand}"
                    if self._graph.has_node(impl_id):
                        self._graph.add_edge(file_id, impl_id, kind="tests", weight=0.9)

    def update_file(self, rel_path: str) -> None:
        """Atualiza incrementalmente um arquivo no grafo.

        Args:
            rel_path: caminho relativo do arquivo alterado.
        """
        self._ensure_nx()
        if self._graph is None:
            self.initialize()
            return

        file_id = f"file:{rel_path}"
        file_path = self.project_root / rel_path

        # Remove nós antigos do arquivo
        old_nodes = self._file_to_nodes.get(rel_path, [])
        for node_id in old_nodes:
            if node_id != file_id and self._graph.has_node(node_id):
                # Remove referências do symbol_to_node
                for sym_key, sym_node in list(self._symbol_to_node.items()):
                    if sym_node == node_id:
                        del self._symbol_to_node[sym_key]
                self._graph.remove_node(node_id)

        if file_path.exists():
            self._add_file_node(rel_path, file_path)
        else:
            # Arquivo deletado
            if self._graph.has_node(file_id):
                self._graph.remove_node(file_id)
            self._file_to_nodes.pop(rel_path, None)

        self._add_cross_file_edges()
        self._version += 1

    def get_dependents(self, node_id: str, *, max_depth: int = 3) -> list[str]:
        """Retorna nós que dependem do nó dado (transitivo até max_depth)."""
        self._ensure_nx()
        if self._graph is None or not self._graph.has_node(node_id):
            return []

        dependents = set()
        current = {node_id}
        for depth in range(max_depth):
            next_level = set()
            for n in current:
                preds = list(self._graph.predecessors(n))
                next_level.update(preds)
            dependents.update(next_level)
            current = next_level
            if not current:
                break
        return list(dependents)

    def get_dependencies(self, node_id: str, *, max_depth: int = 3) -> list[str]:
        """Retorna nós dos quais o nó dado depende (transitivo até max_depth)."""
        self._ensure_nx()
        if self._graph is None or not self._graph.has_node(node_id):
            return []

        dependencies = set()
        current = {node_id}
        for depth in range(max_depth):
            next_level = set()
            for n in current:
                succs = list(self._graph.successors(n))
                next_level.update(succs)
            dependencies.update(next_level)
            current = next_level
            if not current:
                break
        return list(dependencies)

    def get_affected_tests(self, changed_files: list[str]) -> list[str]:
        """Retorna arquivos de teste afetados por mudanças nos arquivos dados."""
        self._ensure_nx()
        if self._graph is None:
            return []

        affected = set()
        for f in changed_files:
            file_id = f"file:{f}"
            if self._graph.has_node(file_id):
                deps = self.get_dependents(file_id, max_depth=5)
                for dep in deps:
                    node_data = self._graph.nodes[dep]
                    if node_data.get("kind") == "file" and "test" in node_data.get("path", ""):
                        affected.add(node_data["path"])
        return sorted(affected)

    def compute_transitive_closure(self, start_nodes: list[str]) -> set[str]:
        """Computa o fecho transitivo a partir de nós iniciais (seguindo arestas de saída)."""
        self._ensure_nx()
        if self._graph is None:
            return set()

        closure = set(start_nodes)
        frontier = set(start_nodes)
        while frontier:
            next_frontier = set()
            for n in frontier:
                for succ in self._graph.successors(n):
                    if succ not in closure:
                        closure.add(succ)
                        next_frontier.add(succ)
            frontier = next_frontier
        return closure

    def get_node_info(self, node_id: str) -> NodeInfo | None:
        """Retorna informações de um nó."""
        return self._node_index.get(node_id)

    def get_file_node_id(self, rel_path: str) -> str:
        """Retorna o ID do nó de arquivo para um caminho."""
        return f"file:{rel_path}"

    def stats(self) -> dict[str, Any]:
        """Estatísticas do grafo."""
        if self._graph is None:
            return {"nodes": 0, "edges": 0, "version": self._version}
        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "version": self._version,
            "files": len(self._file_to_nodes),
            "symbols": len(self._symbol_to_node),
        }


class ImpactAnalyzer:
    """Analisador de impacto de mudanças no projeto.

    Usa o grafo de dependências para estimar quais componentes são afetados
    por uma mudança e qual o risco associado.
    """

    def __init__(self, graph: DependencyGraph) -> None:
        """Cria o analisador com um grafo de dependências.

        Args:
            graph: grafo de dependências do projeto.
        """
        self.graph = graph

    def analyze(self, changed_files: list[str]) -> ImpactResult:
        """Analisa o impacto de uma lista de arquivos alterados.

        Args:
            changed_files: lista de caminhos relativos dos arquivos alterados.

        Returns:
            Resultado da análise de impacto.
        """
        if not changed_files:
            return ImpactResult(
                changed_files=[],
                affected_nodes=[],
                affected_files=[],
                test_files=[],
                risk_score=0.0,
                breaking_changes=[],
                propagation_depth=0,
            )

        self.graph._ensure_nx()
        assert self.graph._graph is not None

        affected_nodes = set()
        affected_files = set()
        max_depth = 0

        for f in changed_files:
            file_id = self.graph.get_file_node_id(f)
            if not self.graph._graph.has_node(file_id):
                continue

            # Fecho transitivo das dependências (o que este arquivo afeta)
            deps = self.graph.get_dependents(file_id, max_depth=5)
            affected_nodes.update(deps)

            # Profundidade de propagação
            for dep in deps:
                node_data = self.graph._graph.nodes[dep]
                if node_data.get("kind") == "file":
                    affected_files.add(node_data["path"])
                    # Calcula profundidade via caminho mais curto
                    try:
                        path_len = nx.shortest_path_length(self.graph._graph, file_id, dep)
                        max_depth = max(max_depth, path_len)
                    except nx.NetworkXNoPath:
                        pass

        affected_files_list = sorted(affected_files)
        test_files = self.graph.get_affected_tests(changed_files)

        # Calcula breaking changes (heurística)
        breaking_changes = self._detect_breaking_changes(changed_files, affected_nodes)

        # Risk score
        risk_score = self._calculate_risk_score(
            len(changed_files), len(affected_files_list), len(test_files),
            len(breaking_changes), max_depth
        )

        return ImpactResult(
            changed_files=changed_files,
            affected_nodes=sorted(affected_nodes),
            affected_files=affected_files_list,
            test_files=test_files,
            risk_score=risk_score,
            breaking_changes=breaking_changes,
            propagation_depth=max_depth,
        )

    def _detect_breaking_changes(self, changed_files: list[str], affected_nodes: set[str]) -> list[dict[str, Any]]:
        """Detecta mudanças potencialmente quebradoras de contrato."""
        breaking = []

        for f in changed_files:
            file_id = self.graph.get_file_node_id(f)
            if not self.graph._graph.has_node(file_id):
                continue

            node_data = self.graph._graph.nodes[file_id]
            path = node_data.get("path", "")

            # Verifica se é arquivo de interface/contrato
            if path.endswith((".pyi", ".d.ts", ".h", ".hpp")):
                breaking.append({
                    "type": "interface_file",
                    "file": path,
                    "severity": "high",
                    "reason": "Arquivo de interface/tipo alterado",
                })

            # Verifica símbolos públicos alterados
            for affected in affected_nodes:
                affected_data = self.graph._graph.nodes.get(affected, {})
                if affected_data.get("kind") in {"class", "function", "method"}:
                    meta = affected_data.get("metadata", {})
                    if not meta.get("private", False):
                        breaking.append({
                            "type": "public_symbol",
                            "symbol": affected_data.get("label", ""),
                            "file": affected_data.get("path", ""),
                            "severity": "medium",
                            "reason": "Símbolo público potencialmente alterado",
                        })

        return breaking[:20]  # Limita

    def _calculate_risk_score(
        self,
        num_changed: int,
        num_affected: int,
        num_tests: int,
        num_breaking: int,
        max_depth: int,
    ) -> float:
        """Calcula pontuação de risco (0-100)."""
        score = 0.0

        # Fator: número de arquivos alterados
        score += min(num_changed * 5, 20)

        # Fator: propagação
        score += min(num_affected * 2, 30)

        # Fator: testes afetados
        score += min(num_tests * 3, 20)

        # Fator: breaking changes
        score += min(num_breaking * 10, 20)

        # Fator: profundidade
        score += min(max_depth * 2, 10)

        return min(score, 100.0)


def compute_transitive_closure(graph: DependencyGraph, start_nodes: list[str]) -> set[str]:
    """Função utilitária para computar fecho transitivo."""
    return graph.compute_transitive_closure(start_nodes)