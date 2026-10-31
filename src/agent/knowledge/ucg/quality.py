"""
Arquivo: src/agent/knowledge/ucg/quality.py
Nome: quality.py
Propósito: Quality Graph — critérios de qualidade antecipados, evidências rastreáveis,
testes direcionados e verificação incremental vinculados a tarefas e decisões.
Responsabilidade: camada de aplicação — expõe critérios de qualidade como nós do UCG com
relações para tarefas, artefatos, decisões e evidências, permitindo que a qualidade participe
do planejamento e da execução, e não apareça somente no final.
Componentes: QualityCriterion, QualityEvidence, QualityVerification, QualityGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.persistence.models,
agent.verification.runner, dataclasses, datetime, typing, uuid.
Observações: não grava dados de negócio além dos modelos existentes (`evidences`,
`memory_records`). Não substitui o sistema de verificação vigente; integra-se a ele para
expor critérios e evidências como nós do grafo.
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

#: Nível de importância padrão de um critério de qualidade.
_DEFAULT_IMPORTANCE = "medio"

#: Limiar de confiança para considerar um critério como aprovado.
_PASS_CONFIDENCE = 0.7


@dataclass
class QualityCriterion:
    """Critério de qualidade antecipado vinculado a uma tarefa ou requisito.

    Atributos:
        criterion_id: identificador estável do critério.
        title: título curto do critério.
        description: descrição do que precisa ser comprovado.
        importance: nível de importância (`baixo`, `medio`, `alto`, `critico`).
        verification_type: tipo de verificação (`pytest`, `script`, `command`, `file_exists`, ...).
        acceptance_criteria: critério de aceite textual.
        evidence_required: tipos de evidência exigidos.
        task_id: tarefa a qual o critério pertence.
        requirement_id: requisito a qual o critério está vinculado.
        status: status (`pendente`, `aprovado`, `reprovado`, `bloqueado`).
        confidence: nível de confiança na avaliação (0 a 1).
        created_at: instante de criação.
        updated_at: instante da última atualização.
        metadata: metadados livres.
    """

    criterion_id: str
    title: str
    description: str
    importance: str = _DEFAULT_IMPORTANCE
    verification_type: str = "script"
    acceptance_criteria: str = ""
    evidence_required: list[str] = field(default_factory=list)
    task_id: str | None = None
    requirement_id: str | None = None
    status: str = "pendente"
    confidence: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte o critério para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.criterion_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.QUALITY,
            kind=GraphNodeKind.REQUIREMENT,
            source_system="quality",
            source_id=self.criterion_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.status in ("pendente", "aprovado") else GraphStatus.BLOCKED,
            metadata={
                "title": self.title,
                "description": self.description,
                "importance": self.importance,
                "verification_type": self.verification_type,
                "acceptance_criteria": self.acceptance_criteria,
                "status": self.status,
                "confidence": self.confidence,
                **({"created_at": self.created_at.isoformat()} if self.created_at else {}),
            },
        )

    @property
    def is_approved(self) -> bool:
        """Diz se o critério está aprovado com confiança suficiente."""
        return self.status == "aprovado" and self.confidence >= _PASS_CONFIDENCE


@dataclass
class QualityEvidence:
    """Evidência de qualidade vinculada a um critério e artefato.

    Atributos:
        evidence_id: identificador estável da evidência.
        criterion_id: identificador do critério a qual a evidência está vinculada.
        artifact: caminho ou identificador do artefato verificado.
        verification_type: tipo de verificação que gerou a evidência.
        passed: se a verificação passou.
        summary: resumo textual do resultado.
        detail: detalhe estruturado da verificação.
        verified_at: instante da verificação.
        verifier: verificador ou processo que gerou a evidência.
        metadata: metadados livres.
    """

    evidence_id: str
    criterion_id: str
    artifact: str
    verification_type: str
    passed: bool
    summary: str = ""
    detail: dict[str, Any] | None = None
    verified_at: datetime | None = None
    verifier: str = "quality_graph"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a evidência para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.evidence_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.QUALITY,
            kind=GraphNodeKind.EVIDENCE,
            source_system="quality",
            source_id=self.evidence_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.passed else GraphStatus.BLOCKED,
            metadata={
                "criterion_id": self.criterion_id,
                "artifact": self.artifact,
                "verification_type": self.verification_type,
                "passed": self.passed,
                "summary": self.summary,
                **({"verified_at": self.verified_at.isoformat()} if self.verified_at else {}),
            },
        )


@dataclass
class QualityVerification:
    """Resultado de uma verificação de qualidade executada.

    Atributos:
        verification_id: identificador estável da verificação.
        criterion_id: identificador do critério verificado.
        task_id: tarefa a qual a verificação pertence.
        verifier_type: tipo do verificador executado.
        passed: `True` aprovado, `False` reprovado, `None` inconclusivo.
        summary: resumo do resultado.
        detail: detalhe estruturado.
        executed_at: instante da execução.
        metadata: metadados livres.
    """

    verification_id: str
    criterion_id: str
    task_id: str | None
    verifier_type: str
    passed: bool | None
    summary: str = ""
    detail: dict[str, Any] | None = None
    executed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class QualityGraphService:
    """Serviço do Quality Graph integrado ao UCG.

    Registra critérios de qualidade antecipados, evidências rastreáveis e resultados de
    verificação vinculados a tarefas, permitindo que a qualidade participe do planejamento
    e da execução de forma incremental.

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

    def register_criterion(
        self,
        *,
        criterion_id: str,
        task_id: str,
        title: str,
        description: str,
        importance: str = _DEFAULT_IMPORTANCE,
        verification_type: str = "script",
        acceptance_criteria: str = "",
        evidence_required: list[str] | None = None,
        project_id: str | None = None,
    ) -> QualityCriterion:
        """Registra um critério de qualidade antecipado vinculado a uma tarefa.

        Args:
            criterion_id: identificador estável do critério.
            task_id: identificador da tarefa.
            title: título curto.
            description: descrição do que precisa ser comprovado.
            importance: nível de importância.
            verification_type: tipo de verificação.
            acceptance_criteria: critério de aceite.
            evidence_required: tipos de evidência exigidos.
            project_id: escopo de projeto.

        Returns:
            O `QualityCriterion` registrado.
        """
        from sqlalchemy import select
        from uuid import UUID

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None:
            raise ValueError(f"Tarefa não encontrada: {task_id}")
        pid = str(task.project_id)

        memory_row = MemoryRecordModel(
            project_id=task.project_id,
            kind="quality_criterion",
            title=f"Critério: {title[:80]}",
            summary=description,
            content=(
                f"Critério: {title}\n"
                f"Descrição: {description}\n"
                f"Importância: {importance}\n"
                f"Verificação: {verification_type}\n"
                f"Aceite: {acceptance_criteria}"
            ),
            version=1,
            task_id=task.id,
            source_refs_json=list(evidence_required or []),
            outline_json={
                "criterion_id": criterion_id,
                "title": title,
                "description": description,
                "importance": importance,
                "verification_type": verification_type,
                "acceptance_criteria": acceptance_criteria,
                "status": "pendente",
                "task_id": task_id,
            },
        )
        self._session.add(memory_row)
        self._session.flush()

        return QualityCriterion(
            criterion_id=criterion_id,
            title=title,
            description=description,
            importance=importance,
            verification_type=verification_type,
            acceptance_criteria=acceptance_criteria,
            evidence_required=list(evidence_required or []),
            task_id=task_id,
            status="pendente",
            confidence=0.0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata={"project_id": pid},
        )

    def record_evidence(
        self,
        *,
        evidence_id: str,
        criterion_id: str,
        artifact: str,
        verification_type: str,
        passed: bool,
        summary: str = "",
        detail: dict[str, Any] | None = None,
        task_id: str,
        project_id: str | None = None,
    ) -> QualityEvidence:
        """Registra uma evidência de qualidade vinculada a um critério.

        Args:
            evidence_id: identificador estável da evidência.
            criterion_id: identificador do critério.
            artifact: caminho ou identificador do artefato verificado.
            verification_type: tipo de verificação.
            passed: se a verificação passou.
            summary: resumo do resultado.
            detail: detalhe estruturado.
            task_id: tarefa a qual a evidência pertence.
            project_id: escopo de projeto.

        Returns:
            O `QualityEvidence` registrado.
        """
        from uuid import UUID

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = self._session.get(TaskModel, tid)
        if task is None:
            raise ValueError(f"Tarefa não encontrada: {task_id}")

        ev_row = EvidenceModel(
            task_id=task.id,
            verifier="quality_graph",
            passed=passed,
            summary=summary,
            detail_json=detail,
            created_at=datetime.now(UTC),
        )
        self._session.add(ev_row)
        self._session.flush()

        return QualityEvidence(
            evidence_id=evidence_id,
            criterion_id=criterion_id,
            artifact=artifact,
            verification_type=verification_type,
            passed=passed,
            summary=summary,
            detail=detail,
            verified_at=datetime.now(UTC),
            verifier="quality_graph",
            metadata={},
        )

    def criterion_to_graph_node(self, criterion: QualityCriterion) -> GraphNodeRef:
        """Converte um `QualityCriterion` para um `GraphNodeRef` do UCG."""
        return criterion.to_graph_node_ref()

    def evidence_to_graph_node(self, evidence: QualityEvidence) -> GraphNodeRef:
        """Converte um `QualityEvidence` para um `GraphNodeRef` do UCG."""
        return evidence.to_graph_node_ref()

    def relate_criterion_to_task(
        self, criterion: QualityCriterion, task_id: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `APPLICABLE_TO` entre um critério e uma tarefa."""
        target = GraphNodeRef(
            id=hash(task_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.TASK,
            kind=GraphNodeKind.TASK,
            source_system="task",
            source_id=task_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        source = criterion.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.APPLICABLE_TO, target
        ):
            return None
        return GraphEdgeRef(
            source, target, GraphRelationKind.APPLICABLE_TO,
            metadata={"criterion_id": criterion.criterion_id, "task_id": task_id},
        )

    def list_criteria_for_task(
        self,
        *,
        task_id: str,
    ) -> list[QualityCriterion]:
        """Lista os critérios de qualidade registrados para uma tarefa.

        Args:
            task_id: identificador da tarefa.

        Returns:
            Lista de `QualityCriterion` ordenados por criação.
        """
        from sqlalchemy import select
        from uuid import UUID

        tid = UUID(task_id) if isinstance(task_id, str) else task_id
        stmt = select(MemoryRecordModel).where(
            MemoryRecordModel.kind == "quality_criterion",
            MemoryRecordModel.task_id == tid,
        )
        rows = list(self._session.scalars(stmt).all())
        criteria: list[QualityCriterion] = []
        for row in rows:
            meta = row.outline_json or {}
            criteria.append(
                QualityCriterion(
                    criterion_id=meta.get("criterion_id", str(row.id)),
                    title=meta.get("title", ""),
                    description=meta.get("description", ""),
                    importance=meta.get("importance", _DEFAULT_IMPORTANCE),
                    verification_type=meta.get("verification_type", "script"),
                    acceptance_criteria=meta.get("acceptance_criteria", ""),
                    evidence_required=list(meta.get("evidence_required", [])),
                    task_id=str(row.task_id) if row.task_id else None,
                    status=meta.get("status", "pendente"),
                    confidence=meta.get("confidence", 0.0),
                    created_at=row.created_at,
                    updated_at=row.created_at,
                    metadata=meta,
                )
            )
        criteria.sort(key=lambda c: c.created_at or datetime.min.replace(tzinfo=UTC))
        return criteria


__all__ = [
    "QualityCriterion",
    "QualityEvidence",
    "QualityVerification",
    "QualityGraphService",
    "_DEFAULT_IMPORTANCE",
    "_PASS_CONFIDENCE",
]
