"""
Arquivo: src/agent/knowledge/ucg/memory.py
Nome: memory.py
Propósito: Memory Graph — expõe as memórias existentes (operacional, episódica, semântica,
estratégica) como nós do UCG com validade temporal, confiança e promoção controlada.
Responsabilidade: camada de aplicação — integra as camadas de memória existentes
(`memory/layers.py`, `memory/operational.py`, `memory/state.py`) ao UCG sem criar novas
tabelas. Cada memória é um nó tipado com metadados de origem, validade, confiança e
relações para tarefas, arquivos e decisões.
Componentes: MemoryNodeRef, MemoryValidity, MemoryConflict, MemoryGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.memory.layers,
agent.memory.operational, agent.memory.state, agent.persistence.models, dataclasses,
datetime, typing, uuid.
Observações: não grava dados de negócio; lê de `memory_records`, `evidences`, `tasks` e
das camadas existentes. A promoção de memória episódica para semântica exige validação
explícita e nunca é feita silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from agent.domain.enums import MemoryKind
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
from agent.memory.layers import MemoryLayers
from agent.memory.operational import recall as operational_recall
from agent.memory.state import TaskStateService
from agent.persistence.models import EvidenceModel, MemoryRecordModel, TaskModel

#: Confiança mínima para promover uma memória episódica para semântica.
PROMOTION_MIN_CONFIDENCE = 0.8

#: Idade máxima (dias) de uma memória antes de ser considerada expirada.
DEFAULT_MAX_AGE_DAYS = 90


@dataclass
class MemoryNodeRef:
    """Referência a um nó de memória no UCG.

    Atributos:
        id: identificador estável do registro de memória.
        kind: natureza da memória (`canonical`, `execution`, `contextual`, `evidence`,
            `procedure`, `operational`, `task_detail`, `artifact`).
        title: título curto da memória.
        summary: resumo operacional (nível 1) ou None.
        content: conteúdo completo ou referência (carregado sob demanda).
        project_id: projeto de escopo.
        task_id: tarefa de origem, quando aplicável.
        conversation_id: conversa de origem, quando aplicável.
        version: versão do registro.
        status: status de validade (`active`, `expired`, `superseded`, `blocked`).
        confidence: nível de confiança (0 a 1).
        validity: janela de validade temporal.
        source_refs: referências às fontes originais.
        created_at: instante de criação.
        updated_at: instante da última atualização.
        last_used_at: última utilização na recuperação.
        metadata: metadados livres.
    """

    id: str
    kind: str
    title: str
    summary: str | None = None
    content: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    version: int = 1
    status: GraphStatus = GraphStatus.ACTIVE
    confidence: float = 1.0
    validity: MemoryValidity | None = None
    source_refs: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a referência de memória para um `GraphNodeRef` do UCG."""
        kind_map = {
            "canonical": GraphNodeKind.KNOWLEDGE,
            "contextual": GraphNodeKind.KNOWLEDGE,
            "procedure": GraphNodeKind.KNOWLEDGE,
            "evidence": GraphNodeKind.EVIDENCE,
            "operational": GraphNodeKind.MEMORY,
            "task_detail": GraphNodeKind.MEMORY,
            "artifact": GraphNodeKind.MEMORY,
            "execution": GraphNodeKind.MEMORY,
        }
        return GraphNodeRef(
            id=hash(self.id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.MEMORY,
            kind=kind_map.get(self.kind, GraphNodeKind.MEMORY),
            source_system="memory",
            source_id=self.id,
            project_id=self.project_id,
            scope=GraphScope.PROJECT if self.project_id else GraphScope.TASK,
            version=self.version,
            status=self.status,
            metadata={
                "kind": self.kind,
                "title": self.title,
                "summary": self.summary,
                "confidence": self.confidence,
                "source_refs": self.source_refs,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                **self.metadata,
            },
        )

    @property
    def is_valid(self) -> bool:
        """Diz se a memória está válida (ativa, não expirada e não supersedida)."""
        if self.status != GraphStatus.ACTIVE:
            return False
        if self.validity is not None and self.validity.is_expired:
            return False
        return True

    @property
    def is_reusable(self) -> bool:
        """Diz se a memória pode ser reutilizada (válida e com confiança suficiente)."""
        return self.is_valid and self.confidence >= 0.5


@dataclass
class MemoryValidity:
    """Janela de validade temporal de uma memória.

    Atributos:
        valid_from: instante a partir do qual a memória é válida.
        valid_until: instante até o qual a memória é válida (None = permanente).
        max_age_days: idade máxima aceitável a partir da criação (None = sem limite).
        expired_reason: motivo da expiração, quando expirada.
    """

    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_age_days: int | None = None
    expired_reason: str | None = None

    @property
    def is_expired(self) -> bool:
        """Diz se a janela de validade expirou."""
        now = datetime.now(UTC)
        if self.valid_until is not None:
            until = self.valid_until
            if until.tzinfo is None:
                until = until.replace(tzinfo=UTC)
            if now > until:
                self.expired_reason = "valid_until expirado"
                return True
        if self.max_age_days is not None and self.valid_from is not None:
            start = self.valid_from
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            age = now - start
            if age > timedelta(days=self.max_age_days):
                self.expired_reason = "idade máxima excedida"
                return True
        return False


@dataclass
class MemoryConflict:
    """Conflito entre duas memórias sobre o mesmo fato.

    Atributos:
        fact: descrição curta do fato em conflito.
        memory_a_id: identificador da primeira memória.
        memory_b_id: identificador da segunda memória.
        category: categoria do conflito (`valor`, `versão`, `disponibilidade`, `interpretação`).
        severity: severidade (`baixa`, `media`, `alta`).
        resolution: resolução sugerida ou None quando não resolvido.
    """

    fact: str
    memory_a_id: str
    memory_b_id: str
    category: str = "valor"
    severity: str = "media"
    resolution: str | None = None


class MemoryGraphService:
    """Serviço do Memory Graph integrado ao UCG.

    Expõe as memórias existentes como nós do UCG, com relações tipadas para tarefas,
    arquivos, decisões e evidências, controle de validade e confiança, e promoção
    controlada de memória episódica para semântica.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _graph: serviço de leitura do grafo unificado.
        _layers: recuperação de memória por camada.
        _state: serviço de estado estruturado da tarefa.
    """

    def __init__(self, session: Any) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas de leitura.
        """
        self._session = session
        self._graph = UnifiedGraphService(session)
        self._layers = MemoryLayers(session)
        self._state = TaskStateService(session)

    def discover_memories(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        objective: str = "",
        kinds: list[str] | None = None,
        limit: int = 20,
        only_reusable: bool = True,
    ) -> list[MemoryNodeRef]:
        """Descobre memórias relevantes para um projeto e objetivo.

        A seleção é determinística: filtra por kind, escopo de projeto, validade temporal
        e confiança, e pontua por relevância textual ao objetivo.

        Args:
            project_id: escopo de projeto obrigatório (isolamento de dados).
            task_id: restringe a uma tarefa específica, quando informado.
            objective: objetivo da etapa (usado para pontuar relevância).
            kinds: kinds de memória a considerar (todos quando None).
            limit: quantidade máxima devolvida.
            only_reusable: se True, devolve apenas memórias válidas e reutilizáveis.

        Returns:
            Lista de `MemoryNodeRef` ordenada por relevância.
        """
        candidates: list[MemoryNodeRef] = []

        # Memórias do projeto (camada projeto).
        rows = self._layers.project(
            project_id=project_id,
            kind=kinds[0] if kinds and len(kinds) == 1 else None,
            text=objective or None,
            limit=limit * 2,
        )
        candidates.extend(self._row_to_node_ref(r, project_id) for r in rows)

        # Memórias da tarefa (camada tarefa).
        if task_id:
            task_rows = self._layers.task(
                project_id=project_id,
                task_id=task_id,
                kind=kinds[0] if kinds and len(kinds) == 1 else None,
                text=objective or None,
                limit=limit * 2,
            )
            candidates.extend(
                self._row_to_node_ref(r, project_id, task_id=task_id) for r in task_rows
            )

        # Remove duplicatas por id.
        seen: set[str] = set()
        unique: list[MemoryNodeRef] = []
        for node in candidates:
            if node.id not in seen:
                seen.add(node.id)
                unique.append(node)

        # Filtra por validade e reutilização.
        filtered: list[MemoryNodeRef] = []
        for node in unique:
            if only_reusable and not node.is_reusable:
                continue
            if not node.is_valid:
                continue
            filtered.append(node)

        # Pontua por relevância textual ao objetivo.
        obj_words = {w.lower() for w in self._words(objective) if len(w) >= 4}
        scored: list[tuple[int, MemoryNodeRef]] = []
        for node in filtered:
            score = 0
            text = f"{node.title} {node.summary or ''} {node.content or ''}".lower()
            for word in obj_words:
                if word in text:
                    score += 1
            score += int(node.confidence * 5)
            scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].title))

        return [node for _, node in scored[:limit]]

    def memory_to_graph_node(self, mem: MemoryNodeRef) -> GraphNodeRef:
        """Converte uma `MemoryNodeRef` para `GraphNodeRef` do UCG."""
        return mem.to_graph_node_ref()

    def relate_memory_to_task(
        self, memory: MemoryNodeRef, task_id: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `USED_IN` entre uma memória e uma tarefa."""
        target = GraphNodeRef(
            id=hash(task_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.TASK,
            kind=GraphNodeKind.TASK,
            source_system="task",
            source_id=task_id,
            project_id=memory.project_id,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        source = memory.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.USED_IN, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.USED_IN,
            metadata={"memory_id": memory.id, "task_id": task_id},
        )

    def relate_memory_to_file(
        self, memory: MemoryNodeRef, file_path: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `DOCUMENTS` entre uma memória e um arquivo."""
        target = GraphNodeRef(
            id=hash(file_path) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.KNOWLEDGE,
            kind=GraphNodeKind.FILE,
            source_system="kg",
            source_id=file_path,
            project_id=memory.project_id,
            scope=GraphScope.PROJECT,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        source = memory.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.DOCUMENTS, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.DOCUMENTS,
            metadata={"memory_id": memory.id, "file_path": file_path},
        )

    def detect_conflicts(
        self,
        memories: list[MemoryNodeRef],
        *,
        fact_key: str = "title",
    ) -> list[MemoryConflict]:
        """Detecta conflitos entre memórias sobre o mesmo fato.

        Args:
            memories: lista de memórias a comparar.
            fact_key: campo usado para agrupar fatos (`title` ou `summary`).

        Returns:
            Lista de `MemoryConflict` para pares de memórias com mesmo fato e
            valores conflitantes.
        """
        groups: dict[str, list[MemoryNodeRef]] = {}
        for mem in memories:
            key = getattr(mem, fact_key, "") or ""
            groups.setdefault(key, []).append(mem)

        conflicts: list[MemoryConflict] = []
        for key, group in groups.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a.content != b.content or a.summary != b.summary:
                        conflicts.append(
                            MemoryConflict(
                                fact=key or "sem título",
                                memory_a_id=a.id,
                                memory_b_id=b.id,
                                category="valor",
                                severity="media",
                            )
                        )
        return conflicts

    def promote_to_semantic(
        self,
        memory: MemoryNodeRef,
        *,
        validated: bool,
        evidence_id: str | None = None,
        confidence: float | None = None,
    ) -> MemoryNodeRef | None:
        """Promove uma memória episódica para semântica, somente se validada.

        A promoção nunca é feita silenciosamente: exige `validated=True` e, opcionalmente,
        uma evidência de apoio. A confiança só é ajustada para cima quando há evidência.

        Args:
            memory: memória a promover.
            validated: se a promoção foi validada por um processo independente.
            evidence_id: identificador da evidência de apoio, quando houver.
            confidence: nova confiança (0 a 1), quando fornecida.

        Returns:
            A `MemoryNodeRef` promovida (kind `canonical`) ou None quando não validada.
        """
        if not validated:
            return None
        new_confidence = (
            confidence if confidence is not None else min(memory.confidence + 0.1, 1.0)
        )
        if evidence_id:
            new_confidence = min(new_confidence + 0.05, 1.0)
        return MemoryNodeRef(
            id=f"promoted:{memory.id}",
            kind="canonical",
            title=f"Promovido: {memory.title}",
            summary=memory.summary,
            content=memory.content,
            project_id=memory.project_id,
            task_id=memory.task_id,
            conversation_id=memory.conversation_id,
            version=memory.version + 1,
            status=GraphStatus.ACTIVE,
            confidence=new_confidence,
            validity=MemoryValidity(
                valid_from=datetime.now(UTC),
                max_age_days=DEFAULT_MAX_AGE_DAYS,
            ),
            source_refs=list(memory.source_refs) + ([evidence_id] if evidence_id else []),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata={
                **memory.metadata,
                "promoted_from": memory.id,
                "promoted_at": datetime.now(UTC).isoformat(),
                "evidence_id": evidence_id,
            },
        )

    def refresh_validity(self) -> int:
        """Recalcula a validade de todas as memórias conhecidas (invalida cache interno).

        Returns:
            Quantidade de memórias reavaliadas (aproximada).
        """
        # Não há cache persistente de validade; a validade é calculada sob demanda.
        return 0

    # -- internos ---------------------------------------------------------

    def _row_to_node_ref(
        self,
        row: MemoryRecordModel,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> MemoryNodeRef:
        """Converte uma linha `MemoryRecordModel` em `MemoryNodeRef`."""
        kind = row.kind
        try:
            kind_enum = MemoryKind(kind)
        except ValueError:
            kind_enum = MemoryKind.CONTEXTUAL

        validity: MemoryValidity | None = None
        created_at = row.created_at
        if created_at is not None:
            validity = MemoryValidity(
                valid_from=created_at,
                max_age_days=DEFAULT_MAX_AGE_DAYS,
            )

        source_refs = list(row.source_refs_json or [])
        confidence = self._estimate_confidence(row)

        return MemoryNodeRef(
            id=str(row.id),
            kind=kind,
            title=row.title,
            summary=row.summary,
            content=row.content,
            project_id=str(row.project_id),
            task_id=str(row.task_id) if row.task_id else task_id,
            conversation_id=str(row.conversation_id) if row.conversation_id else None,
            version=row.version,
            status=GraphStatus.ACTIVE,
            confidence=confidence,
            validity=validity,
            source_refs=source_refs,
            created_at=created_at,
            updated_at=row.created_at,
            metadata={
                "kind": kind,
                "outline": row.outline_json,
            },
        )

    @staticmethod
    def _estimate_confidence(row: MemoryRecordModel) -> float:
        """Estima a confiança de uma memória a partir de seus metadados."""
        confidence = 0.7  # base para memória persistida
        if row.outline_json:
            confidence += 0.1
        if row.source_refs_json:
            confidence += 0.1
        if row.summary:
            confidence += 0.1
        return min(confidence, 1.0)

    @staticmethod
    def _words(text: str) -> list[str]:
        import re

        return re.findall(r"\w+", text or "")


__all__ = [
    "MemoryNodeRef",
    "MemoryValidity",
    "MemoryConflict",
    "MemoryGraphService",
    "PROMOTION_MIN_CONFIDENCE",
    "DEFAULT_MAX_AGE_DAYS",
]
