"""
Arquivo: src/agent/knowledge/ucg/graph.py
Nome: graph.py
Propósito: provedor do Unified Cognitive Graph sobre as tabelas existentes — resolução de nós, consulta de relacionamentos, validação de tipos, controle de escopo, proveniência e travessia limitada.
Responsabilidade: camada de aplicação — expõe um repositório de grafos pequeno para que módulos consultem relações sem conhecer a implementação interna dos demais domínios.
Componentes: GraphRepository (protocolo), UnifiedGraphService.
Dependências: agent.knowledge.ucg.model, agent.persistence.models, sqlalchemy, uuid, typing.
Observações: não cria novas tabelas; lê de KgNodeModel, KgEdgeModel, TaskModel, TaskDependencyModel, MemoryRecordModel, EvidenceModel e AgentModel. Os módulos originais continuam responsáveis por criar, atualizar e remover seus próprios dados. Arestas entre domínios que ainda não estão em kg_edges retornam travessia vazia sem falhar.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphEdgeRef,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
    InvalidRelationshipError,
    NodeNotFoundError,
    relation_rule,
    to_relation_kind,
)

#: Tipos de nó que existem como linhas em kg_nodes.
_KG_NODE_KINDS: frozenset[GraphNodeKind] = frozenset(
    {
        GraphNodeKind.FILE,
        GraphNodeKind.SYMBOL,
        GraphNodeKind.DOCUMENT,
        GraphNodeKind.CONCEPT,
        GraphNodeKind.FUNCTION,
        GraphNodeKind.CLASS,
    }
)

#: Resolvedor de nó por (domínio, tipo). Expandido de forma controlada.
NodeResolver = Callable[[Session, GraphNodeRef], GraphNodeRef | None]
_NODE_RESOLVERS: dict[tuple[GraphDomain, GraphNodeKind], NodeResolver] = {}


def _register_resolver(domain: GraphDomain, kind: GraphNodeKind) -> Callable[[NodeResolver], NodeResolver]:
    def decorator(func: NodeResolver) -> NodeResolver:
        _NODE_RESOLVERS[(domain, kind)] = func
        return func

    return decorator


# -- repositório -----------------------------------------------------------


class GraphRepository:
    """Contrato de leitura do grafo unificado.

    Implementações resolvem referências de nós, consultam relacionamentos,
    validam tipos, controlam escopos e provedor de proveniência, sem gravar
    dados de negócio — cada domínio permanece dono de suas próprias gravações.
    """

    def get_node(self, node_ref: GraphNodeRef) -> GraphNodeRef | None:
        """Resolve uma referência de nó para sua representação no banco.

        Args:
            node_ref: referência do nó a resolver.

        Returns:
            O `GraphNodeRef` resolvido com metadados de proveniência, ou `None`
            quando o nó não existe.
        """
        raise NotImplementedError

    def get_neighbors(
        self,
        node_ref: GraphNodeRef,
        *,
        relation_types: list[GraphRelationKind] | None = None,
        direction: GraphDirection = GraphDirection.OUTGOING,
        limit: int = 50,
    ) -> list[tuple[GraphEdgeRef, GraphNodeRef]]:
        """Devolve os vizinhos de um nó, filtrados por tipo de relacionamento e direção.

        Args:
            node_ref: nó de partida.
            relation_types: tipos de relacionamento permitidos (todos quando None).
            direction: direção da travessia.
            limit: quantidade máxima de vizinhos.

        Returns:
            Lista de pares (aresta, nó destino), respeitando o limite.
        """
        raise NotImplementedError

    def get_edges(
        self,
        node_ref: GraphNodeRef,
        *,
        direction: GraphDirection = GraphDirection.OUTGOING,
        relation_types: list[GraphRelationKind] | None = None,
        limit: int = 50,
    ) -> list[GraphEdgeRef]:
        """Devolve as arestas incidentes a um nó.

        Args:
            node_ref: nó de referência.
            direction: direção das arestas.
            relation_types: tipos de relacionamento permitidos.
            limit: quantidade máxima de arestas.

        Returns:
            Lista de arestas incidentes.
        """
        raise NotImplementedError

    def validate_relationship(
        self,
        source: GraphNodeRef,
        relation: GraphRelationKind,
        target: GraphNodeRef,
    ) -> bool:
        """Valida se o relacionamento é permitido entre os tipos de origem e destino.

        Args:
            source: nó de origem.
            relation: tipo do relacionamento.
            target: nó de destino.

        Returns:
            `True` quando a regra de relacionamento permite a aresta.
        """
        raise NotImplementedError


class UnifiedGraphService(GraphRepository):
    """Implementação do repositório do UCG sobre as tabelas existentes.

    Resolve nós de conhecimento (`kg_nodes`), memória (`memory_records`),
    tarefas (`tasks`) e evidências (`evidences`). Travessia de arestas usa
    `kg_edges` para nós de conhecimento e `task_dependencies` para dependências
    de tarefas.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
        """
        self._session = session

    def get_node(self, node_ref: GraphNodeRef) -> GraphNodeRef | None:
        resolver = _NODE_RESOLVERS.get((node_ref.domain, node_ref.kind))
        if resolver is None:
            return None
        return resolver(self._session, node_ref)

    def get_neighbors(
        self,
        node_ref: GraphNodeRef,
        *,
        relation_types: list[GraphRelationKind] | None = None,
        direction: GraphDirection = GraphDirection.OUTGOING,
        limit: int = 50,
    ) -> list[tuple[GraphEdgeRef, GraphNodeRef]]:
        source = self.get_node(node_ref)
        if source is None:
            raise NodeNotFoundError(node_ref)

        results: list[tuple[GraphEdgeRef, GraphNodeRef]] = []

        if source.domain == GraphDomain.KNOWLEDGE and source.kind in _KG_NODE_KINDS:
            results.extend(self._kg_neighbors(source, relation_types, direction, limit))

        if source.domain == GraphDomain.TASK and source.kind == GraphNodeKind.TASK:
            remaining = limit - len(results)
            if remaining > 0:
                results.extend(self._task_dep_neighbors(source, relation_types, direction, remaining))

        return results[:limit]

    def get_edges(
        self,
        node_ref: GraphNodeRef,
        *,
        direction: GraphDirection = GraphDirection.OUTGOING,
        relation_types: list[GraphRelationKind] | None = None,
        limit: int = 50,
    ) -> list[GraphEdgeRef]:
        source = self.get_node(node_ref)
        if source is None:
            raise NodeNotFoundError(node_ref)

        edges: list[GraphEdgeRef] = []
        if source.domain == GraphDomain.KNOWLEDGE and source.kind in _KG_NODE_KINDS:
            edges.extend(self._kg_edges(source, direction, relation_types, limit))

        if source.domain == GraphDomain.TASK and source.kind == GraphNodeKind.TASK:
            remaining = limit - len(edges)
            if remaining > 0:
                edges.extend(self._task_dep_edges(source, direction, relation_types, remaining))

        return edges[:limit]

    def validate_relationship(
        self,
        source: GraphNodeRef,
        relation: GraphRelationKind,
        target: GraphNodeRef,
    ) -> bool:
        """Valida a regra do relacionamento pelos tipos de origem e destino.

        A validade depende apenas dos tipos, conforme registrado em
        `RELATION_RULES` (model.py). A existência dos nós é verificada pelos
        chamadores quando necessário.
        """
        rule = relation_rule(relation)
        return rule.allows(source.kind, target.kind)

    # -- internos: grafo de conhecimento ----------------------------------

    def _kg_neighbors(
        self,
        source: GraphNodeRef,
        relation_types: list[GraphRelationKind] | None,
        direction: GraphDirection,
        limit: int,
    ) -> list[tuple[GraphEdgeRef, GraphNodeRef]]:
        from agent.persistence.models import KgEdgeModel, KgNodeModel

        src_id = self._resolve_kg_node_id(source)
        if src_id is None:
            return []

        edges = list(
            self._session.scalars(
                select(KgEdgeModel).where(KgEdgeModel.project_id == source.project_id)
            ).all()
        )

        out: list[tuple[GraphEdgeRef, GraphNodeRef]] = []
        for edge in edges:
            if edge.src_id != src_id and edge.dst_id != src_id:
                continue
            rel = to_relation_kind(edge.rel)
            if rel is None:
                continue
            if relation_types is not None and rel not in relation_types:
                continue
            if direction == GraphDirection.OUTGOING and edge.src_id != src_id:
                continue
            if direction == GraphDirection.INCOMING and edge.dst_id != src_id:
                continue
            other_id = edge.dst_id if edge.src_id == src_id else edge.src_id
            node = self._session.get(KgNodeModel, other_id)
            if node is None:
                continue
            target = _kg_node_to_ref(node)
            edge_ref = GraphEdgeRef(
                source, target, rel, metadata={"kg_edge_id": str(edge.id)}
            )
            out.append((edge_ref, target))
            if len(out) >= limit:
                break
        return out

    def _kg_edges(
        self,
        source: GraphNodeRef,
        direction: GraphDirection,
        relation_types: list[GraphRelationKind] | None,
        limit: int,
    ) -> list[GraphEdgeRef]:
        from agent.persistence.models import KgEdgeModel, KgNodeModel

        src_id = self._resolve_kg_node_id(source)
        if src_id is None:
            return []

        edges = list(
            self._session.scalars(
                select(KgEdgeModel).where(KgEdgeModel.project_id == source.project_id)
            ).all()
        )

        out: list[GraphEdgeRef] = []
        for edge in edges:
            if edge.src_id != src_id and edge.dst_id != src_id:
                continue
            if direction == GraphDirection.OUTGOING and edge.src_id != src_id:
                continue
            if direction == GraphDirection.INCOMING and edge.dst_id != src_id:
                continue
            rel = to_relation_kind(edge.rel)
            if rel is None:
                continue
            if relation_types is not None and rel not in relation_types:
                continue
            dst_id = edge.dst_id if edge.src_id == src_id else edge.src_id
            dst_node = self._session.get(KgNodeModel, dst_id)
            if dst_node is None:
                continue
            target = _kg_node_to_ref(dst_node)
            out.append(
                GraphEdgeRef(
                    source, target, rel, metadata={"kg_edge_id": str(edge.id)}
                )
            )
            if len(out) >= limit:
                break
        return out

    def _resolve_kg_node_id(self, node_ref: GraphNodeRef):
        from uuid import UUID
        from agent.persistence.models import KgNodeModel

        stmt = select(KgNodeModel.id).where(
            KgNodeModel.project_id == node_ref.project_id,
            func.lower(KgNodeModel.kind) == node_ref.kind.value.lower(),
            KgNodeModel.ref == node_ref.source_id,
        )
        return self._session.scalar(stmt)

    # -- internos: dependências de tarefa ----------------------------------

    def _task_dep_neighbors(
        self,
        source: GraphNodeRef,
        relation_types: list[GraphRelationKind] | None,
        direction: GraphDirection,
        limit: int,
    ) -> list[tuple[GraphEdgeRef, GraphNodeRef]]:
        from agent.persistence.models import TaskDependencyModel, TaskModel

        deps = list(
            self._session.scalars(
                select(TaskDependencyModel).where(TaskDependencyModel.task_id == source.id)
            ).all()
        )
        dependents = list(
            self._session.scalars(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.depends_on_task_id == source.id
                )
            ).all()
        )

        candidates: list[tuple[Any, GraphDirection]] = [
            (d, GraphDirection.OUTGOING) for d in deps
        ] + [(d, GraphDirection.INCOMING) for d in dependents]

        out: list[tuple[GraphEdgeRef, GraphNodeRef]] = []
        for dep, dirn in candidates:
            if direction not in (GraphDirection.UNDIRECTED, dirn):
                continue
            rel = (
                GraphRelationKind.DEPENDS_ON
                if dirn == GraphDirection.OUTGOING
                else GraphRelationKind.BLOCKED_BY
            )
            if relation_types is not None and rel not in relation_types:
                continue
            other_id = dep.depends_on_task_id if dirn == GraphDirection.OUTGOING else dep.task_id
            node = self._session.get(TaskModel, other_id)
            if node is None:
                continue
            target = _task_node_to_ref(node)
            edge_ref = GraphEdgeRef(
                source, target, rel, metadata={"task_dependency_id": str(dep.id)}
            )
            out.append((edge_ref, target))
            if len(out) >= limit:
                break
        return out

    def _task_dep_edges(
        self,
        source: GraphNodeRef,
        direction: GraphDirection,
        relation_types: list[GraphRelationKind] | None,
        limit: int,
    ) -> list[GraphEdgeRef]:
        from agent.persistence.models import TaskDependencyModel, TaskModel

        deps = list(
            self._session.scalars(
                select(TaskDependencyModel).where(TaskDependencyModel.task_id == source.id)
            ).all()
        )
        dependents = list(
            self._session.scalars(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.depends_on_task_id == source.id
                )
            ).all()
        )

        out: list[GraphEdgeRef] = []
        for dep in deps:
            if direction == GraphDirection.INCOMING:
                continue
            rel = GraphRelationKind.DEPENDS_ON
            if relation_types is not None and rel not in relation_types:
                continue
            node = self._session.get(TaskModel, dep.depends_on_task_id)
            if node is None:
                continue
            out.append(
                GraphEdgeRef(
                    source, _task_node_to_ref(node), rel,
                    metadata={"task_dependency_id": str(dep.id)},
                )
            )
            if len(out) >= limit:
                break
        for dep in dependents:
            if direction == GraphDirection.OUTGOING:
                continue
            rel = GraphRelationKind.BLOCKED_BY
            if relation_types is not None and rel not in relation_types:
                continue
            node = self._session.get(TaskModel, dep.task_id)
            if node is None:
                continue
            out.append(
                GraphEdgeRef(
                    source, _task_node_to_ref(node), rel,
                    metadata={"task_dependency_id": str(dep.id)},
                )
            )
            if len(out) >= limit:
                break
        return out


# -- resolvers de nós por domínio ------------------------------------------


def _kg_node_to_ref(node) -> GraphNodeRef:
    from agent.persistence.models import KgNodeModel

    try:
        kind = GraphNodeKind(node.kind.upper())
    except ValueError:
        kind = GraphNodeKind.FILE
    return GraphNodeRef(
        id=node.id,
        domain=GraphDomain.KNOWLEDGE,
        kind=kind,
        source_system="kg",
        source_id=node.ref,
        project_id=node.project_id,
        scope=GraphScope.PROJECT,
        version=1,
        status=GraphStatus.ACTIVE,
        metadata=dict(node.meta_json or {}),
    )


@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.FILE)
@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.SYMBOL)
@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.DOCUMENT)
@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.CONCEPT)
@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.FUNCTION)
@_register_resolver(GraphDomain.KNOWLEDGE, GraphNodeKind.CLASS)
def _resolve_knowledge_node(session: Session, node_ref: GraphNodeRef) -> GraphNodeRef | None:
    from agent.persistence.models import KgNodeModel

    stmt = select(KgNodeModel).where(
        KgNodeModel.project_id == node_ref.project_id,
        func.lower(KgNodeModel.kind) == node_ref.kind.value.lower(),
        KgNodeModel.ref == node_ref.source_id,
    )
    row = session.scalar(stmt)
    if row is None:
        return None
    return _kg_node_to_ref(row)


@_register_resolver(GraphDomain.MEMORY, GraphNodeKind.MEMORY)
def _resolve_memory_node(session: Session, node_ref: GraphNodeRef) -> GraphNodeRef | None:
    from agent.persistence.models import MemoryRecordModel

    row = session.get(MemoryRecordModel, node_ref.id)
    if row is None or row.project_id != node_ref.project_id:
        return None
    return GraphNodeRef(
        id=row.id,
        domain=GraphDomain.MEMORY,
        kind=GraphNodeKind.MEMORY,
        source_system="memory",
        source_id=str(row.id),
        project_id=row.project_id,
        scope=GraphScope.PROJECT,
        version=row.version,
        status=GraphStatus.ACTIVE,
        metadata={
            "kind": row.kind,
            "title": row.title,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "source_refs": row.source_refs_json,
        },
    )


@_register_resolver(GraphDomain.TASK, GraphNodeKind.TASK)
def _resolve_task_node(session: Session, node_ref: GraphNodeRef) -> GraphNodeRef | None:
    from agent.persistence.models import TaskModel

    row = session.get(TaskModel, node_ref.id)
    if row is None or row.project_id != node_ref.project_id:
        return None
    return GraphNodeRef(
        id=row.id,
        domain=GraphDomain.TASK,
        kind=GraphNodeKind.TASK,
        source_system="task",
        source_id=str(row.id),
        project_id=row.project_id,
        scope=GraphScope.TASK,
        version=1,
        status=GraphStatus.ACTIVE,
        metadata={
            "title": row.title,
            "objective": row.objective,
            "status": row.status,
            "kind": row.kind,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    )


def _task_node_to_ref(node) -> GraphNodeRef:
    return GraphNodeRef(
        id=node.id,
        domain=GraphDomain.TASK,
        kind=GraphNodeKind.TASK,
        source_system="task",
        source_id=str(node.id),
        project_id=node.project_id,
        scope=GraphScope.TASK,
        version=1,
        status=GraphStatus.ACTIVE,
        metadata={
            "title": node.title,
            "objective": node.objective,
            "status": node.status,
            "kind": node.kind,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        },
    )


@_register_resolver(GraphDomain.DECISION, GraphNodeKind.EVIDENCE)
def _resolve_evidence_node(session: Session, node_ref: GraphNodeRef) -> GraphNodeRef | None:
    from agent.persistence.models import EvidenceModel

    row = session.get(EvidenceModel, node_ref.id)
    if row is None:
        return None
    return GraphNodeRef(
        id=row.id,
        domain=GraphDomain.DECISION,
        kind=GraphNodeKind.EVIDENCE,
        source_system="evidence",
        source_id=str(row.id),
        project_id=row.project_id,
        scope=GraphScope.TASK,
        version=1,
        status=GraphStatus.ACTIVE,
        metadata={
            "verifier": row.verifier,
            "passed": row.passed,
            "summary": row.summary,
            "task_id": str(row.task_id) if row.task_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
    )


@_register_resolver(GraphDomain.AGENT, GraphNodeKind.AGENT)
def _resolve_agent_node(session: Session, node_ref: GraphNodeRef) -> GraphNodeRef | None:
    from agent.persistence.models import AgentModel

    row = session.get(AgentModel, node_ref.id)
    if row is None or row.project_id != node_ref.project_id:
        return None
    return GraphNodeRef(
        id=row.id,
        domain=GraphDomain.AGENT,
        kind=GraphNodeKind.AGENT,
        source_system="agent",
        source_id=str(row.id),
        project_id=row.project_id,
        scope=GraphScope.AGENT,
        version=1,
        status=GraphStatus.ACTIVE,
        metadata={"name": row.name, "role": row.role},
    )


__all__ = [
    "GraphRepository",
    "UnifiedGraphService",
    "NodeNotFoundError",
    "InvalidRelationshipError",
]
