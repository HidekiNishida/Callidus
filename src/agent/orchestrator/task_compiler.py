"""
Arquivo: src/agent/orchestrator/task_compiler.py
Nome: task_compiler.py
Propósito: compilador de tarefas — transforma uma intenção em TaskIR com operações pequenas,
dependências explícitas, componentes afetados, critérios de aceitação verificáveis e orçamentos.
Responsabilidade: camada de aplicação — compila a intenção do usuário em uma representação
intermediária (TaskIR) usando inteligência determinística do projeto (descoberta, grafo de
dependências, grafo de conhecimento), sem depender apenas do modelo.
Componentes: TaskCompiler, CompileResult.
Dependências: agent.engineering.discovery, agent.engineering.dependency_graph, agent.knowledge.graph_service,
agent.orchestrator.task_ir, agent.persistence.models, pydantic, uuid, hashlib, pathlib, re.
Observações: não cria novas tabelas; escreve no `metadata_json` da tarefa via `apply_ir_to_task`.
O compilador roda antes do planejamento do modelo e enriquece o contexto com fatos do projeto,
de modo que o modelo receba operações pequenas e contextualizadas em vez de uma tarefa ampla.
"""

from __future__ import annotations

import uuid
from dataclasses import field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

from pydantic import BaseModel

from agent.engineering.dependency_graph import DependencyGraph, ImpactAnalyzer
from agent.engineering.discovery import detect_project, discover_commands, read_manifest
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.orchestrator.task_ir import (
    ArtifactRef,
    ContextBudget,
    ExecutionConstraint,
    TaskIR,
    apply_ir_to_task,
)

if TYPE_CHECKING:
    from agent.persistence.models import ProjectModel

#: Operações de inspeção que toda tarefa complexa começa com.
_DEFAULT_TOOLS = ["list_dir", "glob_files", "search_grep", "read_file"]

#: Limite de operações por plano (evita planos gigantescos).
_MAX_OPERATIONS = 12


class CompileResult(BaseModel):
    """Resultado da compilação de uma tarefa.

    Atributos:
        ir: TaskIR compilado.
        task_id: identificador da tarefa criada/atualizada no banco.
        source: origem do plano (`compiler`, `fallback`, `model`).
        warnings: avisos sobre o que o compilador não pôde determinar.
    """

    ir: TaskIR
    task_id: uuid.UUID
    source: str = "compiler"
    warnings: list[str] = field(default_factory=list)


class TaskCompiler:
    """Compila uma intenção de usuário em um TaskIR estruturado.

    Usa ferramentas determinísticas do projeto (descoberta de dependências, grafo de
    conhecimento, inspeção de manifesto) para identificar componentes afetados, operações
    necessárias e critérios de aceitação, antes de qualquer inferência do modelo.

    Atributos:
        _session: sessão SQLAlchemy para persistir o IR.
        _project: modelo do projeto.
        _root: caminho raiz do projeto.
        _kg: serviço de grafo de conhecimento.
        _dep_graph: grafo de dependências do projeto.
    """

    def __init__(self, session: Any, project: ProjectModel) -> None:
        """Cria o compilador ligado a um projeto.

        Args:
            session: sessão SQLAlchemy.
            project: modelo do projeto.
        """
        self._session = session
        self._project = project
        self._root = project.root_path
        self._kg = KnowledgeGraphService(session)
        self._dep_graph = DependencyGraph(self._root)

    def compile(
        self,
        objective: str,
        *,
        parent_id: uuid.UUID | None = None,
        depth: int = 0,
        requirements: list[dict[str, Any]] | None = None,
    ) -> CompileResult:
        """Compila uma intenção em um TaskIR.

        Fluxo:
        1. Detecta o tipo de projeto, manifesto e comandos disponíveis.
        2. Identifica arquivos e símbolos relacionados ao objetivo.
        3. Calcula componentes afetados via grafo de dependências.
        4. Divide o trabalho em operações pequenas (inspeção → alteração → verificação).
        5. Define critérios de aceitação e orçamentos.
        6. Persiste o IR na tarefa.

        Args:
            objective: intenção do usuário.
            parent_id: tarefa-pai (None para raiz).
            depth: profundidade na árvore de tarefas.
            requirements: requisitos já derivados (análise de lacunas).

        Returns:
            O `CompileResult` com o TaskIR e a tarefa persistida.
        """
        warnings: list[str] = []

        # 1. Descoberta determinística do projeto.
        project_info = detect_project(self._root)
        manifest = read_manifest(self._root)
        commands = discover_commands(self._root)

        # 2. Reindexa o grafo de conhecimento para ter símbolos atualizados.
        try:
            self._kg.reindex(self._project.id, self._root)
        except Exception as exc:  # pragma: no cover - falha do grafo não bloqueia a compilação
            warnings.append(f"grafo de conhecimento indisponível: {exc}")

        # 3. Símbolos relacionados ao objetivo.
        related = self._find_related(objective)

        # 4. Componentes afetados via grafo de dependências.
        affected = self._affected_components(related)

        # 5. Operações pequenas.
        operations = self._build_operations(objective, related, affected, manifest, commands)

        # 6. Critérios de aceitação.
        acceptance = self._derive_acceptance(objective, related, requirements or [])

        # 7. Orçamento de contexto.
        budget = self._budget(objective, len(operations), depth)

        # 8. Restrições.
        constraints = self._constraints(manifest, project_info)

        # 9. Monta o TaskIR.
        ir = TaskIR(
            objective=objective,
            parent_id=parent_id,
            requirements=requirements or [],
            constraints=constraints,
            acceptance_criteria=acceptance,
            complexity=self._complexity(objective, affected, len(operations)),
            context_budget=budget,
            affected_components=affected,
            allowed_tools=_DEFAULT_TOOLS,
            allowed_files=self._allowed_files(related),
            expected_artifacts=self._expected_artifacts(affected),
            operations=operations,
            depth=depth,
            max_attempts=8,
            max_depth=16,
            status="pending",
        )

        # 10. Persiste.
        task_id = apply_ir_to_task(self._session, ir, self._project.id)

        return CompileResult(ir=ir, task_id=task_id, source="compiler", warnings=warnings)

    # -- passos internos de compilação -------------------------------------

    def _find_related(self, objective: str) -> list[dict[str, Any]]:
        """Busca símbolos e arquivos relacionados ao objetivo no grafo de conhecimento."""
        related: list[dict[str, Any]] = []
        try:
            results = self._kg.search(self._project.id, objective, limit=8)
            related.extend(
                [
                    {
                        "kind": r.get("kind", "file"),
                        "ref": r.get("ref", ""),
                        "path": r.get("ref", ""),
                        "description": r.get("description", ""),
                    }
                    for r in results
                ]
            )
        except Exception:
            pass
        return related

    def _affected_components(self, related: list[dict[str, Any]]) -> list[str]:
        """Componentes afetados: caminhos dos símbolos relacionados e seus dependentes."""
        paths: set[str] = set()
        for item in related:
            path = item.get("path", "")
            if path:
                paths.add(path)
        # Tenta rastrear dependentes via grafo de dependências.
        try:
            analyzer = ImpactAnalyzer(self._dep_graph)
            for path in list(paths):
                node_id = self._dep_graph.get_file_node_id(path)
                if node_id:
                    for dep in analyzer.graph.get_dependents(node_id):
                        paths.add(dep)
        except Exception:
            pass
        return sorted(paths)

    def _build_operations(
        self,
        objective: str,
        related: list[dict[str, Any]],
        affected: list[str],
        _manifest: dict[str, Any],
        _commands: list[str],
    ) -> list[dict[str, Any]]:
        """Divide o trabalho em operações pequenas e ordenadas."""
        ops: list[dict[str, Any]] = []

        # Operação 0: inspecionar arquivos relacionados.
        inspect_files = [r["path"] for r in related if r.get("path")][:5] or affected[:5]
        ops.append(
            {
                "id": "inspect",
                "title": "Inspecionar arquivos relacionados",
                "objective": f"Ler e entender os arquivos relacionados a: {objective[:80]}",
                "kind": "inspection",
                "files": inspect_files,
                "depends_on": [],
                "acceptance": "Arquivos relacionados lidos e resumidos",
                "budget": {"max_input_tokens": 4000, "max_output_tokens": 1024},
            }
        )

        # Operação 1: analisar impacto das alterações.
        if affected:
            ops.append(
                {
                    "id": "analyze_impact",
                    "title": "Analisar impacto das alterações",
                    "objective": "Identificar quem usa os componentes afetados e o que pode quebrar",
                    "kind": "analysis",
                    "files": affected[:8],
                    "depends_on": ["inspect"],
                    "acceptance": "Dependências e impactos mapeados",
                    "budget": {"max_input_tokens": 3000, "max_output_tokens": 768},
                }
            )

        # Operação 2: implementar a mudança.
        ops.append(
            {
                "id": "implement",
                "title": "Implementar a mudança",
                "objective": f"Aplicar a alteração pedida: {objective[:80]}",
                "kind": "model_operation",
                "files": affected[:8],
                "depends_on": ["analyze_impact"] if affected else ["inspect"],
                "acceptance": "Alteração aplicada e arquivos gravados",
                "budget": {"max_input_tokens": 5000, "max_output_tokens": 2048},
            }
        )

        # Operação 3: verificar.
        test_files = [r["path"] for r in related if "test" in r.get("path", "").lower()][:3]
        verification = {
            "id": "verify",
            "title": "Verificar a alteração",
            "objective": "Executar testes e validações relacionadas à mudança",
            "kind": "verification",
            "files": test_files or [],
            "depends_on": ["implement"],
            "acceptance": "Testes aprovados e verificação concluída",
            "budget": {"max_input_tokens": 2500, "max_output_tokens": 1024},
        }
        ops.append(verification)

        # Operação 4: resposta final (se não for apenas verificação).
        ops.append(
            {
                "id": "final_answer",
                "title": "Responder ao usuário",
                "objective": "Entregar o resumo da execução e o resultado da verificação",
                "kind": "final_answer",
                "files": [],
                "depends_on": ["verify"],
                "acceptance": "Resposta entregue com evidências de conclusão",
                "budget": {"max_input_tokens": 3000, "max_output_tokens": 1536},
            }
        )

        return ops[:_MAX_OPERATIONS]

    def _derive_acceptance(
        self,
        objective: str,
        related: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
    ) -> list[str]:
        """Deriva critérios de aceitação verificáveis a partir do objetivo e requisitos."""
        criteria: list[str] = []
        for req in requirements:
            desc = req.get("description") if isinstance(req, dict) else str(req)
            if desc:
                criteria.append(f"Requisito atendido: {desc[:100]}")
        if related:
            criteria.append("Arquivos relacionados inspecionados e alterados conforme necessário")
        if any("test" in r.get("path", "").lower() for r in related):
            criteria.append("Testes relacionados aprovados")
        if not criteria:
            criteria.append(f"Objetivo concluído: {objective[:100]}")
        return criteria

    def _budget(self, _objective: str, num_ops: int, depth: int) -> ContextBudget:
        """Orçamento de contexto proporcional ao número de operações e profundidade."""
        base_input = 6000
        per_op = 1500
        depth_penalty = depth * 1000
        max_input = base_input + per_op * num_ops + depth_penalty
        return ContextBudget(
            max_input_tokens=min(max_input, 12000),
            max_output_tokens=2048,
            estimated_tokens=0,
            components=["objetivo", "arquivos_relacionados", "grafo_de_conhecimento"],
            dropped=[],
        )

    def _constraints(self, manifest: dict[str, Any], _project_info: dict[str, Any]) -> list[ExecutionConstraint]:
        """Restrições de execução derivadas do tipo de projeto."""
        constraints: list[ExecutionConstraint] = []
        # Projeto de teste: proteger arquivos de teste.
        if manifest.get("has_tests"):
            constraints.append(
                ExecutionConstraint(
                    kind="protect_tests",
                    value=True,
                    description="Arquivos de teste são critério de medição; não alterar para fazer a medição passar",
                )
            )
        constraints.append(
            ExecutionConstraint(kind="max_attempts", value=8, description="Limite de tentativas por operação")
        )
        constraints.append(
            ExecutionConstraint(kind="max_depth", value=16, description="Profundidade máxima da árvore de tarefas")
        )
        return constraints

    def _complexity(self, objective: str, affected: list[str], num_ops: int) -> dict[str, Any]:
        """Pontuação de complexidade da tarefa."""
        score = min(100, len(affected) * 10 + num_ops * 5 + len(objective) // 20)
        return {
            "score": score,
            "affected_components": len(affected),
            "operations": num_ops,
            "factors": ["componentes_afetados", "numero_de_operacoes", "tamanho_do_objetivo"],
        }

    def _allowed_files(self, related: list[dict[str, Any]]) -> list[str]:
        """Arquivos permitidos para leitura/escrita."""
        return sorted({r.get("path", "") for r in related if r.get("path")})

    def _expected_artifacts(self, affected: list[str]) -> list[ArtifactRef]:
        """Artefatos esperados da tarefa."""
        artifacts: list[ArtifactRef] = []
        artifacts.extend(
            [
                ArtifactRef(uri=f"file://{path}", kind="file", description=f"Arquivo alterado: {path}")
                for path in affected[:5]
            ]
        )
        artifacts.append(
            ArtifactRef(
                uri="artifact://verification_result", kind="test_result", description="Resultado da verificação"
            )
        )
        return artifacts


CompileResult.model_rebuild()
