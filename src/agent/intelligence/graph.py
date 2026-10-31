"""
Arquivo: src/agent/intelligence/graph.py
Nome: graph.py
Propósito: grafo cognitivo dinâmico que representa a arquitetura percorrida pelo agente durante a execução.
Responsabilidade: camada de aplicação — topologia de componentes, estados visuais, eventos de transição, histórico de execução.
Componentes: CognitiveGraphNode, CognitiveGraphEdge, CognitiveGraph.
Dependências: agent.intelligence.telemetry (TelemetryEvent), agent.persistence.models, uuid, datetime, collections.
Observações: este grafo representa o fluxo de execução real, não o KnowledgeGraphService (símbolos/arquivos do código).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel
from sqlalchemy import select
from sqlalchemy.orm import Session

GRAPH_SCHEMA_VERSION = 1

# Topologia extraída da arquitetura real do Callidus. Cada nó é um componente do sistema.
ARCHITECTURE_NODES: dict[str, dict[str, Any]] = {
    "user_request": {"name": "Requisição do Usuário", "type": "source", "category": "entrada"},
    "api": {"name": "API FastAPI", "type": "transport", "category": "transporte"},
    "task_manager": {"name": "Task Manager", "type": "manager", "category": "orquestração"},
    "run_manager": {"name": "Run Manager", "type": "manager", "category": "orquestração"},
    "orchestrator": {"name": "Orchestrator", "type": "core", "category": "orquestração"},
    "planner": {"name": "Planner", "type": "component", "category": "planejamento"},
    "decomposition": {"name": "Decomposition", "type": "component", "category": "planejamento"},
    "atomizer": {"name": "Atomizer", "type": "component", "category": "planejamento"},
    "context_assembly": {"name": "Context Assembly", "type": "component", "category": "contexto"},
    "context_budget": {"name": "Context Budget", "type": "component", "category": "contexto"},
    "memory": {"name": "Memory", "type": "component", "category": "memória"},
    "knowledge": {"name": "Knowledge Graph", "type": "component", "category": "conhecimento"},
    "skills": {"name": "Skills", "type": "component", "category": "habilidades"},
    "provider": {"name": "Provider (LLM)", "type": "provider", "category": "inferência"},
    "tool_registry": {"name": "Tool Registry", "type": "component", "category": "ferramentas"},
    "tool_execution": {"name": "Tool Execution", "type": "component", "category": "ferramentas"},
    "verification": {"name": "Verification", "type": "component", "category": "verificação"},
    "recovery": {"name": "Recovery", "type": "component", "category": "recuperação"},
    "replanning": {"name": "Replanning", "type": "component", "category": "planejamento"},
    "consolidation": {"name": "Consolidation", "type": "component", "category": "consolidação"},
    "global_verify": {"name": "Global Verify", "type": "component", "category": "verificação"},
    "closing": {"name": "Closing", "type": "component", "category": "consolidação"},
    "persistence": {"name": "Persistence (SQLite)", "type": "store", "category": "persistência"},
}

# Arestas que representam fluxos possíveis entre componentes (não linear, suporta retornos e ramificações).
ARCHITECTURE_EDGES: dict[str, list[str]] = {
    "user_request": ["api"],
    "api": ["task_manager", "run_manager"],
    "task_manager": ["orchestrator"],
    "run_manager": ["orchestrator"],
    "orchestrator": ["planner", "decomposition", "context_assembly", "provider", "tool_execution", "verification", "replanning", "consolidation", "global_verify", "closing"],
    "planner": ["decomposition", "orchestrator"],
    "decomposition": ["atomizer", "orchestrator"],
    "atomizer": ["context_assembly", "orchestrator"],
    "context_assembly": ["context_budget", "provider", "orchestrator"],
    "context_budget": ["provider", "orchestrator"],
    "memory": ["context_assembly", "orchestrator"],
    "knowledge": ["context_assembly", "orchestrator"],
    "skills": ["context_assembly", "orchestrator"],
    "provider": ["orchestrator"],
    "tool_registry": ["tool_execution", "orchestrator"],
    "tool_execution": ["verification", "orchestrator"],
    "verification": ["recovery", "replanning", "consolidation", "orchestrator"],
    "recovery": ["replanning", "verification", "orchestrator"],
    "replanning": ["planner", "decomposition", "orchestrator"],
    "consolidation": ["global_verify", "closing", "orchestrator"],
    "global_verify": ["closing", "replanning", "orchestrator"],
    "closing": ["persistence", "orchestrator"],
    "persistence": ["orchestrator"],
}

NODE_STATES = {
    "idle": "idle",
    "pending": "pending",
    "active": "active",
    "completed": "completed",
    "failed": "failed",
    "retrying": "retrying",
    "blocked": "blocked",
    "skipped": "skipped",
    "paused": "paused",
}


@dataclass
class CognitiveGraphNode:
    """Nó do grafo cognitivo com estado e métricas.

    Atributos:
        id: identificador estável do componente.
        name: nome legível.
        type: tipo do componente (source, transport, manager, core, component, provider, store).
        category: categoria (entrada, transporte, orquestração, planejamento, contexto, memória, conhecimento, habilidades, inferência, ferramentas, verificação, recuperação, consolidação, persistência).
        state: estado atual (idle, pending, active, completed, failed, retrying, blocked, skipped, paused).
        activations: quantidade de vezes que o nó foi ativado.
        total_duration_ms: tempo acumulado de execução.
        error_count: quantidade de erros registrados.
        last_event_at: timestamp do último evento associado.
        metadata: metadados adicionais (tokens, tentativas, etc.).
    """

    id: str
    name: str
    type: str
    category: str
    state: str = "idle"
    activations: int = 0
    total_duration_ms: int = 0
    error_count: int = 0
    last_event_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "category": self.category,
            "state": self.state,
            "activations": self.activations,
            "total_duration_ms": self.total_duration_ms,
            "error_count": self.error_count,
            "last_event_at": self.last_event_at,
            "metadata": self.metadata,
        }


@dataclass
class CognitiveGraphEdge:
    """Aresta do grafo cognitivo com estado de percurso.

    Atributos:
        source: identificador do nó de origem.
        target: identificador do nó de destino.
        traversed: se a conexão já foi percorrida.
        traversal_count: quantidade de vezes percorrida.
        last_traversed_at: timestamp da última travessia.
        failure_count: quantidade de falhas nesta conexão.
    """

    source: str
    target: str
    traversed: bool = False
    traversal_count: int = 0
    last_traversed_at: str | None = None
    failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "traversed": self.traversed,
            "traversal_count": self.traversal_count,
            "last_traversed_at": self.last_traversed_at,
            "failure_count": self.failure_count,
        }


class CognitiveGraph:
    """Grafo cognitivo dinâmico.

    Atributos:
        session: sessão SQLAlchemy para leitura de eventos e tarefas.
        run_id: identificador da run sendo representada (opcional; se ausente, usa o estado geral).
        nodes: nós do grafo indexados por id.
        edges: arestas do grafo indexadas por (source, target).
        event_history: histórico de eventos que alteraram o grafo.
    """

    def __init__(self, session: Session, run_id: uuid.UUID | None = None) -> None:
        """Cria o grafo a partir da arquitetura e do estado persistido.

        Args:
            session: sessão SQLAlchemy.
            run_id: run específica; quando ausente, o grafo reflete o estado geral dos componentes.
        """
        self._session = session
        self.run_id = run_id
        self.nodes: dict[str, CognitiveGraphNode] = {}
        self.edges: dict[tuple[str, str], CognitiveGraphEdge] = {}
        self.event_history: list[dict[str, Any]] = []
        self._last_active_node: str | None = None
        self._build_topology()
        self._load_state()

    def _build_topology(self) -> None:
        """Constrói nós e arestas a partir da topologia da arquitetura real."""
        for node_id, info in ARCHITECTURE_NODES.items():
            self.nodes[node_id] = CognitiveGraphNode(
                id=node_id,
                name=info["name"],
                type=info["type"],
                category=info["category"],
            )
        for source, targets in ARCHITECTURE_EDGES.items():
            for target in targets:
                key = (source, target)
                self.edges[key] = CognitiveGraphEdge(source=source, target=target)

    def _load_state(self) -> None:
        """Carrega o estado dos nós a partir dos eventos persistidos da run."""
        if self.run_id is None:
            return
        stmt = select(EventLogModel).where(EventLogModel.run_id == self.run_id).order_by(EventLogModel.seq)
        for ev in self._session.scalars(stmt).all():
            self._apply_event(ev.event_type, ev.payload_json or {}, ev.created_at, str(ev.seq))

    def _apply_event(self, event_type: str, data: dict[str, Any], occurred_at: Any, seq: str) -> None:
        """Aplica um evento ao estado do grafo: atualiza nó, aresta e métricas."""
        timestamp = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at)
        self.event_history.append(
            {"seq": int(seq) if seq.isdigit() else 0, "type": event_type, "data": data, "at": timestamp}
        )

        # Mapeia tipos de evento para nós e ações no grafo.
        node_id = self._event_to_node(event_type, data)
        if node_id is None:
            return
        node = self.nodes.get(node_id)
        if node is None:
            return

        node.last_event_at = timestamp
        if event_type.endswith(".started"):
            node.state = "active"
            node.activations += 1
            # Marca a aresta do nó ativo anterior para este nó, indicando o fluxo de execução.
            if self._last_active_node is not None and self._last_active_node != node_id:
                self._mark_edge_traversed(self._last_active_node, node_id, timestamp)
            self._last_active_node = node_id
        elif event_type.endswith(".completed"):
            node.state = "completed"
            duration = data.get("duration_ms")
            if isinstance(duration, int):
                node.total_duration_ms += duration
        elif event_type.endswith(".failed"):
            node.state = "failed"
            node.error_count += 1
        elif event_type.endswith(".retrying"):
            node.state = "retrying"
        elif event_type.endswith(".blocked"):
            node.state = "blocked"
        elif event_type.endswith(".paused"):
            node.state = "paused"
        elif event_type == "task.state.transitioned":
            to = data.get("to")
            if to == "RUNNING":
                node.state = "active"
            elif to == "COMPLETED":
                node.state = "completed"
            elif to == "FAILED":
                node.state = "failed"
                node.error_count += 1
            elif to == "BLOCKED":
                node.state = "blocked"
            elif to == "READY":
                node.state = "pending"
            elif to == "PLANNING":
                node.state = "pending"

    def _event_to_node(self, event_type: str, data: dict[str, Any]) -> str | None:
        """Mapeia um tipo de evento para o nó do grafo correspondente."""
        mapping = {
            "agent.started": "provider",
            "agent.output.completed": "provider",
            "agent.output.failed": "provider",
            "provider.inference.started": "provider",
            "provider.inference.completed": "provider",
            "provider.inference.failed": "provider",
            "tool.started": "tool_execution",
            "tool.completed": "tool_execution",
            "tool.failed": "tool_execution",
            "command.started": "tool_execution",
            "command.completed": "tool_execution",
            "command.failed": "tool_execution",
            "test.started": "tool_execution",
            "test.completed": "tool_execution",
            "test.failed": "tool_execution",
            "verification.started": "verification",
            "verification.passed": "verification",
            "verification.failed": "verification",
            "plan.started": "planner",
            "plan.updated": "decomposition",
            "decomposition.recursive": "decomposition",
            "context.compacted": "context_assembly",
            "budget.pressure": "context_budget",
            "memory.recovered": "memory",
            "skill.selected": "skills",
            "orchestrator.step.started": "orchestrator",
            "orchestrator.step.completed": "orchestrator",
            "task.state.transitioned": "task_manager",
            "run.started": "run_manager",
            "run.completed": "closing",
            "run.failed": "closing",
            "run.paused": "closing",
            "run.resumed": "run_manager",
            "strategy.formulated": "planner",
            "run.stagnation": "replanning",
            "verification.recovery_planned": "recovery",
            "verification.attempt.started": "verification",
            "verification.attempt.completed": "verification",
            "resources.sampled": "persistence",
            "file.changed": "persistence",
            "file.created": "persistence",
        }
        return mapping.get(event_type)

    def _mark_edge_traversed(self, source: str, target: str, timestamp: str) -> None:
        """Marca uma aresta como percorrida."""
        for (s, t), edge in self.edges.items():
            if s == source and t == target:
                edge.traversed = True
                edge.traversal_count += 1
                edge.last_traversed_at = timestamp
                break

    def to_dict(self) -> dict[str, Any]:
        """Exporta o grafo como dicionário para a API."""
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "run_id": str(self.run_id) if self.run_id else None,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "event_history": self.event_history[-200:],
        }

    def get_node(self, node_id: str) -> CognitiveGraphNode | None:
        """Devolve um nó pelo identificador."""
        return self.nodes.get(node_id)

    def get_edges_for_node(self, node_id: str) -> list[CognitiveGraphEdge]:
        """Devolve as arestas de saída de um nó."""
        return [e for (s, _), e in self.edges.items() if s == node_id]

    def get_active_nodes(self) -> list[CognitiveGraphNode]:
        """Devolve os nós no estado ativo."""
        return [n for n in self.nodes.values() if n.state == "active"]

    def get_failed_nodes(self) -> list[CognitiveGraphNode]:
        """Devolve os nós com falha."""
        return [n for n in self.nodes.values() if n.state == "failed"]

    def get_blocked_nodes(self) -> list[CognitiveGraphNode]:
        """Devolve os nós bloqueados."""
        return [n for n in self.nodes.values() if n.state == "blocked"]
