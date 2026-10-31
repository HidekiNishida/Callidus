"""
Arquivo: src/agent/engineering/context_retrieval.py
Nome: context_retrieval.py
Propósito: recuperação seletiva de contexto para operações do agente.
Responsabilidade: camada de aplicação — seleção, ranqueio e carregamento sob demanda de componentes de contexto.
Componentes: ContextRetriever, RetrievalQuery, RetrievalResult, ComponentScorer.
Dependências: agent.engineering.dependency_graph, agent.context.budget, agent.memory.operational.
Observações: prioriza componentes por relevância à tarefa, reutiliza snapshots e invalida por dependência.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from agent.context.budget import ContextComponent, estimate_tokens
from agent.engineering.dependency_graph import DependencyGraph, ImpactAnalyzer
from agent.memory.operational import render_for_prompt
from agent.persistence.models import TaskModel


@dataclass
class RetrievalQuery:
    """Consulta de recuperação de contexto.

    Atributos:
        task: tarefa que solicita o contexto.
        objective: objetivo textual da operação.
        required_files: arquivos que devem ser incluídos (ex: sendo editados).
        excluded_files: arquivos a excluir.
        max_tokens: orçamento máximo de tokens.
        include_tests: se deve incluir arquivos de teste.
        include_dependencies: se deve incluir dependências transitivas.
        include_memory: se deve incluir memória operacional.
        include_knowledge: se deve incluir símbolos do grafo de conhecimento.
        focus_symbols: símbolos específicos para focar.
    """
    task: TaskModel
    objective: str
    required_files: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    max_tokens: int = 8000
    include_tests: bool = True
    include_dependencies: bool = True
    include_memory: bool = True
    include_knowledge: bool = True
    focus_symbols: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    """Resultado da recuperação de contexto.

    Atributos:
        components: componentes selecionados para o prompt.
        estimated_tokens: total estimado de tokens.
        dropped: componentes não incluídos por falta de orçamento.
        coverage: informações sobre o que foi coberto.
        retrieval_time_ms: tempo gasto na recuperação.
    """
    components: list[ContextComponent]
    estimated_tokens: int
    dropped: list[str]
    coverage: dict[str, Any]
    retrieval_time_ms: float


class ComponentScorer:
    """Avaliador de relevância de componentes de contexto."""

    def __init__(self, query: RetrievalQuery, graph: DependencyGraph | None = None) -> None:
        """Inicializa o avaliador.

        Args:
            query: consulta de recuperação.
            graph: grafo de dependências opcional para análise de impacto.
        """
        self.query = query
        self.graph = graph
        self.impact_analyzer = ImpactAnalyzer(graph) if graph else None
        self._objective_tokens = self._tokenize(query.objective)
        self._focus_tokens = set()
        for sym in query.focus_symbols:
            self._focus_tokens.update(self._tokenize(sym))

    def _tokenize(self, text: str) -> set[str]:
        """Tokeniza texto em palavras significativas."""
        return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower()))

    def score_file(self, rel_path: str, content: str | None = None) -> float:
        """Avalia a relevância de um arquivo.

        Args:
            rel_path: caminho relativo do arquivo.
            content: conteúdo do arquivo (opcional, para análise mais profunda).

        Returns:
            Score de relevância (0-100).
        """
        score = 0.0
        path_lower = rel_path.lower()
        objective_lower = self.query.objective.lower()

        # 1. Arquivo explicitamente requerido
        if rel_path in self.query.required_files:
            return 100.0

        # 2. Arquivo excluído
        if rel_path in self.query.excluded_files:
            return -100.0

        # 3. Match direto no objetivo
        path_tokens = self._tokenize(rel_path)
        overlap = len(path_tokens & self._objective_tokens)
        score += overlap * 10

        # 4. Símbolos de foco
        if content:
            content_lower = content.lower()
            for sym in self.query.focus_symbols:
                if sym.lower() in content_lower:
                    score += 15

        # 5. Tipo de arquivo
        if path_lower.endswith((".py", ".js", ".ts", ".jsx", ".tsx")):
            score += 5
        elif path_lower.endswith((".json", ".toml", ".yaml", ".yml")):
            score += 3
        elif "test" in path_lower:
            score += 2 if self.query.include_tests else -5

        # 6. Impacto via grafo de dependências
        if self.impact_analyzer and self.graph:
            try:
                file_id = self.graph.get_file_node_id(rel_path)
                if self.graph._graph and self.graph._graph.has_node(file_id):
                    deps = self.graph.get_dependents(file_id, max_depth=3)
                    if deps:
                        score += min(len(deps) * 2, 20)
            except Exception:
                pass

        # 7. Recência (arquivos modificados recentemente ganham bonus)
        # Isso seria verificado via filesystem, omitido aqui por simplicidade

        return max(score, 0.0)

    def score_symbol(self, symbol_name: str, file_path: str, symbol_kind: str) -> float:
        """Avalia a relevância de um símbolo."""
        score = 0.0
        sym_lower = symbol_name.lower()

        # Match direto no objetivo
        if sym_lower in self.query.objective.lower():
            score += 30

        # Match em símbolos de foco
        if sym_lower in self._focus_tokens:
            score += 25

        # Tipo de símbolo
        if symbol_kind in {"class", "function", "method"}:
            score += 10
        elif symbol_kind == "module":
            score += 5

        # Arquivo do símbolo
        file_score = self.score_file(file_path)
        score += file_score * 0.3

        return score


class ContextRetriever:
    """Recuperador de contexto para operações do agente.

    Seleciona, ranqueia e monta componentes de contexto respeitando o orçamento de tokens.
    """

    def __init__(
        self,
        session: Session,
        project_root: str,
        graph: DependencyGraph | None = None,
    ) -> None:
        """Inicializa o recuperador.

        Args:
            session: sessão do banco de dados.
            project_root: raiz do projeto.
            graph: grafo de dependências (opcional, será criado se não fornecido).
        """
        self.session = session
        self.project_root = Path(project_root).expanduser().resolve()
        self.graph = graph or DependencyGraph(project_root)
        if not self.graph._initialized:
            self.graph.initialize()

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Recupera contexto para uma consulta.

        Args:
            query: consulta de recuperação.

        Returns:
            Componentes de contexto selecionados.
        """
        import time
        start = time.perf_counter()

        scorer = ComponentScorer(query, self.graph)
        components: list[ContextComponent] = []
        dropped: list[str] = []

        # 1. Memória operacional da tarefa (sempre prioritária)
        if query.include_memory:
            mem_component = self._get_operational_memory(query.task)
            if mem_component:
                components.append(mem_component)

        # 2. Arquivos requeridos explicitamente
        for rel_path in query.required_files:
            comp = self._get_file_component(rel_path, required=True)
            if comp:
                components.append(comp)

        # 3. Arquivos de dependência (impacto)
        if query.include_dependencies and self.impact_analyzer:
            impact = self.impact_analyzer.analyze(query.required_files)
            for rel_path in impact.affected_files:
                if rel_path not in query.required_files and rel_path not in query.excluded_files:
                    comp = self._get_file_component(rel_path)
                    if comp:
                        components.append(comp)

        # 4. Arquivos de teste afetados
        if query.include_tests and self.impact_analyzer:
            impact = self.impact_analyzer.analyze(query.required_files)
            for rel_path in impact.test_files:
                if rel_path not in query.excluded_files:
                    comp = self._get_file_component(rel_path)
                    if comp:
                        components.append(comp)

        # 5. Símbolos do grafo de conhecimento
        if query.include_knowledge and query.focus_symbols:
            symbol_components = self._get_symbol_components(query.focus_symbols, scorer)
            components.extend(symbol_components)

        # 6. Arquivos do projeto por relevância (preenche orçamento restante)
        project_files = self._list_project_files(query.excluded_files)
        scored_files: list[tuple[float, str]] = []
        for rel_path in project_files:
            if any(c.name.endswith(rel_path) for c in components):
                continue
            # Amostra o conteúdo para scoring
            content = self._read_file_safe(rel_path)
            score = scorer.score_file(rel_path, content)
            if score > 0:
                scored_files.append((score, rel_path))

        # Ordena por score decrescente
        scored_files.sort(key=lambda x: -x[0])

        # Adiciona até estourar orçamento
        budget = query.max_tokens
        current_tokens = sum(estimate_tokens(c.text) for c in components)

        for score, rel_path in scored_files:
            comp = self._get_file_component(rel_path)
            if not comp:
                continue
            comp_tokens = estimate_tokens(comp.text)
            if current_tokens + comp_tokens <= budget:
                components.append(comp)
                current_tokens += comp_tokens
            else:
                dropped.append(rel_path)

        # Monta cobertura
        coverage = {
            "files_included": len([c for c in components if c.category == "file"]),
            "memory_included": any(c.category == "memory" for c in components),
            "symbols_included": len([c for c in components if c.category == "symbol"]),
            "tests_included": len([c for c in components if "test" in c.name.lower()]),
            "required_files_met": all(
                any(c.name.endswith(f) for c in components) for f in query.required_files
            ),
        }

        retrieval_time = (time.perf_counter() - start) * 1000
        return RetrievalResult(
            components=components,
            estimated_tokens=current_tokens,
            dropped=dropped,
            coverage=coverage,
            retrieval_time_ms=retrieval_time,
        )

    def _get_operational_memory(self, task: TaskModel) -> ContextComponent | None:
        """Recupera memória operacional da tarefa."""
        try:
            text = render_for_prompt(self.session, task)
            if text and text.strip():
                return ContextComponent(
                    name="memória-operacional",
                    text=text,
                    priority=100,
                    required=True,
                    category="memory",
                )
        except Exception:
            pass
        return None

    def _get_file_component(self, rel_path: str, required: bool = False) -> ContextComponent | None:
        """Cria componente de contexto a partir de um arquivo."""
        try:
            full_path = self.project_root / rel_path
            if not full_path.is_file():
                return None

            # Limita tamanho do arquivo
            max_chars = 50000
            content = full_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... [arquivo truncado: {len(content)} chars total]"

            return ContextComponent(
                name=f"arquivo:{rel_path}",
                text=f"## {rel_path}\n\n```\n{content}\n```",
                priority=80 if required else 50,
                required=required,
                category="file",
            )
        except Exception:
            return None

    def _get_symbol_components(self, symbols: list[str], scorer: ComponentScorer) -> list[ContextComponent]:
        """Recupera componentes para símbolos específicos."""
        components = []

        for sym in symbols:
            # Busca no grafo
            node_id = None
            for key, nid in self.graph._symbol_to_node.items():
                if key.endswith(f"::{sym}") or key == sym:
                    node_id = nid
                    break

            if node_id and self.graph._graph and self.graph._graph.has_node(node_id):
                node_data = self.graph._graph.nodes[node_id]
                file_path = node_data.get("path", "")
                label = node_data.get("label", sym)
                kind = node_data.get("kind", "symbol")

                # Tenta ler o trecho do símbolo no arquivo
                snippet = self._extract_symbol_snippet(file_path, label, kind)
                if snippet:
                    score = scorer.score_symbol(label, file_path, kind)
                    components.append(ContextComponent(
                        name=f"símbolo:{file_path}::{label}",
                        text=f"## {kind.title()}: {label} ({file_path})\n\n```\n{snippet}\n```",
                        priority=int(score),
                        required=False,
                        category="symbol",
                    ))

        return components

    def _extract_symbol_snippet(self, file_path: str, symbol: str, kind: str) -> str | None:
        """Extrai trecho do símbolo no arquivo."""
        try:
            full_path = self.project_root / file_path
            if not full_path.is_file():
                return None

            content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            # Busca simples por linha contendo o símbolo
            for i, line in enumerate(lines):
                if symbol in line and (f"def {symbol}" in line or f"class {symbol}" in line or f"function {symbol}" in line):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 30)
                    return "\n".join(lines[start:end])

            return None
        except Exception:
            return None

    def _list_project_files(self, excluded: list[str]) -> list[str]:
        """Lista arquivos do projeto candidatos a contexto."""
        files = []
        skip_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}

        for file_path in self.project_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in skip_dirs for part in file_path.parts):
                continue

            rel = str(file_path.relative_to(self.project_root))
            if rel in excluded:
                continue

            suffix = file_path.suffix.lower()
            if suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".toml", ".yaml", ".yml", ".md", ".txt"}:
                files.append(rel)

        return files[:200]  # Limita para performance

    def _read_file_safe(self, rel_path: str) -> str | None:
        """Lê arquivo com tratamento de erro."""
        try:
            return (self.project_root / rel_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None


class IncrementalContextManager:
    """Gerenciador de contexto incremental com invalidação por dependência.

    Mantém snapshots de contexto e invalida apenas o necessário quando arquivos mudam.
    """

    def __init__(self, session: Session, project_root: str, graph: DependencyGraph) -> None:
        """Inicializa o gerenciador.

        Args:
            session: sessão do banco.
            project_root: raiz do projeto.
            graph: grafo de dependências.
        """
        self.session = session
        self.project_root = project_root
        self.graph = graph
        self._snapshots: dict[str, dict[str, Any]] = {}  # task_id -> {file_hash -> component}
        self._file_hashes: dict[str, str] = {}

    def get_snapshot(self, task: TaskModel) -> dict[str, Any] | None:
        """Recupera snapshot de contexto de uma tarefa."""
        task_id = str(task.id)
        return self._snapshots.get(task_id)

    def update_snapshot(self, task: TaskModel, components: list[ContextComponent]) -> None:
        """Atualiza snapshot de uma tarefa."""
        task_id = str(task.id)
        snapshot = {}
        for comp in components:
            if comp.category == "file" and comp.name.startswith("arquivo:"):
                rel_path = comp.name[len("arquivo:"):]
                file_hash = self._compute_file_hash(rel_path)
                if file_hash:
                    self._file_hashes[rel_path] = file_hash
                    snapshot[rel_path] = {
                        "component": comp,
                        "hash": file_hash,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
        self._snapshots[task_id] = snapshot

    def invalidate(self, changed_files: list[str]) -> dict[str, list[str]]:
        """Invalida snapshots afetados por mudanças.

        Args:
            changed_files: arquivos que mudaram.

        Returns:
            Dicionário task_id -> lista de arquivos invalidados naquela tarefa.
        """
        invalidated: dict[str, list[str]] = defaultdict(list)

        for task_id, snapshot in self._snapshots.items():
            for rel_path in changed_files:
                if rel_path in snapshot:
                    old_hash = snapshot[rel_path]["hash"]
                    new_hash = self._compute_file_hash(rel_path)
                    if new_hash and new_hash != old_hash:
                        invalidated[task_id].append(rel_path)
                        # Atualiza hash
                        self._file_hashes[rel_path] = new_hash
                        snapshot[rel_path]["hash"] = new_hash

        return dict(invalidated)

    def _compute_file_hash(self, rel_path: str) -> str | None:
        """Computa hash SHA256 de um arquivo."""
        try:
            full_path = Path(self.project_root) / rel_path
            if not full_path.is_file():
                return None
            content = full_path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except Exception:
            return None

    def get_reusable_components(self, task: TaskModel, query: RetrievalQuery) -> list[ContextComponent]:
        """Recupera componentes reutilizáveis do snapshot (não invalidados)."""
        snapshot = self.get_snapshot(task)
        if not snapshot:
            return []

        reusable = []
        for rel_path, data in snapshot.items():
            if rel_path in query.excluded_files:
                continue
            if rel_path in query.required_files:
                reusable.append(data["component"])
                continue
            # Verifica se hash ainda confere
            current_hash = self._compute_file_hash(rel_path)
            if current_hash and current_hash == data["hash"]:
                reusable.append(data["component"])

        return reusable