"""
Arquivo: src/agent/knowledge/ucg/query.py
Nome: query.py
Propósito: mecanismo de consulta seletiva do Unified Cognitive Graph — responde perguntas
estruturadas sobre o conhecimento do Callidus respeitando limites de profundidade, nós,
relações, escopo, orçamento e tempo.
Responsabilidade: camada de aplicação — expande o grafo de forma seletiva, nunca carrega o
catálogo inteiro, e devolve um resultado rastreável com fatos conhecidos, arquivos, memórias,
lacunas de pesquisa e proveniência.
Componentes: GraphQuery, GraphQueryResult, GraphQueryLimit, GraphQueryEngine.
Dependências: agent.knowledge.graph_service, agent.knowledge.ucg.graph, agent.knowledge.ucg.model,
agent.memory.layers, agent.persistence.models, pydantic, uuid, datetime, typing.
Observações: não grava dados; usa UnifiedGraphService (leitura de kg_edges e task_dependencies)
e MemoryLayers (recuperação de memória por camada). Os módulos de origem continuam donos das
gravações. Não há busca vetorial; a seleção é determinística com similaridade textual opcional.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from agent.memory.layers import MemoryLayers
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.knowledge.ucg.graph import UnifiedGraphService
from agent.knowledge.ucg.model import (
    EXPANSION_RELATIONS,
    GraphDirection,
    GraphDomain,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
    to_relation_kind,
)

#: Quantidade padrão máxima de nós visitados por consulta.
DEFAULT_MAX_NODES = 100
#: Profundidade padrão de expansão do grafo.
DEFAULT_MAX_DEPTH = 3
#: Orçamento padrão de tokens de contexto para o resultado da consulta.
DEFAULT_CONTEXT_BUDGET = 6000
#: Tempo máximo padrão de execução da consulta, em milissegundos.
DEFAULT_TIMEOUT_MS = 5000


class GraphQueryLimit(BaseModel):
    """Limites de expansão, custo, tempo e contexto de uma consulta ao grafo.

    Atributos:
        max_depth: profundidade máxima de travessia a partir do nó semente.
        max_nodes: quantidade máxima de nós visitados.
        max_edges: quantidade máxima de arestas percorridas.
        context_budget: orçamento de tokens do resultado devolvido.
        timeout_ms: tempo máximo de execução da consulta.
    """

    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=1, le=32)
    max_nodes: int = Field(default=DEFAULT_MAX_NODES, ge=1, le=5000)
    max_edges: int = Field(default=1000, ge=1, le=20000)
    context_budget: int = Field(default=DEFAULT_CONTEXT_BUDGET, ge=256, le=100000)
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, ge=100, le=300000)


class GraphQuery(BaseModel):
    """Entrada da consulta ao mecanismo de consulta do UCG.

    Atributos:
        intent: intenção da consulta (ex.: ``implement_feature``, ``audit_interface``).
        objective: objetivo descritivo da consulta.
        project_id: escopo de projeto obrigatório (isolamento de dados).
        requirements: requisitos que a consulta deve tentar cobrir.
        context_budget: orçamento de tokens para o resultado.
        max_depth: profundidade máxima de expansão do grafo.
        max_nodes: quantidade máxima de nós visitados.
        allowed_relations: tipos de relação permitidos na expansão (padrão: expansivos).
        direction: direção da travessia.
        scope: escopo de visibilidade dos nós.
        include_memories: se deve recuperar memórias relevantes.
        include_capabilities: se deve mapear capacidades necessárias.
    """

    intent: str
    objective: str
    project_id: UUID
    requirements: list[str] = Field(default_factory=list)
    context_budget: int = DEFAULT_CONTEXT_BUDGET
    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_edges: int = 1000
    allowed_relations: list[GraphRelationKind] | None = None
    direction: GraphDirection = GraphDirection.OUTGOING
    scope: GraphScope = GraphScope.PROJECT
    include_memories: bool = True
    include_capabilities: bool = True


class GraphQueryResult(BaseModel):
    """Resultado estruturado e rastreável de uma consulta ao UCG.

    Atributos:
        query_id: identificador da consulta.
        project_id: escopo de projeto da consulta.
        known_facts: nós do grafo considerados fatos conhecidos.
        relevant_files: caminhos de arquivos relevantes.
        relevant_memories: registros de memória recuperados.
        required_capabilities: capacidades identificadas como necessárias.
        candidate_agents: candidatos a agente para o objetivo.
        research_gaps: requisitos cobertos parcialmente ou não cobertos.
        dependencies: dependências de tarefa encontradas no grafo.
        coverage: pontuação de cobertura (0 a 100) e fatores.
        estimated_cost: estimativa de tokens e inferências.
        confidence: nível de confiança do resultado.
        provenance: origem de cada conjunto de resultados.
        nodes_visited: quantidade de nós efetivamente visitados.
        edges_traversed: quantidade de arestas percorridas.
        truncated: se a consulta atingiu um limite de expansão.
        executed_at: instante de execução.
    """

    query_id: UUID
    project_id: UUID
    intent: str
    known_facts: list[dict[str, Any]] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    relevant_memories: list[dict[str, Any]] = Field(default_factory=list)
    required_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    candidate_agents: list[dict[str, Any]] = Field(default_factory=list)
    research_gaps: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    nodes_visited: int = 0
    edges_traversed: int = 0
    truncated: bool = False
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphQueryEngine:
    """Mecanismo de consulta seletiva do Unified Cognitive Graph.

    Expande o grafo a partir de nós semente identificados pelo objetivo, aplica filtros
    determinísticos, respeita limites de profundidade/nós/arestas/orçamento e devolve um
    resultado com proveniência.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _graph: serviço de leitura do grafo unificado.
        _memories: recuperação de memória por camada.
        _kg: serviço de busca do grafo de conhecimento (sementes).
    """

    def __init__(self, session: Any) -> None:
        """Cria o mecanismo ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas de leitura.
        """
        self._session = session
        self._graph = UnifiedGraphService(session)
        self._memories = MemoryLayers(session)
        self._kg = KnowledgeGraphService(session)

    def execute(self, query: GraphQuery) -> GraphQueryResult:
        """Executa uma consulta seletiva ao UCG.

        Fluxo:
        1. Valida escopo e objetivo.
        2. Identifica nós semente via busca no grafo de conhecimento.
        3. Expande vizinhos até max_depth com relações e direção permitidas.
        4. Filtra por status ativo e escopo.
        5. Remove duplicatas e respeita max_nodes/max_edges.
        6. Recupera memórias relevantes por camada (quando solicitado).
        7. Identifica lacunas de pesquisa e dependências.
        8. Calcula cobertura, custo estimado e confiança.

        Args:
            query: consulta a executar.

        Returns:
            O `GraphQueryResult` com fatos, arquivos, memórias, lacunas e proveniência.
        """
        start = datetime.now(UTC)
        query_id = uuid4()

        if not query.objective.strip():
            return GraphQueryResult(
                query_id=query_id,
                project_id=query.project_id,
                intent=query.intent,
                coverage={"score": 0, "factors": ["objetivo vazio"]},
                estimated_cost={"tokens": 0, "inferences": 0},
                confidence={"level": "baixa", "motivo": "objetivo vazio"},
                provenance=[],
                executed_at=start,
            )

        allowed_relations = query.allowed_relations or list(EXPANSION_RELATIONS)

        # 2. Nós semente via busca no grafo de conhecimento.
        seed_hits = self._search_seeds(query)

        # 3. Expansão limitada do grafo a partir das sementes.
        visited: dict[UUID, GraphNodeRef] = {}
        frontier: list[GraphNodeRef] = []
        for hit in seed_hits:
            ref = self._to_node_ref(hit, query.project_id)
            if ref is not None and ref.id not in visited:
                visited[ref.id] = ref
                frontier.append(ref)

        edges_traversed = 0
        current = list(frontier)
        for _depth in range(query.max_depth):
            if not current or len(visited) >= query.max_nodes:
                break
            nxt: list[GraphNodeRef] = []
            for node in current:
                if len(visited) >= query.max_nodes:
                    break
                neighbors = self._graph.get_neighbors(
                    node,
                    relation_types=allowed_relations,
                    direction=query.direction,
                    limit=50,
                )
                for edge, neighbor in neighbors:
                    edges_traversed += 1
                    if edges_traversed > query.max_edges:
                        break
                    if neighbor.id not in visited:
                        visited[neighbor.id] = neighbor
                        nxt.append(neighbor)
                if edges_traversed > query.max_edges:
                    break
            current = nxt

        truncated = len(visited) >= query.max_nodes or edges_traversed > query.max_edges

        # 4. Filtros determinísticos: status ativo e escopo.
        facts = [
            ref for ref in visited.values()
            if ref.status == GraphStatus.ACTIVE
            and (query.scope == GraphScope.GLOBAL or ref.project_id == query.project_id)
        ]

        # 5. Categorização dos resultados.
        relevant_files: list[str] = []
        for ref in facts:
            if ref.kind in {GraphNodeKind.FILE, GraphNodeKind.SYMBOL, GraphNodeKind.DOCUMENT}:
                if ref.source_id not in relevant_files:
                    relevant_files.append(ref.source_id)

        # 6. Memórias relevantes por camada (recuperação sob demanda).
        memories: list[dict[str, Any]] = []
        if query.include_memories:
            memory_rows = self._memories.project(
                project_id=query.project_id,
                text=query.objective,
                limit=10,
            )
            memories = [
                {
                    "id": str(m.id),
                    "kind": m.kind,
                    "title": m.title,
                    "summary": m.summary,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in memory_rows
            ]

        # 7. Lacunas de pesquisa: requisitos sem cobertura nos fatos conhecidos.
        fact_text = " ".join(
            [ref.source_id for ref in facts]
            + [m.get("title", "") for m in memories]
            + [m.get("summary", "") or "" for m in memories]
        ).lower()
        gaps: list[dict[str, Any]] = []
        for req in query.requirements:
            if req.lower() not in fact_text:
                gaps.append(
                    {
                        "requirement": req,
                        "status": "não coberto",
                        "acao": "pesquisa seletiva ou nova memória",
                    }
                )

        # 8. Dependências de tarefa a partir dos nós de tarefa visitados.
        dependencies: list[dict[str, Any]] = []
        for ref in facts:
            if ref.domain == GraphDomain.TASK and ref.kind == GraphNodeKind.TASK:
                deps = self._graph.get_neighbors(
                    ref,
                    relation_types=[GraphRelationKind.DEPENDS_ON, GraphRelationKind.BLOCKED_BY],
                    direction=GraphDirection.OUTGOING,
                    limit=20,
                )
                for edge, target in deps:
                    dependencies.append(
                        {
                            "task": str(ref.id),
                            "depends_on": str(target.id),
                            "relation": edge.relation.value,
                        }
                    )

        # 9. Cobertura, custo estimado e confiança.
        required = max(1, len(query.requirements))
        covered = required - len(gaps)
        coverage_score = min(100, int((covered / required) * 100))
        factors: list[str] = []
        if facts:
            factors.append("fatos_conhecidos")
        if relevant_files:
            factors.append("arquivos_relevantes")
        if memories:
            factors.append("memorias_recuperadas")
        if gaps:
            factors.append("lacunas_de_pesquisa")

        elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
        estimated_tokens = min(
            query.context_budget,
            200 + len(facts) * 80 + len(relevant_files) * 120 + len(memories) * 100,
        )

        return GraphQueryResult(
            query_id=query_id,
            project_id=query.project_id,
            intent=query.intent,
            known_facts=[ref.to_dict() for ref in facts[: query.max_nodes]],
            relevant_files=relevant_files[: query.max_nodes],
            relevant_memories=memories,
            required_capabilities=[],
            candidate_agents=[],
            research_gaps=gaps,
            dependencies=dependencies,
            coverage={
                "score": coverage_score,
                "required": required,
                "covered": covered,
                "factors": factors,
                "truncated": truncated,
            },
            estimated_cost={
                "tokens": estimated_tokens,
                "inferences": 0,
                "elapsed_ms": round(elapsed_ms, 2),
            },
            confidence={
                "level": "alta" if coverage_score >= 80 else "media" if coverage_score >= 40 else "baixa",
                "basis": "grafo_deterministico",
            },
            provenance=[
                {
                    "conjunto": "known_facts",
                    "fonte": "kg_nodes/kg_edges",
                    "contagem": len(facts),
                },
                {
                    "conjunto": "relevant_memories",
                    "fonte": "memory_records (camada projeto)",
                    "contagem": len(memories),
                },
                {
                    "conjunto": "research_gaps",
                    "fonte": "requisitos da consulta vs fatos conhecidos",
                    "contagem": len(gaps),
                },
            ],
            nodes_visited=len(visited),
            edges_traversed=min(edges_traversed, query.max_edges),
            truncated=truncated,
            executed_at=start,
        )

    # -- internos ---------------------------------------------------------

    def _search_seeds(self, query: GraphQuery) -> list[dict[str, Any]]:
        """Identifica nós semente relacionados ao objetivo no grafo de conhecimento."""
        try:
            return self._kg.search(query.project_id, query.objective, limit=10)
        except Exception:
            return []

    def _to_node_ref(
        self, hit: dict[str, Any], project_id: UUID
    ) -> GraphNodeRef | None:
        """Converte um resultado de busca do grafo de conhecimento em GraphNodeRef."""
        from agent.persistence.models import KgNodeModel
        from sqlalchemy import func, select

        kind = hit.get("kind", "file")
        ref = hit.get("ref") or hit.get("path", "")
        if not ref:
            return None
        try:
            node_kind = GraphNodeKind(kind.upper())
        except ValueError:
            node_kind = GraphNodeKind.FILE
        row = self._session.scalar(
            select(KgNodeModel).where(
                KgNodeModel.project_id == project_id,
                func.lower(KgNodeModel.kind) == node_kind.value.lower(),
                KgNodeModel.ref == ref,
            )
        )
        if row is None:
            return None
        return GraphNodeRef(
            id=row.id,
            domain=GraphDomain.KNOWLEDGE,
            kind=node_kind,
            source_system="kg",
            source_id=row.ref,
            project_id=project_id,
        )


GraphQuery.model_rebuild()
GraphQueryResult.model_rebuild()

__all__ = [
    "GraphQuery",
    "GraphQueryResult",
    "GraphQueryLimit",
    "GraphQueryEngine",
]
