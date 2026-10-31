"""
Arquivo: src/agent/knowledge/ucg/strategy.py
Nome: strategy.py
Propósito: Strategy Graph — estratégias de resolução, resultados históricos e aprendizado
operacional, vinculados a tarefas e permitindo escolha adaptativa com prevenção contra
aprendizado incorreto.
Responsabilidade: camada de aplicação — registra estratégias de resolução (tipo de tarefa,
condições de aplicabilidade, sequência de operações, recursos utilizados, modelo utilizado,
agente utilizado, orçamento esperado, custo, risco, resultado esperado) e seus resultados
históricos (tokens, inferências, duração, ferramentas, taxa de sucesso, retrabalho, falhas,
qualidade, custo total), sem criar novas tabelas.
Componentes: Strategy, StrategyResult, StrategyGraphService.
Dependências: agent.knowledge.ucg.graph, agent.knowledge.ucg.model, agent.persistence.models,
dataclasses, datetime, statistics, typing, uuid.
Observações: não grava dados de negócio além dos modelos existentes (`memory_records`,
`evidences`, `inference_records`). A seleção adaptativa exige quantidade mínima de
observações e confiança estatística; nunca permite que uma estratégia sem validação
substitua uma estratégia comprovada.
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
    EvidenceModel,
    InferenceRecordModel,
    MemoryRecordModel,
    TaskModel,
)

#: Número mínimo de observações para considerar uma estratégia como comprovada.
_MIN_OBSERVATIONS = 5

#: Confiança mínima para considerar uma estratégia como preferível.
_MIN_CONFIDENCE = 0.6


@dataclass
class Strategy:
    """Estratégia de resolução de tarefas.

    Descreve como uma classe de tarefa pode ser resolvida, incluindo sequência de operações,
    recursos utilizados, modelo e agente envolvidos, orçamento esperado e resultado esperado.

    Atributos:
        strategy_id: identificador estável da estratégia.
        name: nome legível da estratégia.
        task_class: classe de tarefa à qual a estratégia se aplica.
        conditions: condições de aplicabilidade (condições sob as quais a estratégia vale).
        sequence: sequência de operações da estratégia.
        resources: recursos utilizados (capacidades, ferramentas, agentes).
        model: modelo utilizado.
        agent: agente utilizado.
        expected_budget: orçamento esperado (tokens estimados).
        cost: custo relativo estimado (`baixo`, `medio`, `alto`).
        risk: risco relativo (`baixo`, `medio`, `alto`).
        expected_result: resultado esperado.
        project_id: projeto de escopo.
        version: versão da estratégia.
        status: status (`ativa`, `descontinuada`, `experimental`).
        metadata: metadados livres.
    """

    strategy_id: str
    name: str
    task_class: str
    conditions: list[str] = field(default_factory=list)
    sequence: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    model: str = ""
    agent: str = ""
    expected_budget: int = 0
    cost: str = "medio"
    risk: str = "medio"
    expected_result: str = ""
    project_id: str | None = None
    version: int = 1
    status: str = "ativa"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a estratégia para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.strategy_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.STRATEGY,
            kind=GraphNodeKind.STRATEGY,
            source_system="strategy",
            source_id=self.strategy_id,
            project_id=self.project_id,
            scope=GraphScope.PROJECT,
            version=self.version,
            status=GraphStatus.ACTIVE if self.status == "ativa" else GraphStatus.BLOCKED,
            metadata={
                "name": self.name,
                "task_class": self.task_class,
                "cost": self.cost,
                "risk": self.risk,
                "expected_budget": self.expected_budget,
                **({"created_at": self.metadata.get("created_at")} if "created_at" in self.metadata else {}),
            },
        )


@dataclass
class StrategyResult:
    """Resultado histórico de uma execução de estratégia.

    Atributos:
        result_id: identificador estável do resultado.
        strategy_id: identificador da estratégia executada.
        task_class: classe de tarefa executada.
        tokens_in: tokens de entrada.
        tokens_out: tokens de saída.
        inferences: número de inferências realizadas.
        duration_seconds: duração da execução em segundos.
        tools_used: número de ferramentas acionadas.
        success: se a execução teve sucesso.
        rework: se houve retrabalho.
        failure: se houve falha.
        quality: nível de qualidade observado (0 a 1).
        total_cost: custo total estimado.
        evidence_id: identificador da evidência vinculada, quando houver.
        executed_at: instante da execução.
        metadata: metadados livres.
    """

    result_id: str
    strategy_id: str
    task_class: str
    tokens_in: int = 0
    tokens_out: int = 0
    inferences: int = 0
    duration_seconds: float = 0.0
    tools_used: int = 0
    success: bool = False
    rework: bool = False
    failure: bool = False
    quality: float = 0.0
    total_cost: str = "medio"
    evidence_id: str | None = None
    executed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte o resultado para um `GraphNodeRef` do UCG."""
        return GraphNodeRef(
            id=hash(self.result_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.STRATEGY,
            kind=GraphNodeKind.EXECUTION,
            source_system="strategy",
            source_id=self.result_id,
            project_id=None,
            scope=GraphScope.TASK,
            version=1,
            status=GraphStatus.ACTIVE if self.success else GraphStatus.BLOCKED,
            metadata={
                "strategy_id": self.strategy_id,
                "task_class": self.task_class,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "inferences": self.inferences,
                "duration_seconds": self.duration_seconds,
                "success": self.success,
                "quality": self.quality,
                **({"executed_at": self.executed_at.isoformat()} if self.executed_at else {}),
            },
        )


class StrategyGraphService:
    """Serviço do Strategy Graph integrado ao UCG.

    Registra estratégias de resolução e seus resultados históricos, permitindo escolha
    adaptativa baseada em evidências. Nunca permite que uma estratégia sem validação
    substitua uma estratégia comprovada.

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

    def register_strategy(
        self,
        *,
        strategy_id: str,
        name: str,
        task_class: str,
        conditions: list[str] | None,
        sequence: list[str] | None,
        resources: list[str] | None,
        model: str,
        agent: str,
        expected_budget: int,
        cost: str,
        risk: str,
        expected_result: str,
        project_id: str,
    ) -> Strategy:
        """Registra uma estratégia de resolução.

        Args:
            strategy_id: identificador estável da estratégia.
            name: nome legível.
            task_class: classe de tarefa.
            conditions: condições de aplicabilidade.
            sequence: sequência de operações.
            resources: recursos utilizados.
            model: modelo utilizado.
            agent: agente utilizado.
            expected_budget: orçamento esperado.
            cost: custo relativo.
            risk: risco relativo.
            expected_result: resultado esperado.
            project_id: projeto de escopo.

        Returns:
            O `Strategy` registrado.
        """
        from sqlalchemy import select

        pid = UUID(str(project_id)) if isinstance(project_id, str) else project_id

        memory_row = MemoryRecordModel(
            project_id=pid,
            kind="strategy",
            title=f"Estratégia: {name[:80]}",
            summary=expected_result,
            content=(
                f"Estratégia: {name}\n"
                f"Classe de tarefa: {task_class}\n"
                f"Modelo: {model}\n"
                f"Agente: {agent}\n"
                f"Orçamento esperado: {expected_budget}\n"
                f"Custo: {cost}\n"
                f"Risco: {risk}\n"
                f"Resultado esperado: {expected_result}"
            ),
            version=1,
            source_refs_json=[],
            outline_json={
                "strategy_id": strategy_id,
                "name": name,
                "task_class": task_class,
                "conditions": list(conditions or []),
                "sequence": list(sequence or []),
                "resources": list(resources or []),
                "model": model,
                "agent": agent,
                "expected_budget": expected_budget,
                "cost": cost,
                "risk": risk,
                "expected_result": expected_result,
                "status": "ativa",
            },
        )
        self._session.add(memory_row)
        self._session.flush()

        return Strategy(
            strategy_id=strategy_id,
            name=name,
            task_class=task_class,
            conditions=list(conditions or []),
            sequence=list(sequence or []),
            resources=list(resources or []),
            model=model,
            agent=agent,
            expected_budget=expected_budget,
            cost=cost,
            risk=risk,
            expected_result=expected_result,
            project_id=project_id,
            version=1,
            status="ativa",
        )

    def record_result(
        self,
        *,
        result_id: str,
        strategy_id: str,
        task_class: str,
        tokens_in: int,
        tokens_out: int,
        inferences: int,
        duration_seconds: float,
        tools_used: int,
        success: bool,
        rework: bool,
        failure: bool,
        quality: float,
        total_cost: str,
        evidence_id: str | None = None,
        executed_at: datetime | None = None,
        project_id: str,
    ) -> StrategyResult:
        """Registra o resultado de uma execução de estratégia.

        Args:
            result_id: identificador estável do resultado.
            strategy_id: identificador da estratégia.
            task_class: classe de tarefa.
            tokens_in: tokens de entrada.
            tokens_out: tokens de saída.
            inferences: número de inferências.
            duration_seconds: duração em segundos.
            tools_used: número de ferramentas acionadas.
            success: se teve sucesso.
            rework: se houve retrabalho.
            failure: se houve falha.
            quality: nível de qualidade (0 a 1).
            total_cost: custo total.
            evidence_id: identificador da evidência vinculada.
            executed_at: instante da execução.
            project_id: projeto de escopo.

        Returns:
            O `StrategyResult` registrado.
        """
        from uuid import UUID

        pid = UUID(str(project_id)) if isinstance(project_id, str) else project_id

        ev_row = None
        if evidence_id is not None:
            eid = UUID(evidence_id) if isinstance(evidence_id, str) else evidence_id
            ev_row = EvidenceModel(
                task_id=None,
                verifier="strategy_graph",
                passed=success,
                summary=f"Resultado da estratégia {strategy_id}: {task_class}",
                detail_json={"strategy_id": strategy_id, "task_class": task_class},
                created_at=executed_at or datetime.now(UTC),
            )
            self._session.add(ev_row)
            self._session.flush()

        memory_row = MemoryRecordModel(
            project_id=pid,
            kind="strategy_result",
            title=f"Resultado: {strategy_id} → {task_class}",
            summary=f"Sucesso: {success}, Qualidade: {quality:.2f}",
            content=(
                f"Estratégia: {strategy_id}\n"
                f"Tarefa: {task_class}\n"
                f"Tokens: {tokens_in} entrada / {tokens_out} saída\n"
                f"Inferências: {inferences}\n"
                f"Duração: {duration_seconds}s\n"
                f"Sucesso: {success}, Qualidade: {quality:.2f}"
            ),
            version=1,
            source_refs_json=[evidence_id] if evidence_id else [],
            outline_json={
                "result_id": result_id,
                "strategy_id": strategy_id,
                "task_class": task_class,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "inferences": inferences,
                "duration_seconds": duration_seconds,
                "tools_used": tools_used,
                "success": success,
                "rework": rework,
                "failure": failure,
                "quality": quality,
                "total_cost": total_cost,
                "evidence_id": evidence_id,
            },
        )
        self._session.add(memory_row)
        self._session.flush()

        return StrategyResult(
            result_id=result_id,
            strategy_id=strategy_id,
            task_class=task_class,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            inferences=inferences,
            duration_seconds=duration_seconds,
            tools_used=tools_used,
            success=success,
            rework=rework,
            failure=failure,
            quality=quality,
            total_cost=total_cost,
            evidence_id=evidence_id,
            executed_at=executed_at,
        )

    def select_strategy(
        self,
        *,
        task_class: str,
        conditions: list[str] | None,
        min_observations: int = _MIN_OBSERVATIONS,
    ) -> Strategy | None:
        """Seleciona a melhor estratégia para uma classe de tarefa.

        A seleção é baseada em evidências históricas: considera apenas estratégias com
        pelo menos `min_observations` resultados e confiança estatística suficiente.
        Nunca permite que uma estratégia sem validação substitua uma estratégia comprovada.

        Args:
            task_class: classe de tarefa.
            conditions: condições de aplicabilidade para filtrar estratégias.
            min_observations: número mínimo de observações para considerar uma estratégia.

        Returns:
            O `Strategy` selecionado, ou None quando não há estratégia comprovada.
        """
        from sqlalchemy import select

        # Carrega estratégias do escopo.
        rows = list(
            self._session.scalars(
                select(MemoryRecordModel).where(
                    MemoryRecordModel.kind == "strategy",
                )
            ).all()
        )

        strategies: list[Strategy] = []
        for row in rows:
            meta = row.outline_json or {}
            if meta.get("task_class") != task_class:
                continue
            if conditions:
                strat_conditions = set(meta.get("conditions", []))
                if not set(conditions).issubset(strat_conditions):
                    continue
            strategies.append(
                Strategy(
                    strategy_id=meta.get("strategy_id", str(row.id)),
                    name=meta.get("name", ""),
                    task_class=meta.get("task_class", ""),
                    conditions=list(meta.get("conditions", [])),
                    sequence=list(meta.get("sequence", [])),
                    resources=list(meta.get("resources", [])),
                    model=meta.get("model", ""),
                    agent=meta.get("agent", ""),
                    expected_budget=int(meta.get("expected_budget", 0)),
                    cost=meta.get("cost", "medio"),
                    risk=meta.get("risk", "medio"),
                    expected_result=meta.get("expected_result", ""),
                    project_id=None,
                    version=int(meta.get("version", 1)),
                    status=meta.get("status", "ativa"),
                    metadata=meta,
                )
            )

        if not strategies:
            return None

        # Carrega resultados históricos.
        result_rows = list(
            self._session.scalars(
                select(MemoryRecordModel).where(
                    MemoryRecordModel.kind == "strategy_result",
                )
            ).all()
        )

        # Agrupa resultados por estratégia.
        results_by_strategy: dict[str, list[StrategyResult]] = {}
        for row in result_rows:
            meta = row.outline_json or {}
            sid = meta.get("strategy_id")
            if sid not in results_by_strategy:
                results_by_strategy[sid] = []
            results_by_strategy[sid].append(
                StrategyResult(
                    result_id=meta.get("result_id", str(row.id)),
                    strategy_id=sid,
                    task_class=meta.get("task_class", ""),
                    tokens_in=int(meta.get("tokens_in", 0)),
                    tokens_out=int(meta.get("tokens_out", 0)),
                    inferences=int(meta.get("inferences", 0)),
                    duration_seconds=float(meta.get("duration_seconds", 0.0)),
                    tools_used=int(meta.get("tools_used", 0)),
                    success=bool(meta.get("success", False)),
                    rework=bool(meta.get("rework", False)),
                    failure=bool(meta.get("failure", False)),
                    quality=float(meta.get("quality", 0.0)),
                    total_cost=meta.get("total_cost", "medio"),
                    evidence_id=meta.get("evidence_id"),
                    executed_at=row.created_at,
                    metadata=meta,
                )
            )

        # Avalia cada estratégia com base em evidências suficientes.
        best: Strategy | None = None
        best_score = -1.0

        for strategy in strategies:
            results = results_by_strategy.get(strategy.strategy_id, [])
            n = len(results)
            if n < min_observations:
                continue  # Não há evidências suficientes.

            # Calcula taxa de sucesso e qualidade média.
            successes = sum(1 for r in results if r.success)
            success_rate = successes / n if n else 0.0
            avg_quality = sum(r.quality for r in results) / n if n else 0.0
            avg_tokens = (
                sum(r.tokens_in + r.tokens_out for r in results) / n if n else 0
            )

            # Confiança estatística: baseia-se no número de observações.
            confidence = min(1.0, n / (min_observations * 2))

            # A estratégia deve ter confiança mínima e sucesso razoável.
            if confidence < _MIN_CONFIDENCE or success_rate < 0.5:
                continue

            # Score: combina sucesso, qualidade e custo inverso.
            cost_weight = {"baixo": 1.0, "medio": 0.5, "alto": 0.1}.get(strategy.cost, 0.5)
            score = success_rate * 0.4 + avg_quality * 0.4 + cost_weight * 0.2

            if score > best_score:
                best_score = score
                best = strategy

        return best

    def strategy_to_graph_node(self, strategy: Strategy) -> GraphNodeRef:
        """Converte um `Strategy` para um `GraphNodeRef` do UCG."""
        return strategy.to_graph_node_ref()

    def result_to_graph_node(self, result: StrategyResult) -> GraphNodeRef:
        """Converte um `StrategyResult` para um `GraphNodeRef` do UCG."""
        return result.to_graph_node_ref()


__all__ = [
    "Strategy",
    "StrategyResult",
    "StrategyGraphService",
    "_MIN_OBSERVATIONS",
    "_MIN_CONFIDENCE",
]
