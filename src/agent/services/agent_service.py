# src/agent/services/agent_service.py — agentes lógicos: ciclo de vida e estado persistente
"""Serviço do agente lógico: identidade, papel, execuções e checkpoints.

O Callidus separa três coisas que antes apareciam misturadas:

| Conceito | Onde vive | O que acontece quando termina |
|----------|-----------|--------------------------------|
| Agente lógico | [`AgentModel`][agent.persistence.models.AgentModel] | continua existindo e consultável |
| Tarefa | [`TaskModel`][agent.persistence.models.TaskModel] | guarda resultado e evidências |
| Execução | [`AgentExecutionModel`][agent.persistence.models.AgentExecutionModel] | libera a memória de inferência |

O agente é 1:1 com a tarefa que ele executa, mas a relação é mantida por coluna — o
agente sobrevive à tarefa e a tarefa pode ser lida sem agente.

Duas garantias sustentam o resto do sistema:

1. **Nada se perde ao suspender.** O estado operacional vai para o checkpoint da
   execução e o conhecimento acumulado vai para os metadados do agente.
2. **Nada se perde ao descartar.** Descartar libera o estado recuperável; resultados,
   evidências e artefatos permanecem (a remoção definitiva é uma operação separada).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.domain.agent_enums import AgentStatus, ExecutionStatus, QueryStatus
from agent.domain.agent_lifecycle import (
    validate_agent_transition,
    validate_execution_transition,
)
from agent.domain.enums import TaskKind, TaskStatus
from agent.persistence.models import (
    AgentExecutionModel,
    AgentModel,
    AgentQueryModel,
    EvidenceModel,
    TaskDependencyModel,
    TaskModel,
)

__all__ = [
    "AgentNotFoundError",
    "AgentDepthError",
    "AgentService",
    "DiscardBlockedError",
]


class AgentNotFoundError(LookupError):
    """Agente inexistente."""


class AgentDepthError(RuntimeError):
    """A delegação passaria do limite de profundidade configurado."""


class DiscardBlockedError(RuntimeError):
    """Descartar o agente agora quebraria algo que ainda é necessário."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_for_kind(kind: str) -> str:
    return {
        TaskKind.OBJECTIVE.value: "orchestrator",
        TaskKind.SUBSYSTEM.value: "lead",
        TaskKind.OPERATION.value: "worker",
    }.get(kind, "worker")


class AgentService:
    """Operações sobre agentes lógicos e suas execuções."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ leitura

    def get(self, agent_id: uuid.UUID) -> AgentModel:
        agent = self._session.get(AgentModel, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agente não encontrado: {agent_id}")
        return agent

    def find(self, agent_id: uuid.UUID) -> AgentModel | None:
        return self._session.get(AgentModel, agent_id)

    def agent_for_task(self, task_id: uuid.UUID) -> AgentModel | None:
        stmt = select(AgentModel).where(AgentModel.task_id == task_id)
        return self._session.scalars(stmt).first()

    def children(self, agent_id: uuid.UUID) -> list[AgentModel]:
        stmt = (
            select(AgentModel)
            .where(AgentModel.parent_id == agent_id)
            .order_by(AgentModel.created_at, AgentModel.id)
        )
        return list(self._session.scalars(stmt).all())

    def descendants(self, agent_id: uuid.UUID) -> list[AgentModel]:
        """Descendentes em ordem de profundidade (o mais perto primeiro)."""
        found: list[AgentModel] = []
        frontier = [agent_id]
        seen = {agent_id}
        while frontier:
            current = frontier.pop(0)
            for child in self.children(current):
                if child.id in seen:
                    continue
                seen.add(child.id)
                found.append(child)
                frontier.append(child.id)
        return sorted(found, key=lambda a: (a.depth, a.created_at))

    def ancestors(self, agent_id: uuid.UUID) -> list[AgentModel]:
        """Cadeia de ancestrais, do mais distante para o mais próximo."""
        chain: list[AgentModel] = []
        current = self.get(agent_id)
        seen = {current.id}
        while current.parent_id:
            parent = self._session.get(AgentModel, current.parent_id)
            if parent is None or parent.id in seen:
                break
            chain.append(parent)
            seen.add(parent.id)
            current = parent
        return list(reversed(chain))

    def executions(self, agent_id: uuid.UUID) -> list[AgentExecutionModel]:
        stmt = (
            select(AgentExecutionModel)
            .where(AgentExecutionModel.agent_id == agent_id)
            .order_by(AgentExecutionModel.created_at, AgentExecutionModel.id)
        )
        return list(self._session.scalars(stmt).all())

    def current_execution(self, agent_id: uuid.UUID) -> AgentExecutionModel | None:
        """Execução viva ou recuperável do agente (a última em aberto)."""
        for execution in reversed(self.executions(agent_id)):
            if execution.status not in {
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.DISCARDED.value,
            }:
                return execution
        return None

    # ------------------------------------------------------------------ criação

    def ensure_agent(
        self,
        task_id: uuid.UUID,
        *,
        parent_agent_id: uuid.UUID | None = None,
        role: str | None = None,
        instructions: str | None = None,
    ) -> AgentModel:
        """Agente da tarefa, criado se ainda não existir.

        A hierarquia de agentes acompanha a hierarquia de tarefas: o pai lógico de uma
        tarefa filha é o agente da tarefa pai. Chamadas repetidas devolvem o mesmo
        agente — a identidade é estável.
        """
        existing = self.agent_for_task(task_id)
        if existing is not None:
            return existing
        task = self._session.get(TaskModel, task_id)
        if task is None:
            raise AgentNotFoundError(f"Tarefa não encontrada: {task_id}")
        parent: AgentModel | None = None
        if parent_agent_id is not None:
            parent = self.find(parent_agent_id)
        elif task.parent_id is not None:
            parent = self.ensure_agent(task.parent_id)
        depth = 0 if parent is None else parent.depth + 1
        if depth > self._settings.max_agent_depth:
            raise AgentDepthError(
                f"delegação além do limite de profundidade ({self._settings.max_agent_depth})"
            )
        agent = AgentModel(
            project_id=task.project_id,
            parent_id=parent.id if parent is not None else None,
            task_id=task.id,
            role=role or _role_for_kind(task.kind),
            instructions=instructions,
            status=AgentStatus.IDLE.value,
            depth=depth,
            metadata_json={"findings": [], "decisions": [], "artifacts": [], "tests": []},
        )
        self._session.add(agent)
        self._session.flush()
        return agent

    # --------------------------------------------------------------- transições

    def _set_agent_status(self, agent: AgentModel, target: AgentStatus) -> AgentModel:
        current = AgentStatus(agent.status)
        if current == target:
            return agent
        validate_agent_transition(current, target)
        agent.status = target.value
        return agent

    def _set_execution_status(
        self, execution: AgentExecutionModel, target: ExecutionStatus, error: str | None = None
    ) -> AgentExecutionModel:
        current = ExecutionStatus(execution.status)
        if current != target:
            validate_execution_transition(current, target)
        execution.status = target.value
        if error is not None:
            execution.last_error = error[:2000]
        if target in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
            execution.finished_at = datetime.now(timezone.utc)
        return execution

    # -------------------------------------------------------------- execuções

    def start_execution(
        self,
        agent_id: uuid.UUID,
        *,
        task_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> AgentExecutionModel:
        """Abre uma execução do agente.

        Reaproveita a execução recuperável (suspensa, falhada ou em espera) e cria uma
        nova quando a anterior já terminou: a execução antiga continua no histórico —
        o que ela encontrou não se perde.
        """
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is not None and ExecutionStatus(execution.status) in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.DISCARDED,
        }:
            execution = None
        if execution is None:
            execution = AgentExecutionModel(
                agent_id=agent.id,
                task_id=task_id or agent.task_id,
                run_id=run_id,
                status=ExecutionStatus.PENDING.value,
                checkpoint_json=checkpoint or {},
            )
            self._session.add(execution)
            self._session.flush()
        else:
            if task_id is not None:
                execution.task_id = task_id
            if run_id is not None:
                execution.run_id = run_id
            if checkpoint:
                merged = dict(execution.checkpoint_json or {})
                merged.update(checkpoint)
                execution.checkpoint_json = merged
        self._set_execution_status(execution, ExecutionStatus.RUNNING)
        execution.attempt = (execution.attempt or 0) + 1
        execution.started_at = datetime.now(timezone.utc)
        execution.finished_at = None
        self._set_agent_status(agent, AgentStatus.ACTIVE)
        self._session.flush()
        return execution

    def suspend(
        self, agent_id: uuid.UUID, *, reason: str = "", checkpoint: dict[str, Any] | None = None
    ) -> AgentExecutionModel:
        """Suspende a execução: persiste o estado e libera o contexto de inferência.

        O agente continua existindo e continua consultável; o que se libera é a
        execução. Nada é apagado.
        """
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None or ExecutionStatus(execution.status) not in {
            ExecutionStatus.RUNNING,
            ExecutionStatus.RESUMING,
            ExecutionStatus.WAITING_FOR_CHILD,
            ExecutionStatus.PENDING,
        }:
            raise AgentNotFoundError(
                f"o agente {agent_id} não tem execução ativa para suspender"
            )
        self._set_execution_status(execution, ExecutionStatus.SUSPENDING)
        if checkpoint:
            merged = dict(execution.checkpoint_json or {})
            merged.update(checkpoint)
            merged["suspended_at"] = _utcnow_iso()
            merged["suspend_reason"] = reason[:500]
            execution.checkpoint_json = merged
        else:
            checkpoint_data = dict(execution.checkpoint_json or {})
            checkpoint_data["suspended_at"] = _utcnow_iso()
            checkpoint_data["suspend_reason"] = reason[:500]
            execution.checkpoint_json = checkpoint_data
        # O estado operacional vai para o agente: ele precisa responder consultas
        # mesmo sem execução viva.
        metadata = dict(agent.metadata_json or {})
        metadata["checkpoint"] = execution.checkpoint_json
        agent.metadata_json = metadata
        self._set_execution_status(execution, ExecutionStatus.SUSPENDED)
        self._set_agent_status(agent, AgentStatus.SUSPENDED)
        self._session.flush()
        return execution

    def resume(self, agent_id: uuid.UUID) -> AgentExecutionModel:
        """Retoma a execução suspensa a partir do estado persistido."""
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            raise AgentNotFoundError(f"Agente sem execução recuperável: {agent_id}")
        status = ExecutionStatus(execution.status)
        if status in {ExecutionStatus.CANCELLED, ExecutionStatus.DISCARDED}:
            raise AgentNotFoundError(
                f"Execução do agente {agent_id} foi encerrada ({status.value}); "
                "é preciso abrir uma nova execução"
            )
        if status not in {ExecutionStatus.SUSPENDED, ExecutionStatus.FAILED}:
            # Já está viva: retomar é idempotente.
            return execution
        self._set_execution_status(execution, ExecutionStatus.RESUMING)
        self._set_execution_status(execution, ExecutionStatus.RUNNING)
        execution.attempt = (execution.attempt or 0) + 1
        execution.started_at = datetime.now(timezone.utc)
        execution.finished_at = None
        # Efeito externo não retomável precisa ser verificado antes de a ação ser
        # repetida: a retomada não pode assumir que o processo de antes continua.
        pending_effects = self.effects_requiring_verification(agent_id)
        if pending_effects:
            checkpoint = dict(execution.checkpoint_json or {})
            checkpoint["verify_before_repeat"] = [
                {
                    "effect_id": effect["effect_id"],
                    "description": effect["description"],
                    "verify_hint": effect.get("verify_hint") or "",
                }
                for effect in pending_effects
            ]
            execution.checkpoint_json = checkpoint
        self._set_agent_status(agent, AgentStatus.ACTIVE)
        self._session.flush()
        return execution

    def wait_for_child(self, agent_id: uuid.UUID) -> AgentExecutionModel:
        """A execução fica esperando uma resposta de descendente."""
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            raise AgentNotFoundError(f"Agente sem execução ativa: {agent_id}")
        self._set_execution_status(execution, ExecutionStatus.WAITING_FOR_CHILD)
        self._set_agent_status(agent, AgentStatus.WAITING)
        self._session.flush()
        return execution

    def complete_execution(
        self, agent_id: uuid.UUID, *, result: dict[str, Any] | None = None
    ) -> AgentExecutionModel:
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            raise AgentNotFoundError(f"Agente sem execução ativa: {agent_id}")
        if result:
            merged = dict(execution.checkpoint_json or {})
            merged.update(result)
            execution.checkpoint_json = merged
        self._set_execution_status(execution, ExecutionStatus.COMPLETED)
        self._set_agent_status(agent, AgentStatus.COMPLETED)
        self._session.flush()
        return execution

    def fail_execution(self, agent_id: uuid.UUID, error: str) -> AgentExecutionModel:
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            raise AgentNotFoundError(f"Agente sem execução ativa: {agent_id}")
        self._set_execution_status(execution, ExecutionStatus.FAILED, error=error)
        self._set_agent_status(agent, AgentStatus.FAILED)
        self._session.flush()
        return execution

    def cancel_execution(self, agent_id: uuid.UUID, *, reason: str = "") -> AgentExecutionModel:
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            raise AgentNotFoundError(f"Agente sem execução ativa: {agent_id}")
        self._set_execution_status(execution, ExecutionStatus.CANCELLED, error=reason)
        self._set_agent_status(agent, AgentStatus.IDLE)
        self._session.flush()
        return execution

    # ------------------------------------------------------------- checkpoint

    def save_checkpoint(
        self,
        agent_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        merge: bool = True,
    ) -> AgentExecutionModel:
        """Grava o estado operacional da execução (etapa, plano, pendências, erros)."""
        agent = self.get(agent_id)
        execution = self.current_execution(agent_id)
        if execution is None:
            execution = self.start_execution(agent_id)
        current = dict(execution.checkpoint_json or {}) if merge else {}
        current.update(payload or {})
        current = self.bound_checkpoint(current)
        current["updated_at"] = _utcnow_iso()
        execution.checkpoint_json = current
        metadata = dict(agent.metadata_json or {})
        metadata["checkpoint"] = current
        agent.metadata_json = metadata
        self._session.flush()
        return execution

    def bound_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        """Mantém o checkpoint dentro do limite configurado.

        O estado guardado é estruturado de propósito. Se ainda assim ele crescer demais
        (uma lista enorme de artefatos, um texto colado), o que sobra é a essência —
        etapa, plano, pendências — e os valores longos são truncados. Descobrir o resto
        é o que a consulta ao agente faz, sob demanda.
        """
        limit = max(1000, int(self._settings.max_agent_checkpoint_chars))
        bounded: dict[str, Any] = {}
        used = 0
        truncated = False
        for key, value in (checkpoint or {}).items():
            if isinstance(value, str):
                size = len(value)
                if used + size > limit:
                    bounded[key] = value[: max(0, limit - used)] + "…"
                    truncated = True
                    break
                bounded[key] = value
                used += size
            elif isinstance(value, list):
                bounded[key] = value[:50]
                used += len(str(value[:50]))
            else:
                bounded[key] = value
                used += len(str(value))
        if truncated or used > limit:
            bounded["truncated"] = True
        return bounded

    def checkpoint(self, agent_id: uuid.UUID) -> dict[str, Any]:
        execution = self.current_execution(agent_id)
        if execution is not None and execution.checkpoint_json:
            return dict(execution.checkpoint_json)
        agent = self.find(agent_id)
        if agent is None:
            return {}
        metadata = agent.metadata_json or {}
        return dict(metadata.get("checkpoint") or {})

    # ------------------------------------------------------------- conhecimento

    def record_finding(
        self,
        agent_id: uuid.UUID,
        text: str,
        *,
        evidence: list[str] | None = None,
        artifacts: list[str] | None = None,
        kind: str = "finding",
    ) -> dict[str, Any]:
        """Guarda uma descoberta do agente no estado persistente.

        Descoberta é informação com valor de evidência: o que foi observado, em que
        arquivo, com que prova. É isso que permite responder a uma consulta depois,
        sem reexecutar o trabalho.
        """
        agent = self.get(agent_id)
        metadata = dict(agent.metadata_json or {})
        findings = list(metadata.get("findings") or [])
        entry = {
            "kind": kind,
            "text": str(text)[:4000],
            "evidence": list(evidence or []),
            "artifacts": list(artifacts or []),
            "at": _utcnow_iso(),
        }
        findings.append(entry)
        metadata["findings"] = findings
        agent.metadata_json = metadata
        self._session.flush()
        return entry

    def findings(self, agent_id: uuid.UUID) -> list[dict[str, Any]]:
        agent = self.find(agent_id)
        if agent is None:
            return []
        return list((agent.metadata_json or {}).get("findings") or [])

    def record_task_result(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Importa o resultado e as evidências de uma tarefa para o agente dela.

        É o momento em que o filho "devolve" ao pai: o pai recebe um resumo curto
        (o que a consolidação já produz) e a evidência fica consultável sob demanda.
        """
        agent = self.agent_for_task(task_id)
        if agent is None:
            return []
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return []
        result = task.consolidated_result_json or {}
        metadata = dict(agent.metadata_json or {})
        if metadata.get("last_result") == result:
            # Já importado: a consolidação roda várias vezes e não deve duplicar
            # descobertas nem fazer o agente reanalisar o que já sabe.
            return []
        summary = result.get("summary") or result.get("markdown") or result.get("final_answer")
        evidence_rows = list(
            self._session.scalars(
                select(EvidenceModel)
                .where(EvidenceModel.task_id == task_id)
                .order_by(EvidenceModel.created_at, EvidenceModel.id)
            ).all()
        )
        evidence = [
            f"{row.verifier}: {row.summary}"[:500] for row in evidence_rows[-5:]
        ]
        if not summary and not evidence:
            return []
        entry = self.record_finding(
            agent.id,
            str(summary or f"Tarefa '{task.title}' concluída"),
            evidence=evidence,
            artifacts=list(result.get("sources") or []),
            kind="result",
        )
        metadata = dict(agent.metadata_json or {})
        metadata["last_result"] = result
        agent.metadata_json = metadata
        self._session.flush()
        return [entry]
    # ------------------------------------------------------- efeitos externos

    def record_external_effect(
        self,
        agent_id: uuid.UUID,
        *,
        description: str,
        effect_id: str,
        resumable: bool = False,
        verify_hint: str | None = None,
    ) -> dict[str, Any]:
        """Registra um efeito externo (comando, sessão, transação) que a execução fez.

        Processo de terminal, sessão de navegador ou transação externa **não** são
        recuperáveis pelo histórico do agente. Por isso o efeito fica registrado com
        a informação de que ele precisa ser verificado antes de ser repetido — evita
        que a retomada repita algo que já aconteceu.
        """
        agent = self.get(agent_id)
        metadata = dict(agent.metadata_json or {})
        effects = list(metadata.get("external_effects") or [])
        entry = {
            "effect_id": effect_id,
            "description": str(description)[:500],
            "resumable": bool(resumable),
            "verify_hint": (verify_hint or "")[:500],
            "verified": False,
            "at": _utcnow_iso(),
        }
        effects = [e for e in effects if e.get("effect_id") != effect_id]
        effects.append(entry)
        metadata["external_effects"] = effects
        agent.metadata_json = metadata
        self._session.flush()
        return entry

    def external_effects(self, agent_id: uuid.UUID) -> list[dict[str, Any]]:
        agent = self.find(agent_id)
        if agent is None:
            return []
        return list((agent.metadata_json or {}).get("external_effects") or [])

    def effects_requiring_verification(self, agent_id: uuid.UUID) -> list[dict[str, Any]]:
        """Efeitos externos que precisam ser verificados antes de a ação ser repetida."""
        return [
            effect
            for effect in self.external_effects(agent_id)
            if not effect.get("resumable") and not effect.get("verified")
        ]

    def mark_effect_verified(self, agent_id: uuid.UUID, effect_id: str) -> dict[str, Any] | None:
        agent = self.get(agent_id)
        metadata = dict(agent.metadata_json or {})
        effects = list(metadata.get("external_effects") or [])
        found = None
        for effect in effects:
            if effect.get("effect_id") == effect_id:
                effect["verified"] = True
                effect["verified_at"] = _utcnow_iso()
                found = effect
        metadata["external_effects"] = effects
        agent.metadata_json = metadata
        self._session.flush()
        return found

    # -------------------------------------------------------------- descarte

    def discard_checks(self, agent_id: uuid.UUID) -> dict[str, Any]:
        """Verifica o que impede descartar o agente agora."""
        agent = self.get(agent_id)
        pending_queries = list(
            self._session.scalars(
                select(AgentQueryModel).where(
                    AgentQueryModel.target_agent_id == agent_id,
                    AgentQueryModel.status.in_(
                        [QueryStatus.PENDING.value, QueryStatus.ROUTED.value]
                    ),
                )
            ).all()
        )
        live_descendants = [
            child
            for child in self.descendants(agent_id)
            if child.status
            in {AgentStatus.ACTIVE.value, AgentStatus.WAITING.value}
        ]
        blocked_dependencies: list[str] = []
        if agent.task_id is not None:
            dependents = self._session.scalars(
                select(TaskModel)
                .join(TaskDependencyModel, TaskDependencyModel.task_id == TaskModel.id)
                .where(TaskDependencyModel.depends_on_task_id == agent.task_id)
            ).all()
            for dependent in dependents:
                if TaskStatus(dependent.status) not in {
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                }:
                    blocked_dependencies.append(str(dependent.id))
        return {
            "pending_queries": [str(q.id) for q in pending_queries],
            "live_descendants": [str(d.id) for d in live_descendants],
            "blocked_dependencies": blocked_dependencies,
            "artifacts": list((agent.metadata_json or {}).get("artifacts") or []),
        }

    def discard(
        self,
        agent_id: uuid.UUID,
        *,
        purge: bool = False,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """Descarta o estado recuperável do agente.

        Três operações distintas, deliberadamente separadas:

        | Operação | Efeito |
        |----------|--------|
        | `suspend` | libera a execução, guarda o checkpoint |
        | `discard` (aqui) | descarta o estado recuperável, **preserva** resultados e artefatos |
        | `purge=True` | apaga as linhas persistidas do agente |

        Descartar nunca apaga tarefa, evidência ou artefato: o resultado pode ser
        necessário para a tarefa principal ou para outros agentes.
        """
        agent = self.get(agent_id)
        checks = self.discard_checks(agent_id)
        blocking = [
            key
            for key in ("pending_queries", "live_descendants", "blocked_dependencies")
            if checks[key]
        ]
        if blocking and not force:
            raise DiscardBlockedError(
                "não é possível descartar agora: " + ", ".join(blocking)
            )
        preserved = {
            "findings": self.findings(agent_id),
            "artifacts": list((agent.metadata_json or {}).get("artifacts") or []),
            "task_id": str(agent.task_id) if agent.task_id else None,
        }
        execution = self.current_execution(agent_id)
        if execution is not None:
            self._set_execution_status(execution, ExecutionStatus.DISCARDED, error=reason)
            # O checkpoint é o estado recuperável: some com ele. As descobertas, o
            # resultado e os artefatos permanecem — outro agente pode precisar deles.
            execution.checkpoint_json = None
        for query in self._session.scalars(
            select(AgentQueryModel).where(
                AgentQueryModel.target_agent_id == agent_id,
                AgentQueryModel.status.in_([QueryStatus.PENDING.value, QueryStatus.ROUTED.value]),
            )
        ).all():
            query.status = QueryStatus.CANCELLED.value
            query.error_message = "agente descartado"
        self._set_agent_status(agent, AgentStatus.DISCARDED)
        metadata = dict(agent.metadata_json or {})
        metadata.pop("checkpoint", None)
        metadata.update({"discarded": True, "reason": reason[:500], "preserved": preserved})
        agent.metadata_json = metadata
        self._session.flush()
        if purge:
            # Remoção definitiva: as linhas do agente e as referências a ele. As
            # tarefas, evidências e artefatos ficam — eles pertencem ao projeto.
            self._session.query(AgentQueryModel).filter(
                (AgentQueryModel.requester_agent_id == agent_id)
                | (AgentQueryModel.target_agent_id == agent_id)
            ).delete(synchronize_session=False)
            self._session.query(AgentExecutionModel).filter(
                AgentExecutionModel.agent_id == agent_id
            ).delete(synchronize_session=False)
            for child in self.children(agent_id):
                child.parent_id = None
            self._session.delete(agent)
            self._session.flush()
        return {
            "agent_id": str(agent_id),
            "purged": purge,
            "preserved": preserved,
            "checks": checks,
        }
