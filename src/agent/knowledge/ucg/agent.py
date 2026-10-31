"""
Arquivo: src/agent/knowledge/ucg/agent.py
Nome: agent.py
Propósito: Agent Graph — perfis de agente, seleção adaptativa por competência e handoff
estruturado com contexto mínimo, sem criar agentes para trabalho determinístico.
Responsabilidade: camada de aplicação — expõe os agentes existentes (`AgentModel`) como
nós do UCG com perfis de competência, seleção baseada em cobertura de requisitos, custo,
disponibilidade e confiabilidade, e construção de pacotes de contexto mínimo para handoff.
Componentes: AgentProfile, AgentSelection, AgentHandoff, AgentGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.persistence.models,
dataclasses, datetime, typing, uuid.
Observações: não grava dados de negócio; lê de `agents`, `agent_executions` e
`agent_queries`. A seleção nunca cria agentes para trabalho que código determinístico
resolva, e não paraleliza chamadas a modelos apenas porque tarefas são independentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.knowledge.ucg.graph import UnifiedGraphService
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphEdgeRef,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
)
from agent.persistence.models import AgentExecutionModel, AgentModel, AgentQueryModel

#: Custo relativo padrão de um agente (baixo, medio, alto).
_DEFAULT_COST = "medio"

#: Confiança mínima para considerar um agente disponível.
_MIN_AVAILABILITY_CONFIDENCE = 0.5


@dataclass
class AgentProfile:
    """Perfil de agente: capacidades, limitações e custos para seleção adaptativa.

    Atributos:
        agent_id: identificador do agente.
        role: papel do agente (`worker`, `reviewer`, `specialist`, `coordinator`, ...).
        competencies: competências declaradas (lista de strings).
        limitations: limitações conhecidas.
        compatible_models: modelos compatíveis com o agente.
        recommended_context: orçamento de contexto recomendado (tokens).
        allowed_tools: ferramentas que o agente pode usar.
        execution_requirements: requisitos de execução (memória, tempo, concorrência).
        estimated_cost: custo relativo (`baixo`, `medio`, `alto`).
        availability: disponibilidade atual (0 a 1).
        reliability: confiabilidade histórica (0 a 1).
        suitable_task_kinds: tipos de tarefa aos quais o agente se aplica.
        project_id: projeto de escopo.
        parent_id: agente-pai, quando houver.
        depth: profundidade na hierarquia de agentes.
        status: status atual (`idle`, `busy`, `offline`, `blocked`).
        metadata: metadados livres.
    """

    agent_id: str
    role: str
    competencies: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    compatible_models: list[str] = field(default_factory=list)
    recommended_context: int = 6000
    allowed_tools: list[str] = field(default_factory=list)
    execution_requirements: dict[str, Any] = field(default_factory=dict)
    estimated_cost: str = _DEFAULT_COST
    availability: float = 1.0
    reliability: float = 1.0
    suitable_task_kinds: list[str] = field(default_factory=list)
    project_id: str | None = None
    parent_id: str | None = None
    depth: int = 0
    status: str = "idle"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte o perfil para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.agent_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.AGENT,
            kind=GraphNodeKind.AGENT,
            source_system="agent",
            source_id=self.agent_id,
            project_id=self.project_id,
            scope=GraphScope.AGENT,
            version=1,
            status=GraphStatus.ACTIVE if self.status == "idle" else GraphStatus.BLOCKED,
            metadata={
                "role": self.role,
                "competencies": self.competencies,
                "limitations": self.limitations,
                "compatible_models": self.compatible_models,
                "recommended_context": self.recommended_context,
                "allowed_tools": self.allowed_tools,
                "estimated_cost": self.estimated_cost,
                "availability": self.availability,
                "reliability": self.reliability,
                "suitable_task_kinds": self.suitable_task_kinds,
                "status": self.status,
                **self.metadata,
            },
        )

    @property
    def is_available(self) -> bool:
        """Diz se o agente está disponível (idle e com confiança suficiente)."""
        return self.status == "idle" and self.availability >= _MIN_AVAILABILITY_CONFIDENCE


@dataclass
class AgentSelection:
    """Resultado da seleção de agente para uma tarefa.

    Atributos:
        agent: perfil do agente selecionado.
        score: pontuação de seleção (0 a 100).
        reasons: motivos que explicam a escolha.
        coverage: requisitos cobertos pelas competências do agente.
        gaps: requisitos não cobertos (lacunas de competência).
        cost_estimate: estimativa de custo da execução.
        context_estimate: estimativa de contexto necessário.
    """

    agent: AgentProfile
    score: float
    reasons: list[str] = field(default_factory=list)
    coverage: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    cost_estimate: str = _DEFAULT_COST
    context_estimate: int = 0


@dataclass
class AgentHandoff:
    """Pacote de contexto mínimo para handoff entre agente e orquestrador.

    Atributos:
        agent_id: identificador do agente destinatário.
        task_id: identificador da tarefa.
        objective: objetivo da tarefa.
        scope: escopo de isolamento (projeto, tarefa, execução).
        essential_information: informações essenciais para o agente.
        files_and_references: arquivos e referências relevantes.
        relevant_memories: memórias pertinentes (resumidas).
        available_capabilities: capacidades disponíveis para o agente.
        preconditions: pré-condições que devem ser satisfeitas.
        expected_output: resultado esperado.
        acceptance_criteria: critérios de aceite.
        budget: orçamento (tentativas, tokens, tempo).
    """

    agent_id: str
    task_id: str
    objective: str
    scope: str = "task"
    essential_information: list[str] = field(default_factory=list)
    files_and_references: list[str] = field(default_factory=list)
    relevant_memories: list[dict[str, Any]] = field(default_factory=list)
    available_capabilities: list[dict[str, Any]] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    expected_output: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o handoff para dicionário."""
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "objective": self.objective,
            "scope": self.scope,
            "essential_information": self.essential_information,
            "files_and_references": self.files_and_references,
            "relevant_memories": self.relevant_memories,
            "available_capabilities": self.available_capabilities,
            "preconditions": self.preconditions,
            "expected_output": self.expected_output,
            "acceptance_criteria": self.acceptance_criteria,
            "budget": self.budget,
        }


class AgentGraphService:
    """Serviço do Agent Graph integrado ao UCG.

    Expõe os agentes existentes como nós do UCG com perfis de competência, seleção
    baseada em cobertura de requisitos, custo, disponibilidade e confiabilidade, e
    construção de pacotes de contexto mínimo para handoff.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _project: modelo do projeto.
        _graph: serviço de leitura do grafo unificado.
    """

    def __init__(self, session: Any, project: Any) -> None:
        """Cria o serviço ligado a um projeto.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
            project: modelo do projeto.
        """
        self._session = session
        self._project = project
        self._graph = UnifiedGraphService(session)

    def discover_agents(
        self,
        *,
        required_competencies: list[str] | None,
        suitable_task_kinds: list[str] | None,
        limit: int = 10,
    ) -> list[AgentProfile]:
        """Descobre agentes disponíveis para um conjunto de competências.

        Args:
            required_competencies: competências necessárias para a tarefa.
            suitable_task_kinds: tipos de tarefa aos quais o agente deve se aplicar.
            limit: quantidade máxima devolvida.

        Returns:
            Lista de `AgentProfile` ordenada por adequação.
        """
        from sqlalchemy import select

        rows = list(
            self._session.scalars(
                select(AgentModel).where(AgentModel.project_id == self._project.id)
            ).all()
        )

        profiles: list[AgentProfile] = []
        for row in rows:
            meta = row.metadata_json or {}
            profiles.append(
                AgentProfile(
                    agent_id=str(row.id),
                    role=row.role,
                    competencies=list(meta.get("competencies", []) or []),
                    limitations=list(meta.get("limitations", []) or []),
                    compatible_models=list(meta.get("compatible_models", []) or []),
                    recommended_context=int(meta.get("recommended_context", 6000)),
                    allowed_tools=list(
                        row.permissions_json or [] if isinstance(row.permissions_json, list) else []
                    ),
                    execution_requirements=meta.get("execution_requirements", {}) or {},
                    estimated_cost=meta.get("estimated_cost", _DEFAULT_COST),
                    availability=float(meta.get("availability", 1.0)),
                    reliability=float(meta.get("reliability", 1.0)),
                    suitable_task_kinds=list(
                        meta.get("suitable_task_kinds", []) or []
                    ),
                    project_id=str(row.project_id),
                    parent_id=str(row.parent_id) if row.parent_id else None,
                    depth=int(row.depth or 0),
                    status=row.status,
                    metadata=meta,
                )
            )

        # Filtra por disponibilidade.
        available = [p for p in profiles if p.is_available]

        # Pontua por cobertura de competências e tipos de tarefa.
        req_set = set(required_competencies or [])
        kind_set = set(suitable_task_kinds or [])
        scored: list[tuple[float, AgentProfile]] = []
        for profile in available:
            score = 0.0
            reasons: list[str] = []
            coverage: list[str] = []
            if req_set:
                covered = req_set & set(profile.competencies)
                coverage.extend(covered)
                score += len(covered) * 10
                if covered:
                    reasons.append(f"competências: {', '.join(sorted(covered))}")
            if kind_set:
                covered_kinds = kind_set & set(profile.suitable_task_kinds)
                if covered_kinds:
                    score += len(covered_kinds) * 5
                    reasons.append(f"tipos de tarefa: {', '.join(sorted(covered_kinds))}")
            score += profile.reliability * 20
            score += profile.availability * 10
            # Custo menor = melhor.
            cost_weight = {"baixo": 5, "medio": 3, "alto": 1}.get(profile.estimated_cost, 3)
            score += cost_weight
            scored.append((score, profile))

        scored.sort(key=lambda item: (-item[0], item[1].agent_id))
        return [profile for _, profile in scored[:limit]]

    def select_agent(
        self,
        *,
        required_competencies: list[str] | None,
        suitable_task_kinds: list[str] | None,
        objective: str = "",
        limit: int = 10,
    ) -> AgentSelection | None:
        """Seleciona o melhor agente para uma tarefa.

        Args:
            required_competencies: competências necessárias.
            suitable_task_kinds: tipos de tarefa adequados.
            objective: objetivo da tarefa (para pontuação de relevância).
            limit: quantidade máxima de candidatos considerados.

        Returns:
            O `AgentSelection` com o melhor agente, ou None quando não há agente adequado.
        """
        candidates = self.discover_agents(
            required_competencies=required_competencies,
            suitable_task_kinds=suitable_task_kinds,
            limit=limit,
        )
        if not candidates:
            return None

        best = candidates[0]
        req_set = set(required_competencies or [])
        covered = req_set & set(best.competencies)
        gaps = list(req_set - set(best.competencies))

        reasons = list(
            {
                f"Selecionado por melhor cobertura de competências ({len(covered)}/{max(1, len(req_set))})",
                f"Confiabilidade: {best.reliability:.2f}, disponibilidade: {best.availability:.2f}",
                f"Custo estimado: {best.estimated_cost}",
            }
        )

        return AgentSelection(
            agent=best,
            score=100.0 - len(gaps) * 20,
            reasons=reasons,
            coverage=list(covered),
            gaps=gaps,
            cost_estimate=best.estimated_cost,
            context_estimate=best.recommended_context,
        )

    def build_handoff(
        self,
        *,
        agent_id: str,
        task_id: str,
        objective: str,
        essential_information: list[str] | None,
        files_and_references: list[str] | None,
        preconditions: list[str] | None,
        expected_output: str = "",
        acceptance_criteria: list[str] | None,
        budget: dict[str, Any] | None,
        relevant_memories: list[dict[str, Any]] | None,
        available_capabilities: list[dict[str, Any]] | None,
    ) -> AgentHandoff:
        """Constrói um pacote de contexto mínimo para handoff ao agente.

        O handoff contém apenas o necessário para o agente executar, sem expor o
        grafo inteiro nem histórico desnecessário.

        Args:
            agent_id: identificador do agente destinatário.
            task_id: identificador da tarefa.
            objective: objetivo da tarefa.
            essential_information: informações essenciais.
            files_and_references: arquivos e referências relevantes.
            preconditions: pré-condições a satisfazer.
            expected_output: resultado esperado.
            acceptance_criteria: critérios de aceite.
            budget: orçamento de execução.
            relevant_memories: memórias pertinentes (já resumidas).
            available_capabilities: capacidades disponíveis.

        Returns:
            O `AgentHandoff` montado.
        """
        return AgentHandoff(
            agent_id=agent_id,
            task_id=task_id,
            objective=objective,
            essential_information=list(essential_information or []),
            files_and_references=list(files_and_references or []),
            relevant_memories=list(relevant_memories or []),
            available_capabilities=list(available_capabilities or []),
            preconditions=list(preconditions or []),
            expected_output=expected_output,
            acceptance_criteria=list(acceptance_criteria or []),
            budget=dict(budget or {}),
        )

    def agent_to_graph_node(self, profile: AgentProfile) -> GraphNodeRef:
        """Converte um `AgentProfile` para `GraphNodeRef` do UCG."""
        return profile.to_graph_node_ref()

    def relate_agent_to_task(
        self, profile: AgentProfile, task_id: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `EXECUTED_BY` entre uma tarefa e um agente.

        A tarefa (origem) é executada pelo agente (destino).
        """
        source = GraphNodeRef(
            id=hash(task_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.TASK,
            kind=GraphNodeKind.TASK,
            source_system="task",
            source_id=task_id,
            project_id=profile.project_id,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        target = profile.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.EXECUTED_BY, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.EXECUTED_BY,
            metadata={"agent_id": profile.agent_id, "task_id": task_id},
        )


__all__ = [
    "AgentProfile",
    "AgentSelection",
    "AgentHandoff",
    "AgentGraphService",
]
