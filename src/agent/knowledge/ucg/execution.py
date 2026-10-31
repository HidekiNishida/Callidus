"""
Arquivo: src/agent/knowledge/ucg/execution.py
Nome: execution.py
Propósito: Execution Graph — representa o DAG de operações e dependências de execução,
detecta ciclos bloqueantes, gerencia checkpoints e habilita retomada segura e reutilização
de resultados ainda válidos.
Responsabilidade: camada de aplicação — constrói o grafo de execução a partir de
`TaskDependencyModel` e `TaskModel`, valida aciclicidade, expõe tarefas prontas para
execução (sem dependências pendentes), e suporta checkpoints de retomada e reutilização
de resultados por fingerprint de artefatos.
Componentes: ExecutionNode, ExecutionEdge, CycleError, ExecutionGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.persistence.models,
dataclasses, datetime, typing, uuid.
Observações: não grava dados de negócio; lê de `tasks`, `task_dependencies` e
`execution_runs`. Os módulos de orquestração existentes (`runner.py`, `executor.py`)
continuam donos das gravações e da máquina de estados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

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
from agent.persistence.models import (
    ExecutionRunModel,
    TaskDependencyModel,
    TaskModel,
)

#: Limite máximo de iterações na detecção de ciclo (protege contra grafos malformados).
_MAX_CYCLE_DETECTION_ITERATIONS = 10000


@dataclass
class ExecutionNode:
    """Nó de execução (tarefa) no Execution Graph.

    Atributos:
        task_id: identificador da tarefa.
        title: título da tarefa.
        objective: objetivo da tarefa.
        status: estado atual da tarefa.
        kind: tipo da tarefa.
        depth: profundidade na árvore de tarefas.
        project_id: projeto de escopo.
        parent_id: tarefa-pai, quando houver.
        depends_on: IDs de tarefas das quais esta depende.
        dependents: IDs de tarefas que dependem desta.
        files: arquivos relacionados.
        ready: se todas as dependências estão concluídas (pronta para executar).
        completed: se a tarefa está concluída.
        result: resultado consolidado, quando houver.
        fingerprint: fingerprint do artefato para reutilização.
        metadata: metadados livres.
    """

    task_id: str
    title: str
    objective: str
    status: str
    kind: str
    depth: int = 0
    project_id: str | None = None
    parent_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    ready: bool = False
    completed: bool = False
    result: dict[str, Any] | None = None
    fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte o nó de execução para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.task_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.TASK,
            kind=GraphNodeKind.TASK,
            source_system="task",
            source_id=self.task_id,
            project_id=self.project_id,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE,
            metadata={
                "title": self.title,
                "objective": self.objective,
                "status": self.status,
                "kind": self.kind,
                "depth": self.depth,
                "ready": self.ready,
                "completed": self.completed,
                "fingerprint": self.fingerprint,
                **self.metadata,
            },
        )

    @property
    def is_blocked(self) -> bool:
        """Diz se a tarefa está bloqueada por dependência não concluída."""
        return not self.ready and not self.completed and self.status not in {
            "COMPLETED",
            "CANCELLED",
        }


@dataclass
class ExecutionEdge:
    """Aresta de dependência entre duas tarefas.

    Atributos:
        task_id: identificador da tarefa dependente.
        depends_on_task_id: identificador da tarefa da qual depende.
        relation: tipo de relação (`DEPENDS_ON` ou `BLOCKED_BY`).
    """

    task_id: str
    depends_on_task_id: str
    relation: str = "DEPENDS_ON"

    def to_graph_edge_ref(
        self, source: GraphNodeRef, target: GraphNodeRef
    ) -> GraphEdgeRef:
        """Converte a aresta para um `GraphEdgeRef` do UCG."""
        relation_kind = (
            GraphRelationKind.DEPENDS_ON
            if self.relation == "DEPENDS_ON"
            else GraphRelationKind.BLOCKED_BY
        )
        return GraphEdgeRef(source, target, relation_kind)


@dataclass
class CycleError(Exception):
    """Erro levantado quando um ciclo é detectado no grafo de execução.

    Atributos:
        cycle: lista de IDs de tarefas que formam o ciclo.
    """

    cycle: list[str]

    def __str__(self) -> str:
        return "ciclo detectado no grafo de execução: " + " -> ".join(self.cycle)


class ExecutionGraphService:
    """Serviço do Execution Graph integrado ao UCG.

    Constrói o DAG de execução a partir de `TaskDependencyModel` e `TaskModel`,
    detecta ciclos bloqueantes, expõe tarefas prontas para execução, e suporta
    checkpoints de retomada e reutilização de resultados por fingerprint de artefatos.

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

    def build_execution_graph(
        self,
        *,
        root_task_id: str | None = None,
        include_completed: bool = True,
    ) -> tuple[list[ExecutionNode], list[ExecutionEdge]]:
        """Constrói o grafo de execução a partir das dependências de tarefa.

        Args:
            root_task_id: tarefa-raiz para escopo (todas do projeto quando None).
            include_completed: se True, inclui tarefas concluídas no grafo.

        Returns:
            Tupla (nós, arestas) do grafo de execução.

        Raises:
            CycleError: quando um ciclo é detectado nas dependências.
        """
        from sqlalchemy import select

        # Carrega tarefas do escopo.
        stmt = select(TaskModel).where(TaskModel.project_id == self._project.id)
        if root_task_id is not None:
            # Inclui a raiz e suas descendentes.
            root_id = root_task_id
            stmt = select(TaskModel).where(
                TaskModel.project_id == self._project.id
            )
        rows = list(self._session.scalars(stmt).all())

        # Carrega dependências.
        dep_rows = list(
            self._session.scalars(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.task_id.in_([r.id for r in rows])
                    if rows
                    else False
                )
            ).all()
        )

        # Constrói nós.
        nodes: dict[str, ExecutionNode] = {}
        for row in rows:
            if not include_completed and row.status == "COMPLETED":
                continue
            deps = [str(d.depends_on_task_id) for d in dep_rows if d.task_id == row.id]
            dependents = [str(d.task_id) for d in dep_rows if d.depends_on_task_id == row.id]
            nodes[str(row.id)] = ExecutionNode(
                task_id=str(row.id),
                title=row.title,
                objective=row.objective,
                status=row.status,
                kind=row.kind,
                depth=0,  # calculado abaixo se houver pai
                project_id=str(row.project_id),
                parent_id=str(row.parent_id) if row.parent_id else None,
                depends_on=deps,
                dependents=dependents,
                files=[],
                ready=False,
                completed=row.status == "COMPLETED",
                result=None,
                fingerprint=None,
            )

        # Calcula profundidade e pronto-para-executar.
        completed_ids = {nid for nid, n in nodes.items() if n.completed}
        for nid, node in nodes.items():
            # Profundidade com base no pai.
            if node.parent_id and node.parent_id in nodes:
                node.depth = nodes[node.parent_id].depth + 1
            # Pronto quando todas as dependências estão concluídas.
            deps_in_scope = [d for d in node.depends_on if d in nodes]
            node.ready = all(d in completed_ids for d in deps_in_scope) and not node.completed

        # Detecta ciclos.
        self._detect_cycles(nodes)

        # Constrói arestas.
        edges: list[ExecutionEdge] = []
        for row in dep_rows:
            tid = str(row.task_id)
            did = str(row.depends_on_task_id)
            if tid in nodes and did in nodes:
                edges.append(
                    ExecutionEdge(task_id=tid, depends_on_task_id=did, relation="DEPENDS_ON")
                )

        return list(nodes.values()), edges

    def ready_tasks(self, *, root_task_id: str | None = None) -> list[ExecutionNode]:
        """Devolve tarefas prontas para execução (dependências concluídas).

        Args:
            root_task_id: tarefa-raiz para escopo.

        Returns:
            Lista de `ExecutionNode` prontas, ordenada por profundidade.
        """
        nodes, _ = self.build_execution_graph(root_task_id=root_task_id)
        ready = [n for n in nodes if n.ready and not n.completed]
        ready.sort(key=lambda n: (n.depth, n.title))
        return ready

    def next_task(self, *, root_task_id: str | None = None) -> ExecutionNode | None:
        """Devolve a próxima tarefa a executar (pronta, de menor profundidade).

        Args:
            root_task_id: tarefa-raiz para escopo.

        Returns:
            A próxima `ExecutionNode`, ou None quando não há nenhuma pronta.
        """
        ready = self.ready_tasks(root_task_id=root_task_id)
        return ready[0] if ready else None

    def has_cycle(self, *, root_task_id: str | None = None) -> bool:
        """Diz se há ciclo no grafo de execução do escopo.

        Args:
            root_task_id: tarefa-raiz para escopo.

        Returns:
            True quando há ciclo, False caso contrário.
        """
        try:
            self.build_execution_graph(root_task_id=root_task_id)
            return False
        except CycleError:
            return True

    def checkpoint(self, *, run_id: str, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Registra um checkpoint de retomada para uma tarefa.

        O checkpoint é gravado nos metadados da tarefa (`execution_checkpoint`),
        permitindo retomada sem reconstruir o estado.

        Args:
            run_id: identificador do run.
            task_id: identificador da tarefa.
            state: estado a preservar para retomada.

        Returns:
            O dicionário do checkpoint gravado.
        """
        from sqlalchemy import select

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None:
            raise ValueError(f"Tarefa não encontrada: {task_id}")
        meta = dict(task.metadata_json or {})
        checkpoints = meta.get("execution_checkpoints", [])
        checkpoint = {
            "run_id": run_id,
            "task_id": task_id,
            "state": state,
            "created_at": datetime.now(UTC).isoformat(),
        }
        checkpoints.append(checkpoint)
        meta["execution_checkpoints"] = checkpoints
        task.metadata_json = meta
        self._session.flush()
        return checkpoint

    def resume_checkpoint(
        self, *, task_id: str, run_id: str | None = None
    ) -> dict[str, Any] | None:
        """Recupera o último checkpoint de uma tarefa para retomada.

        Args:
            task_id: identificador da tarefa.
            run_id: run específico, quando informado (último do run quando None).

        Returns:
            O estado do checkpoint, ou None quando não há checkpoint.
        """
        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None:
            return None
        meta = task.metadata_json or {}
        checkpoints = meta.get("execution_checkpoints", [])
        if not checkpoints:
            return None
        if run_id is not None:
            for cp in reversed(checkpoints):
                if cp.get("run_id") == run_id:
                    return cp.get("state")
            return None
        return checkpoints[-1].get("state")

    def reusable_result(
        self, *, task_id: str, artifact_fingerprint: str
    ) -> bool:
        """Verifica se há resultado reutilizável para uma tarefa com o mesmo fingerprint.

        Args:
            task_id: identificador da tarefa.
            artifact_fingerprint: fingerprint do artefato a comparar.

        Returns:
            True quando há resultado concluído com fingerprint compatível.
        """
        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None or task.status != "COMPLETED":
            return False
        result = task.consolidated_result_json or {}
        return result.get("fingerprint") == artifact_fingerprint

    # -- internos ---------------------------------------------------------

    def _detect_cycles(self, nodes: dict[str, ExecutionNode]) -> None:
        """Detecta ciclos nas dependências usando DFS com cores.

        Args:
            nodes: dicionário de nós do grafo.

        Raises:
            CycleError: quando um ciclo é encontrado.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in nodes}
        parent: dict[str, str | None] = {nid: None for nid in nodes}

        def dfs(nid: str, path: list[str]) -> None:
            color[nid] = GRAY
            path.append(nid)
            node = nodes[nid]
            for dep_id in node.depends_on:
                if dep_id not in nodes:
                    continue
                if color[dep_id] == GRAY:
                    cycle_start = path.index(dep_id)
                    raise CycleError(path[cycle_start:] + [dep_id])
                if color[dep_id] == WHITE:
                    parent[dep_id] = nid
                    dfs(dep_id, path)
            path.pop()
            color[nid] = BLACK

        for nid in nodes:
            if color[nid] == WHITE:
                dfs(nid, [])


__all__ = [
    "ExecutionNode",
    "ExecutionEdge",
    "CycleError",
    "ExecutionGraphService",
]
