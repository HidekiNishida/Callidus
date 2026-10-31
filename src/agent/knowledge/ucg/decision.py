"""
Arquivo: src/agent/knowledge/ucg/decision.py
Nome: decision.py
Propósito: Decision Graph — registra decisões operacionais, hipóteses, alternativas e
evidências de forma estruturada, vinculadas a tarefas e permitindo retomada sem
reconstrução integral.
Responsabilidade: camada de aplicação — armazena decisões usando os modelos existentes
(`EvidenceModel`, `MemoryRecordModel`) e expõe-as como nós do UCG com relações tipadas.
Não persiste chain-of-thought privado nem monólogos internos; apenas decisões, razões
resumidas, evidências e resultados verificáveis.
Componentes: DecisionKind, Hypothesis, Alternative, DecisionRecord, DecisionGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.persistence.models,
dataclasses, datetime, typing, uuid.
Observações: não grava dados de negócio além dos modelos existentes; as relações entre
decisões, hipóteses e evidências são expostas como arestas do UCG para consulta e auditoria.
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
from agent.persistence.models import EvidenceModel, MemoryRecordModel, TaskModel

#: Confiança mínima para considerar uma decisão como aceita.
_MIN_DECISION_CONFIDENCE = 0.6


@dataclass
class Hypothesis:
    """Hipótese levantada durante a resolução de um problema.

    Atributos:
        hypothesis_id: identificador estável da hipótese.
        statement: afirmação da hipótese.
        confidence: nível de confiança (0 a 1).
        supporting_evidence: IDs de evidências que apoiam a hipótese.
        contradicting_evidence: IDs de evidências que contradem a hipótese.
        status: status (`ativa`, `rejeitada`, `confirmada`, `descartada`).
        created_at: instante de criação.
    """

    hypothesis_id: str
    statement: str
    confidence: float = 0.5
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    status: str = "ativa"
    created_at: datetime | None = None

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a hipótese para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.hypothesis_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.DECISION,
            kind=GraphNodeKind.HYPOTHESIS,
            source_system="decision",
            source_id=self.hypothesis_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.status == "ativa" else GraphStatus.BLOCKED,
            metadata={
                "statement": self.statement,
                "confidence": self.confidence,
                "status": self.status,
                **({"created_at": self.created_at.isoformat()} if self.created_at else {}),
            },
        )


@dataclass
class Alternative:
    """Alternativa considerada e rejeitada ou aceita em uma decisão.

    Atributos:
        alternative_id: identificador estável da alternativa.
        description: descrição da alternativa.
        reason: motivo da escolha ou rejeição.
        accepted: se a alternativa foi aceita.
        confidence: nível de confiança na avaliação (0 a 1).
    """

    alternative_id: str
    description: str
    reason: str = ""
    accepted: bool = False
    confidence: float = 0.5

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a alternativa para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.alternative_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.DECISION,
            kind=GraphNodeKind.DECISION,
            source_system="decision",
            source_id=self.alternative_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.accepted else GraphStatus.BLOCKED,
            metadata={
                "description": self.description,
                "reason": self.reason,
                "accepted": self.accepted,
                "confidence": self.confidence,
            },
        )


@dataclass
class DecisionRecord:
    """Registro de decisão vinculado a uma tarefa.

    Atributos:
        decision_id: identificador estável da decisão.
        problem: problema identificado que motivou a decisão.
        decision: decisão tomada.
        rationale: justificativa resumida da decisão.
        confidence: nível de confiança na decisão (0 a 1).
        hypotheses: hipóteses consideradas.
        alternatives: alternativas avaliadas.
        evidence_ids: IDs de evidências que apoiam a decisão.
        task_id: tarefa a qual a decisão está vinculada.
        outcome: resultado observado, quando conhecido.
        outcome_evidence: IDs de evidências do resultado.
        status: status (`pendente`, `executada`, `revertida`, `bloqueada`).
        created_at: instante de criação.
        updated_at: instante da última atualização.
        metadata: metadados livres.
    """

    decision_id: str
    problem: str
    decision: str
    rationale: str = ""
    confidence: float = 0.5
    hypotheses: list[Hypothesis] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    task_id: str | None = None
    outcome: str | None = None
    outcome_evidence_ids: list[str] = field(default_factory=list)
    verified: bool = False
    status: str = "pendente"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a decisão para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.decision_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.DECISION,
            kind=GraphNodeKind.DECISION,
            source_system="decision",
            source_id=self.decision_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.status in ("pendente", "executada") else GraphStatus.BLOCKED,
            metadata={
                "problem": self.problem,
                "decision": self.decision,
                "rationale": self.rationale,
                "confidence": self.confidence,
                "status": self.status,
                "outcome": self.outcome,
                **({"created_at": self.created_at.isoformat()} if self.created_at else {}),
            },
        )

    @property
    def is_decided(self) -> bool:
        """Diz se a decisão foi tomada (não está mais pendente)."""
        return self.status != "pendente"


class DecisionGraphService:
    """Serviço do Decision Graph integrado ao UCG.

    Registra decisões, hipóteses, alternativas e evidências de forma estruturada,
    vinculando-as a tarefas e expondo-as como nós do UCG para consulta e auditoria.
    Permite retomada sem reconstrução integral do processo.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _graph: serviço de leitura do grafo unificado.
    """

    def __init__(self, session: Any) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas de leitura.
        """
        self._session = session
        self._graph = UnifiedGraphService(session)

    def record_decision(
        self,
        *,
        decision_id: str,
        task_id: str,
        problem: str,
        decision: str,
        rationale: str = "",
        confidence: float = 0.5,
        hypotheses: list[Hypothesis] | None = None,
        alternatives: list[Alternative] | None = None,
        evidence_ids: list[str] | None = None,
        project_id: str | None = None,
    ) -> DecisionRecord:
        """Registra uma decisão vinculada a uma tarefa.

        A decisão é persistida como um `MemoryRecordModel` (kind `decision`) e cada
        evidência como um `EvidenceModel`, preservando proveniência e permitindo
        retomada posterior.

        Args:
            decision_id: identificador estável da decisão.
            task_id: identificador da tarefa.
            problem: problema identificado.
            decision: decisão tomada.
            rationale: justificativa resumida.
            confidence: nível de confiança (0 a 1).
            hypotheses: hipóteses consideradas.
            alternatives: alternativas avaliadas.
            evidence_ids: IDs de evidências de apoio.
            project_id: escopo de projeto.

        Returns:
            O `DecisionRecord` registrado.
        """
        from sqlalchemy import select
        from uuid import UUID

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None:
            raise ValueError(f"Tarefa não encontrada: {task_id}")
        pid = str(task.project_id)

        # Persiste a decisão como memória estruturada.
        memory_row = MemoryRecordModel(
            project_id=task.project_id,
            kind="decision",
            title=f"Decisão: {decision[:80]}",
            summary=rationale or decision,
            content=(
                f"Problema: {problem}\n"
                f"Decisão: {decision}\n"
                f"Rationale: {rationale}\n"
                f"Confiança: {confidence}"
            ),
            version=1,
            task_id=task.id,
            source_refs_json=list(evidence_ids or []),
            outline_json={
                "decision_id": decision_id,
                "problem": problem,
                "decision": decision,
                "rationale": rationale,
                "confidence": confidence,
                "status": "pendente",
                "task_id": task_id,
            },
        )
        self._session.add(memory_row)
        self._session.flush()

        # Persiste cada evidência vinculada.
        for ev_id in evidence_ids or []:
            ev_row = EvidenceModel(
                task_id=task.id,
                verifier="decision_graph",
                passed=True,
                summary=f"Evidência para decisão {decision_id}: {ev_id}",
                detail=ev_id,
                project_id=task.project_id,
                created_at=datetime.now(UTC),
            )
            self._session.add(ev_row)
            self._session.flush()

        return DecisionRecord(
            decision_id=decision_id,
            problem=problem,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            hypotheses=list(hypotheses or []),
            alternatives=list(alternatives or []),
            evidence_ids=list(evidence_ids or []),
            task_id=task_id,
            status="pendente",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata={"project_id": pid},
        )

    def record_outcome(
        self,
        *,
        decision_id: str,
        outcome: str,
        evidence_ids: list[str] | None,
        verified: bool = False,
    ) -> DecisionRecord | None:
        """Registra o resultado observado de uma decisão previamente tomada.

        Args:
            decision_id: identificador da decisão.
            outcome: resultado observado.
            evidence_ids: IDs de evidências do resultado.
            verified: se o resultado foi verificado.

        Returns:
            O `DecisionRecord` atualizado, ou None quando a decisão não existe.
        """
        # Busca a decisão persistida como memória.
        from sqlalchemy import select

        stmt = select(MemoryRecordModel).where(
            MemoryRecordModel.kind == "decision",
        )
        rows = list(self._session.scalars(stmt).all())
        row = None
        for candidate in rows:
            meta = candidate.outline_json or {}
            if meta.get("decision_id") == decision_id:
                row = candidate
                break
        if row is None:
            return None

        meta = dict(row.outline_json or {})
        meta["outcome"] = outcome
        meta["outcome_evidence_ids"] = list(evidence_ids or [])
        meta["verified"] = verified
        meta["status"] = "executada"
        row.outline_json = meta
        row.updated_at = datetime.now(UTC)
        self._session.flush()

        return DecisionRecord(
            decision_id=decision_id,
            problem=meta.get("problem", ""),
            decision=meta.get("decision", ""),
            rationale=meta.get("rationale", ""),
            confidence=meta.get("confidence", 0.5),
            hypotheses=[],
            alternatives=[],
            evidence_ids=list(meta.get("evidence_ids", [])),
            task_id=str(row.task_id) if row.task_id else None,
            outcome=outcome,
            outcome_evidence_ids=list(evidence_ids or []),
            verified=verified,
            status="executada",
            created_at=row.created_at,
            updated_at=row.updated_at,
            metadata=meta,
        )

    def decision_to_graph_node(self, decision: DecisionRecord) -> GraphNodeRef:
        """Converte um `DecisionRecord` para um `GraphNodeRef` do UCG."""
        return decision.to_graph_node_ref()

    def hypothesis_to_graph_node(self, hypothesis: Hypothesis) -> GraphNodeRef:
        """Converte um `Hypothesis` para um `GraphNodeRef` do UCG."""
        return hypothesis.to_graph_node_ref()

    def alternative_to_graph_node(self, alternative: Alternative) -> GraphNodeRef:
        """Converte um `Alternative` para um `GraphNodeRef` do UCG."""
        return alternative.to_graph_node_ref()

    def relate_decision_to_hypothesis(
        self, decision: DecisionRecord, hypothesis: Hypothesis
    ) -> GraphEdgeRef | None:
        """Cria uma relação `EVIDENCED_BY` entre uma decisão e uma hipótese."""
        source = decision.to_graph_node_ref()
        target = hypothesis.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.EVIDENCED_BY, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.EVIDENCED_BY,
            metadata={"decision_id": decision.decision_id, "hypothesis_id": hypothesis.hypothesis_id},
        )

    def relate_hypothesis_to_evidence(
        self, hypothesis: Hypothesis, evidence_id: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `EVIDENCED_BY` entre uma hipótese e uma evidência."""
        source = hypothesis.to_graph_node_ref()
        target = GraphNodeRef(
            id=hash(evidence_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.DECISION,
            kind=GraphNodeKind.EVIDENCE,
            source_system="evidence",
            source_id=evidence_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        if not self._graph.validate_relationship(
            source, GraphRelationKind.EVIDENCED_BY, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.EVIDENCED_BY,
            metadata={"hypothesis_id": hypothesis.hypothesis_id, "evidence_id": evidence_id},
        )

    def list_decisions_for_task(
        self,
        *,
        task_id: str,
    ) -> list[DecisionRecord]:
        """Lista as decisões registradas para uma tarefa, permitindo retomada.

        Args:
            task_id: identificador da tarefa.

        Returns:
            Lista de `DecisionRecord` ordenados por criação.
        """
        from sqlalchemy import select
        from uuid import UUID

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        stmt = select(MemoryRecordModel).where(
            MemoryRecordModel.kind == "decision",
            MemoryRecordModel.task_id == tid,
        )
        rows = list(self._session.scalars(stmt).all())
        records: list[DecisionRecord] = []
        for row in rows:
            meta = row.outline_json or {}
            records.append(
                DecisionRecord(
                    decision_id=meta.get("decision_id", str(row.id)),
                    problem=meta.get("problem", ""),
                    decision=meta.get("decision", ""),
                    rationale=meta.get("rationale", ""),
                    confidence=meta.get("confidence", 0.5),
                    hypotheses=[],
                    alternatives=[],
                    evidence_ids=list(meta.get("evidence_ids", [])),
                    task_id=str(row.task_id) if row.task_id else None,
                    outcome=meta.get("outcome"),
                    outcome_evidence_ids=list(meta.get("outcome_evidence_ids", [])),
                    verified=meta.get("verified", False),
                    status=meta.get("status", "pendente"),
                    created_at=row.created_at,
                    updated_at=row.created_at,
                    metadata=meta,
                )
            )
        records.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC))
        return records


__all__ = [
    "Hypothesis",
    "Alternative",
    "DecisionRecord",
    "DecisionGraphService",
    "_MIN_DECISION_CONFIDENCE",
]
