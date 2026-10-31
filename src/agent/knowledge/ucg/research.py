"""
Arquivo: src/agent/knowledge/ucg/research.py
Nome: research.py
Propósito: Knowledge Gap Resolver e Research Graph — detecta lacunas de conhecimento e
direciona pesquisa seletiva para preenchê-las, com proveniência, controle de atualidade
e reutilização de descobertas.
Responsabilidade: camada de aplicação — integra o `KnowledgeEngineService` existente
para identificar o que já se sabe, detectar lacunas em relação aos requisitos da tarefa,
e registrar pesquisas orientadas a lacunas com fonte, evidência, confiança e validade.
Componentes: ResearchGap, ResearchSource, ResearchFinding, KnowledgeGapResolver.
Dependências: agent.knowledge.service, agent.knowledge.ucg.graph, agent.knowledge.ucg.model,
agent.persistence.models, dataclasses, datetime, typing, uuid, re.
Observações: não cria novas tabelas; grava em `knowledge_items`, `knowledge_sources`,
`knowledge_requests` e `knowledge_validations` existentes. Pesquisa externa é opcional
e isolada; conteúdo externo é tratado como dado não confiável.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from agent.knowledge.service import KnowledgeEngineService
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
    KnowledgeItemModel,
    KnowledgeRequestModel,
    KnowledgeSourceModel,
    KnowledgeValidationModel,
    TaskModel,
)
from agent.knowledge.models import KnowledgeValidationStatus

#: Idade padrão (dias) após a qual uma descoberta é considerada possivelmente desatualizada.
_DEFAULT_MAX_AGE_DAYS = 90

#: Confiança mínima para considerar uma descoberta válida para reutilização.
_MIN_FINDING_CONFIDENCE = 0.6


@dataclass
class ResearchGap:
    """Lacuna de conhecimento identificada em relação aos requisitos de uma tarefa.

    Atributos:
        requirement: requisito não coberto.
        description: descrição curta do que falta saber.
        severity: severidade (`baixa`, `media`, `alta`, `critica`).
        suggested_source: tipo de fonte sugerida (`documentacao`, `web`, `codigo_local`, `especialista`).
        related_nodes: nós do UCG relacionados à lacuna.
        task_id: tarefa a qual a lacuna pertence, quando aplicável.
        resolved: se a lacuna foi resolvida por uma descoberta válida.
    """

    requirement: str
    description: str = ""
    severity: str = "media"
    suggested_source: str = "documentacao"
    related_nodes: list[str] = field(default_factory=list)
    task_id: str | None = None
    resolved: bool = False


@dataclass
class ResearchSource:
    """Fonte de pesquisa utilizada em uma descoberta.

    Atributos:
        source_id: identificador estável da fonte.
        type: tipo da fonte (`documentacao`, `web`, `github`, `servico_ia`, `analise_local`, `entrada_usuario`).
        title: título da fonte.
        url: URL ou referência da fonte, quando aplicável.
        accessed_at: instante de acesso.
        credibility: credibilidade da fonte (0 a 1).
        metadata: metadados livres.
    """

    source_id: str
    type: str
    title: str
    url: str | None = None
    accessed_at: datetime | None = None
    credibility: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a fonte para um `GraphNodeRef` do UCG."""
        kind_map = {
            "documentacao": GraphNodeKind.DOCUMENT,
            "web": GraphNodeKind.DOCUMENT,
            "github": GraphNodeKind.DOCUMENT,
            "servico_ia": GraphNodeKind.MODEL,
            "analise_local": GraphNodeKind.KNOWLEDGE,
            "entrada_usuario": GraphNodeKind.KNOWLEDGE,
        }
        return GraphNodeRef(
            id=hash(self.source_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.RESEARCH,
            kind=kind_map.get(self.type, GraphNodeKind.DOCUMENT),
            source_system="research",
            source_id=self.source_id,
            project_id=None,
            scope=GraphScope.PROJECT,
            version=1,
            status=GraphStatus.ACTIVE,
            metadata={
                "type": self.type,
                "title": self.title,
                "url": self.url,
                "credibility": self.credibility,
                **self.metadata,
            },
        )


@dataclass
class ResearchFinding:
    """Descoberta de pesquisa registrada com proveniência.

    Atributos:
        finding_id: identificador estável da descoberta.
        question: pergunta original que motivou a pesquisa.
        answer: resposta ou conclusão da descoberta.
        source: fonte de onde a descoberta veio.
        evidence: trechos de evidência da fonte.
        confidence: nível de confiança na descoberta (0 a 1).
        validity: janela de validade temporal da descoberta.
        task_id: tarefa a qual a descoberta se relaciona.
        verified: se a descoberta foi verificada independentemente.
        created_at: instante de criação.
        expires_at: instante de expiração da validade, quando aplicável.
        metadata: metadados livres.
    """

    finding_id: str
    question: str
    answer: str
    source: ResearchSource
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    validity: Any | None = None
    task_id: str | None = None
    verified: bool = False
    created_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a descoberta para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.finding_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.RESEARCH,
            kind=GraphNodeKind.RESEARCH_FINDING,
            source_system="research",
            source_id=self.finding_id,
            project_id=None,
            scope=GraphScope.PROJECT,
            version=1,
            status=GraphStatus.ACTIVE,
            metadata={
                "question": self.question,
                "answer": self.answer,
                "confidence": self.confidence,
                "verified": self.verified,
                "source_type": self.source.type,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                **self.metadata,
            },
        )

    @property
    def is_valid(self) -> bool:
        """Diz se a descoberta está válida (não expirada e com confiança suficiente)."""
        if self.expires_at is not None and datetime.now(UTC) > self.expires_at:
            return False
        return self.confidence >= _MIN_FINDING_CONFIDENCE


class KnowledgeGapResolver:
    """Resolvedor de lacunas de conhecimento integrado ao UCG.

    Usa o `KnowledgeEngineService` existente para buscar conhecimento já validado,
    identifica lacunas em relação aos requisitos da tarefa e direciona pesquisa
    seletiva somente para o que falta.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _engine: serviço de conhecimento existente.
        _graph: serviço de leitura do grafo unificado.
    """

    def __init__(self, session: Any) -> None:
        """Cria o resolvedor ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
        """
        self._session = session
        self._engine = KnowledgeEngineService(session)
        self._graph = UnifiedGraphService(session)

    def _resolve_project_id(self, project_id: str | UUID | None, task_id: str | UUID | None) -> UUID:
        """Resolve o UUID do projeto a partir de project_id ou task_id."""
        if project_id is not None:
            return UUID(str(project_id)) if isinstance(project_id, str) else project_id
        if task_id is not None:
            task = self._session.get(TaskModel, UUID(str(task_id)) if isinstance(task_id, str) else task_id)
            if task is not None:
                return task.project_id
        raise ValueError("project_id ou task_id é obrigatório para resolver o projeto")

    def identify_gaps(
        self,
        *,
        project_id: str | UUID,
        requirements: list[str],
        task_id: str | UUID | None = None,
    ) -> list[ResearchGap]:
        """Identifica lacunas de conhecimento para os requisitos informados.

        Para cada requisito, verifica se já existe conhecimento relevante no grafo
        de conhecimento existente. Requisitos sem cobertura geram uma lacuna.

        Args:
            project_id: escopo de projeto obrigatório.
            requirements: requisitos da tarefa.
            task_id: tarefa a qual as lacunas pertencem, quando aplicável.

        Returns:
            Lista de `ResearchGap` para requisitos não cobertos.
        """
        pid = UUID(str(project_id)) if isinstance(project_id, str) else project_id
        gaps: list[ResearchGap] = []
        for req in requirements:
            hits = self._engine.search_knowledge(project_id=pid, query=req, limit=5)
            if not hits:
                gaps.append(
                    ResearchGap(
                        requirement=req,
                        description=f"Nenhum conhecimento encontrado para: {req}",
                        severity="media",
                        suggested_source="documentacao",
                        task_id=str(task_id) if task_id else None,
                        resolved=False,
                    )
                )
        return gaps

    def resolve_gap(
        self,
        *,
        gap: ResearchGap,
        answer: str,
        source: ResearchSource,
        evidence: list[str] | None = None,
        confidence: float = 0.5,
        verified: bool = False,
        task_id: str | UUID | None = None,
        project_id: str | UUID | None = None,
    ) -> ResearchFinding:
        """Registra uma descoberta que preenche uma lacuna.

        A descoberta é persistida usando os modelos existentes de conhecimento
        (`knowledge_items`, `knowledge_sources`, `knowledge_validations`) e
        marcada com proveniência.

        Args:
            gap: lacuna a preencher.
            answer: resposta ou conclusão da pesquisa.
            source: fonte da descoberta.
            evidence: trechos de evidência da fonte.
            confidence: nível de confiança (0 a 1).
            verified: se a descoberta foi verificada independentemente.
            task_id: tarefa a qual a descoberta se relaciona.
            project_id: projeto de escopo (obrigatório se task_id não for informado).

        Returns:
            O `ResearchFinding` registrado.
        """
        pid = self._resolve_project_id(project_id, task_id)
        now = datetime.now(UTC)
        max_age_days = _DEFAULT_MAX_AGE_DAYS
        expires_at = now + timedelta(days=max_age_days)

        # 1. Cria o item de conhecimento.
        item_row = KnowledgeItemModel(
            project_id=pid,
            kind="fact",
            title=f"Descoberta: {gap.requirement[:80]}",
            content=answer,
            confidence=confidence,
            validation_status=KnowledgeValidationStatus.VALIDATED.value if verified else KnowledgeValidationStatus.UNVALIDATED.value,
        )
        self._session.add(item_row)
        self._session.flush()

        # 2. Registra a fonte do item.
        source_row = KnowledgeSourceModel(
            item_id=item_row.id,
            source_kind=source.type,
            title=source.title,
            url=source.url,
            credibility=source.credibility,
            meta_json=source.metadata,
        )
        self._session.add(source_row)
        self._session.flush()

        # 3. Registra a validação, quando solicitado.
        if verified:
            validation_row = KnowledgeValidationModel(
                item_id=item_row.id,
                validation_kind="independent",
                status=KnowledgeValidationStatus.VALIDATED.value,
                passed=True,
                notes="Validado independentemente durante a resolução de lacuna.",
                validated_at=now,
            )
            self._session.add(validation_row)
            self._session.flush()

        return ResearchFinding(
            finding_id=str(item_row.id),
            question=gap.requirement,
            answer=answer,
            source=source,
            evidence=list(evidence or []),
            confidence=confidence,
            validity=None,
            task_id=str(task_id) if task_id else gap.task_id,
            verified=verified,
            created_at=now,
            expires_at=expires_at,
            metadata={},
        )

    def find_existing_finding(
        self,
        *,
        project_id: str | UUID,
        question: str,
        max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    ) -> ResearchFinding | None:
        """Busca uma descoberta existente ainda válida para a mesma pergunta.

        Args:
            project_id: escopo de projeto.
            question: pergunta a verificar.
            max_age_days: idade máxima para considerar a descoberta válida.

        Returns:
            O `ResearchFinding` existente e válido, ou None quando não há.
        """
        pid = UUID(str(project_id)) if isinstance(project_id, str) else project_id
        hits = self._engine.search_knowledge(project_id=pid, query=question, limit=5)
        if not hits:
            return None
        best = hits[0]
        return ResearchFinding(
            finding_id=str(best.id),
            question=question,
            answer=best.content or "",
            source=ResearchSource(
                source_id=str(best.id),
                type="documentacao",
                title=best.title,
                credibility=best.confidence or 0.5,
            ),
            evidence=[],
            confidence=best.confidence or 0.5,
            validity=None,
            verified=True,
            created_at=best.created_at,
            expires_at=best.created_at + timedelta(days=max_age_days)
            if best.created_at
            else None,
            metadata={},
        )

    def detect_conflicts(
        self,
        findings: list[ResearchFinding],
    ) -> list[dict[str, Any]]:
        """Detecta conflitos entre descobertas sobre a mesma pergunta.

        Args:
            findings: lista de descobertas a comparar.

        Returns:
            Lista de conflitos com as descobertas envolvidas e o motivo.
        """
        conflicts: list[dict[str, Any]] = []
        for i in range(len(findings)):
            for j in range(i + 1, len(findings)):
                a, b = findings[i], findings[j]
                if a.question == b.question and a.answer != b.answer:
                    conflicts.append(
                        {
                            "question": a.question,
                            "finding_a_id": a.finding_id,
                            "finding_b_id": b.finding_id,
                            "answer_a": a.answer,
                            "answer_b": b.answer,
                            "confidence_a": a.confidence,
                            "confidence_b": b.confidence,
                            "severity": "alta"
                            if abs(a.confidence - b.confidence) > 0.4
                            else "media",
                        }
                    )
        return conflicts

    def gap_to_graph_node(self, gap: ResearchGap) -> GraphNodeRef:
        """Converte uma `ResearchGap` para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(gap.requirement) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.RESEARCH,
            kind=GraphNodeKind.RESEARCH_FINDING,
            source_system="research",
            source_id=f"gap:{gap.requirement}",
            project_id=None,
            scope=GraphScope.PROJECT,
            version=1,
            status=GraphStatus.BLOCKED if not gap.resolved else GraphStatus.ACTIVE,
            metadata={
                "requirement": gap.requirement,
                "description": gap.description,
                "severity": gap.severity,
                "suggested_source": gap.suggested_source,
                "resolved": gap.resolved,
            },
        )

    def finding_to_graph_node(self, finding: ResearchFinding) -> GraphNodeRef:
        """Converte um `ResearchFinding` para um `GraphNodeRef` do UCG."""
        return finding.to_graph_node_ref()

    def relate_finding_to_source(
        self, finding: ResearchFinding
    ) -> GraphEdgeRef | None:
        """Cria uma relação `DISCOVERED_BY` entre uma descoberta e sua fonte."""
        source = finding.to_graph_node_ref()
        target = finding.source.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.DISCOVERED_BY, target
        ):
            return None
        return GraphEdgeRef(
            source,
            target,
            GraphRelationKind.DISCOVERED_BY,
            metadata={
                "finding_id": finding.finding_id,
                "source_id": finding.source.source_id,
            },
        )


__all__ = [
    "ResearchGap",
    "ResearchSource",
    "ResearchFinding",
    "KnowledgeGapResolver",
    "_DEFAULT_MAX_AGE_DAYS",
    "_MIN_FINDING_CONFIDENCE",
]
