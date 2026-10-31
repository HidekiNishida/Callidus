"""
Arquivo: src/agent/orchestrator/decomposition_policy.py
Nome: decomposition_policy.py
Propósito: política de decomposição recursiva adaptativa — decidir quando dividir uma tarefa e quando executar diretamente.
Responsabilidade: camada de aplicação — integra grafo de dependências, TaskIR e limites configuráveis para decidir a estratégia de decomposição.
Componentes: DecompositionLimits, DecompositionDecision, DecompositionPolicy, decide_decomposition.
Dependências: agent.engineering.dependency_graph, agent.orchestrator.task_ir, agent.domain.enums, __future__, dataclasses.
Observações: não quebra a decomposição existente em atomizer.py; camada de decisão que enriquece com dados determinísticos do projeto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent.domain.enums import TaskKind, TaskStatus
from agent.orchestrator.task_ir import TaskIR


class DecompositionDecision(StrEnum):
    """Decisão de decomposição para uma tarefa."""

    EXECUTE_DIRECTLY = "execute_directly"
    PREPARE_CONTEXT = "prepare_context"
    DECOMPOSE = "decompose"
    INVESTIGATE = "investigate"
    DIAGNOSE = "diagnose"
    REPLAN = "replan"


@dataclass
class DecompositionLimits:
    """Limites configuráveis para impedir explosão de tarefas.

    Atributos:
        max_depth: profundidade máxima da árvore de decomposição.
        max_children: quantidade máxima de filhos por tarefa.
        max_tokens_per_operation: orçamento de tokens por operação de modelo.
        max_attempts: quantidade máxima de tentativas por tarefa.
        min_work_per_subtask: quantidade mínima de trabalho para justificar uma subtarefa.
        max_total_cost: limite de custo total por execução (tokens estimados).
        complexity_threshold: pontuação acima da qual se considera decomposição.
    """

    max_depth: int = 16
    max_children: int = 8
    max_tokens_per_operation: int = 6000
    max_attempts: int = 8
    min_work_per_subtask: int = 50
    max_total_cost: int = 5_000_000
    complexity_threshold: int = 6


@dataclass
class DecompositionResult:
    """Resultado da decisão de decomposição.

    Atributos:
        decision: estratégia escolhida.
        reason: justificativa da decisão.
        subtask_specs: specs de subtarefas (quando decision == DECOMPOSE).
        context_components: componentes de contexto sugeridos (quando decision == PREPARE_CONTEXT).
        investigation_focus: área de investigação (quando decision == INVESTIGATE).
        diagnosis_hint: dica de diagnóstico (quando decision == DIAGNOSE).
        replan_scope: escopo de replanejamento (quando decision == REPLAN).
    """

    decision: DecompositionDecision
    reason: str
    subtask_specs: list[dict[str, Any]] = field(default_factory=list)
    context_components: list[str] = field(default_factory=list)
    investigation_focus: str | None = None
    diagnosis_hint: str | None = None
    replan_scope: str | None = None


class DecompositionPolicy:
    """Política de decomposição recursiva adaptativa.

    Usa o grafo de dependências, o TaskIR e métricas determinísticas para decidir
    se uma tarefa deve ser executada diretamente, ter o contexto preparado, ser
    decomposta, investigada, diagnosticada ou replanejada.
    """

    def __init__(self, limits: DecompositionLimits | None = None) -> None:
        """Inicializa a política com limites configuráveis.

        Args:
            limits: limites de decomposição (usa padrões se não informado).
        """
        self.limits = limits or DecompositionLimits()

    def decide(
        self,
        ir: TaskIR,
        *,
        graph: Any | None = None,
        attempt_count: int = 0,
        has_children: bool = False,
        depth: int = 0,
        previous_failures: list[str] | None = None,
    ) -> DecompositionResult:
        """Decide a estratégia de decomposição para uma tarefa.

        Args:
            ir: representação intermediária da tarefa.
            graph: grafo de dependências do projeto (opcional).
            attempt_count: número de tentativas já feitas.
            has_children: se a tarefa já tem subtarefas.
            depth: profundidade atual na árvore.
            previous_failures: lista de falhas anteriores (mensagens).

        Returns:
            A decisão de decomposição com justificativa e specs de subtarefas quando aplicável.
        """
        # 1. Limite de profundidade atingido
        if depth >= self.limits.max_depth:
            return DecompositionResult(
                decision=DecompositionDecision.EXECUTE_DIRECTLY,
                reason=f"profundidade máxima ({self.limits.max_depth}) atingida",
            )

        # 2. Já tem filhos — não dividir de novo
        if has_children:
            return DecompositionResult(
                decision=DecompositionDecision.EXECUTE_DIRECTLY,
                reason="tarefa já possui subtarefas",
            )

        # 3. Tarefa atômica marcada — não dividir
        if ir.context_budget and ir.context_budget.estimated_tokens > self.limits.max_tokens_per_operation:
            return DecompositionResult(
                decision=DecompositionDecision.PREPARE_CONTEXT,
                reason=f"contexto excede orçamento ({ir.context_budget.estimated_tokens} > {self.limits.max_tokens_per_operation})",
                context_components=[a.uri for a in ir.inputs + ir.expected_artifacts],
            )

        # 4. Muitas tentativas — investigar ou diagnosticar
        if attempt_count >= self.limits.max_attempts:
            if previous_failures:
                return DecompositionResult(
                    decision=DecompositionDecision.DIAGNOSE,
                    reason=f"muitas tentativas ({attempt_count}) sem progresso",
                    diagnosis_hint="; ".join(previous_failures[:3]),
                )
            return DecompositionResult(
                decision=DecompositionDecision.INVESTIGATE,
                reason=f"muitas tentativas ({attempt_count}) sem falhas registradas",
                investigation_focus=ir.objective,
            )

        # 5. Calcular complexidade com dados do grafo
        score = self._complexity_score(ir, graph=graph, attempt_count=attempt_count)

        # 6. Complexidade baixa — executar diretamente
        if score < self.limits.complexity_threshold:
            return DecompositionResult(
                decision=DecompositionDecision.EXECUTE_DIRECTLY,
                reason=f"complexidade baixa (score={score} < {self.limits.complexity_threshold})",
            )

        # 7. Complexidade alta — decompor
        if ir.affected_components or ir.allowed_files:
            subtask_specs = self._generate_subtasks(ir, graph=graph)
        else:
            subtask_specs = []

        return DecompositionResult(
            decision=DecompositionDecision.DECOMPOSE,
            reason=f"complexidade alta (score={score} >= {self.limits.complexity_threshold})",
            subtask_specs=subtask_specs,
        )

    def _complexity_score(
        self,
        ir: TaskIR,
        *,
        graph: Any | None = None,
        attempt_count: int = 0,
    ) -> int:
        """Calcula pontuação de complexidade usando dados determinísticos do projeto.

        Args:
            ir: representação intermediária da tarefa.
            graph: grafo de dependências (opcional).
            attempt_count: número de tentativas já feitas.

        Returns:
            Pontuação de complexidade (0-100).
        """
        score = 0

        # Tamanho do objetivo
        score += min(len(ir.objective) // 40, 10)

        # Número de requisitos
        score += min(len(ir.requirements) * 2, 10)

        # Número de critérios de aceitação
        score += min(len(ir.acceptance_criteria) * 2, 10)

        # Número de arquivos afetados
        score += min(len(ir.affected_components) * 3, 15)

        # Número de arquivos permitidos
        score += min(len(ir.allowed_files) * 2, 10)

        # Número de ferramentas autorizadas
        score += min(len(ir.allowed_tools) * 1, 5)

        # Dependências
        score += min(len(ir.dependencies) * 2, 10)

        # Número de artefatos esperados
        score += min(len(ir.expected_artifacts) * 2, 10)

        # Impacto via grafo de dependências
        if graph and ir.allowed_files:
            try:
                dependents = 0
                for f in ir.allowed_files:
                    file_id = graph.get_file_node_id(f)
                    if graph._graph and graph._graph.has_node(file_id):
                        deps = graph.get_dependents(file_id, max_depth=3)
                        dependents += len(deps)
                score += min(dependents, 15)
            except Exception:
                pass

        # Tentativas anteriores
        score += min(attempt_count * 2, 10)

        # Tipo de tarefa
        if ir.status == TaskStatus.BLOCKED.value:
            score += 5

        return min(score, 100)

    def _generate_subtasks(
        self,
        ir: TaskIR,
        *,
        graph: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Gera specs de subtarefas com base no objetivo e nos componentes afetados.

        Args:
            ir: representação intermediária da tarefa.
            graph: grafo de dependências (opcional).

        Returns:
            Lista de specs de subtarefas.
        """
        specs: list[dict[str, Any]] = []

        # Estratégia padrão: entender → implementar → verificar
        specs.append(
            {
                "title": "Inspecionar contexto",
                "objective": f"Buscar referências e símbolos relacionados: {ir.objective[:120]}",
                "metadata": {"tool": "search_grep", "tool_args": {"pattern": "def "}, "atomic": True},
            }
        )

        specs.append(
            {
                "title": "Executar alteração",
                "objective": ir.objective,
                "metadata": {"model_operation": True, "atomic": True},
                "depends_on_indices": [0],
            }
        )

        specs.append(
            {
                "title": "Verificar alteração",
                "objective": "Rodar verificação determinística",
                "metadata": {"verification": {"type": "stages"}, "atomic": True},
                "depends_on_indices": [1],
            }
        )

        # Se há múltiplos arquivos afetados, criar uma subtarefa por arquivo
        if len(ir.allowed_files) > 1:
            file_specs = []
            for f in ir.allowed_files[: self.limits.max_children - 3]:
                file_specs.append(
                    {
                        "title": f"Alterar {f}",
                        "objective": f"Aplicar mudanças em {f}: {ir.objective[:100]}",
                        "metadata": {"model_operation": True, "atomic": True, "target_file": f},
                    }
                )
            specs = specs[:1] + file_specs + specs[1:]

        return specs[: self.limits.max_children]


def decide_decomposition(
    ir: TaskIR,
    *,
    graph: Any | None = None,
    limits: DecompositionLimits | None = None,
    attempt_count: int = 0,
    has_children: bool = False,
    depth: int = 0,
    previous_failures: list[str] | None = None,
) -> DecompositionResult:
    """Função de conveniência para decidir a decomposição de uma tarefa.

    Args:
        ir: representação intermediária da tarefa.
        graph: grafo de dependências do projeto (opcional).
        limits: limites de decomposição (usa padrões se não informado).
        attempt_count: número de tentativas já feitas.
        has_children: se a tarefa já tem subtarefas.
        depth: profundidade atual na árvore.
        previous_failures: lista de falhas anteriores.

    Returns:
        O resultado da decisão de decomposição.
    """
    policy = DecompositionPolicy(limits=limits)
    return policy.decide(
        ir=ir,
        graph=graph,
        attempt_count=attempt_count,
        has_children=has_children,
        depth=depth,
        previous_failures=previous_failures,
    )
