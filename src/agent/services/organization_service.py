"""
Arquivo: src/agent/services/organization_service.py
Nome: organization_service.py
Propósito: dar a cada tarefa um contrato de trabalho organizacional (responsável, revisor, escopo, risco), registrar revisões independentes e handoffs, e expor portões e etapa do fluxo.
Responsabilidade: camada de aplicação — liga o catálogo do domínio (`domain/organization.py`, `domain/work_flow.py`) ao estado persistido.
Componentes: OrganizationService, ReviewRejectedError, WORK_ITEM_KEY, responsibility_line.
Dependências: agent.domain.organization, agent.domain.work_flow, agent.orchestrator.requirements, agent.orchestrator.subtask_summary, agent.persistence.models, sqlalchemy.
Observações: tudo vive no `metadata_json` já existente da tarefa (`work_item`) e do agente (`assignment`, `handoff`) — nenhuma coluna nova. Nenhuma operação aqui chama o modelo.
"""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.domain.enums import AttemptKind
from agent.domain.organization import (
    OFFICES,
    OWNERSHIP,
    ROLES,
    SPECIALTIES,
    TEAMS,
    owner_of,
    reviewer_allowed,
    select_assignment,
)
from agent.domain.work_flow import (
    STAGE_ORDER,
    WorkSnapshot,
    evaluate_delivery,
    evaluate_gates,
    out_of_scope,
    stage_for,
)
from agent.persistence.models import (
    AgentModel,
    EvidenceModel,
    OperationAttemptModel,
    TaskModel,
)

#: Chave do contrato de trabalho no `metadata_json` da tarefa.
WORK_ITEM_KEY = "work_item"
#: Revisões guardadas por tarefa (as mais antigas saem primeiro).
_MAX_REVIEWS = 20
_REVIEW_DECISIONS = frozenset({"approved", "rejected"})


class ReviewRejectedError(ValueError):
    """Revisão recusada: decisão inválida ou revisor sem independência."""


def _now() -> str:
    """Instante atual em UTC, ISO 8601."""
    return datetime.now(UTC).isoformat()


def _aware_iso(value: datetime | None) -> str:
    """Data em ISO 8601 com fuso (o SQLite devolve datas ingênuas gravadas em UTC)."""
    if value is None:
        return _now()
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def responsibility_line(work_item: dict[str, Any] | None) -> str:
    """Uma linha com responsável, revisor e áreas que exigem coordenação, para o contexto da operação.

    Args:
        work_item: contrato de trabalho da tarefa.

    Returns:
        Texto curto, ou vazio quando não há atribuição.
    """
    assignment = (work_item or {}).get("assignment") or {}
    role = assignment.get("role")
    if not role:
        return ""
    team = TEAMS.get(assignment.get("team", ""))
    parts = [
        f"responsável: {ROLES[role].name} ({team.name if team else assignment.get('team')})",
        f"revisor: {ROLES.get(assignment.get('reviewer_role', ''), ROLES['qa_engineer']).name}",
    ]
    if assignment.get("protected_files"):
        parts.append("área protegida, coordenar com " + ", ".join(
            ROLES[r].name for r in assignment.get("coordination") or [] if r in ROLES) + ": "
            + ", ".join(assignment["protected_files"][:3]))
    elif assignment.get("shared_contracts"):
        parts.append("contrato compartilhado, preserve a interface: " + ", ".join(assignment["shared_contracts"][:3]))
    return "; ".join(parts)


class OrganizationService:
    """Contrato de trabalho, atribuição, revisão, handoff e portões de uma tarefa.

    Atributos:
        _session: sessão usada nas leituras e gravações.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    # ------------------------------------------------------------- catálogo

    def directory(self, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Organograma, papéis, especialidades, propriedade e (opcional) quem ocupa cada papel.

        Args:
            project_id: projeto cujos agentes são listados por papel; `None` devolve só o catálogo.

        Returns:
            Escritórios, equipes, papéis, especialidades, regras de propriedade e agentes por papel.
        """
        agents: list[dict[str, Any]] = []
        if project_id is not None:
            rows = self._session.scalars(
                select(AgentModel).where(AgentModel.project_id == project_id).order_by(AgentModel.created_at)
            ).all()
            for agent in rows:
                assignment = (agent.metadata_json or {}).get("assignment") or {}
                agents.append({
                    "id": str(agent.id),
                    "task_id": str(agent.task_id) if agent.task_id else None,
                    "hierarchy": agent.role,
                    "status": agent.status,
                    "role": assignment.get("role"),
                    "team": assignment.get("team"),
                    "specialties": assignment.get("specialties") or [],
                })
        return {
            "offices": [{"id": k, "name": v} for k, v in OFFICES.items()],
            "teams": [vars(t) for t in TEAMS.values()],
            "roles": [
                {**{k: v for k, v in vars(r).items() if k not in {"specialties", "reviews", "authority"}},
                 "specialties": list(r.specialties), "reviews": list(r.reviews), "authority": list(r.authority)}
                for r in ROLES.values()
            ],
            "specialties": [vars(s) for s in SPECIALTIES.values()],
            "ownership": [vars(o) for o in OWNERSHIP],
            "stages": [s.value for s in STAGE_ORDER],
            "agents": agents,
        }

    def owner(self, path: str) -> dict[str, Any] | None:
        """Dono de um caminho, com equipe e papel por extenso.

        Args:
            path: caminho relativo à raiz.

        Returns:
            A regra vencedora serializada, ou `None` quando o caminho não tem dono conhecido.
        """
        rule = owner_of(path)
        if rule is None:
            return None
        return {**vars(rule), "team_name": TEAMS[rule.team].name, "role_name": ROLES[rule.role].name}

    # ----------------------------------------------------- contrato de trabalho

    def _task(self, task_id: uuid.UUID) -> TaskModel:
        """Tarefa pelo id, ou `LookupError`."""
        task = self._session.get(TaskModel, task_id)
        if task is None:
            raise LookupError(f"Tarefa não encontrada: {task_id}")
        return task

    def _scope_paths(self, task: TaskModel) -> list[str]:
        """Escopo declarado da tarefa: `allowed_files`, ou os arquivos do contrato quando não houver."""
        meta = task.metadata_json or {}
        paths = [str(p) for p in (meta.get("allowed_files") or []) if isinstance(p, str)]
        if not paths:
            paths = [str(p) for p in (meta.get("target_files") or []) if isinstance(p, str)]
        return paths

    def assign(self, task: TaskModel, agent: AgentModel | None = None, *, persist: bool = True) -> dict[str, Any]:
        """Atribui (ou reatribui) a tarefa e grava o contrato de trabalho.

        É idempotente: enquanto objetivo, tipo, escopo e especialidade não mudam, devolve o
        contrato gravado sem tocar nas revisões nem no histórico.

        Args:
            task: tarefa a atribuir.
            agent: agente lógico da tarefa, que recebe o resumo da atribuição.
            persist: `False` calcula sem gravar — as rotas de leitura usam assim, para abrir o
                quadro não reescrever o `metadata_json` de todas as tarefas do banco.

        Returns:
            O contrato de trabalho (`metadata_json["work_item"]`).
        """
        meta = dict(task.metadata_json or {})
        paths = self._scope_paths(task)
        lead = meta.get("lead_specialty") or (meta.get("professional_strategy") or {}).get("lead_specialty")
        signature = {"objective": task.objective, "kind": task.kind, "paths": paths, "lead": lead}
        current = meta.get(WORK_ITEM_KEY) if isinstance(meta.get(WORK_ITEM_KEY), dict) else None
        if current and current.get("signature") == signature:
            work_item = copy.deepcopy(current)
        else:
            assignment = select_assignment(
                objective=task.objective, paths=paths, kind=task.kind, lead_specialty=lead
            ).to_dict()
            history = list((current or {}).get("history") or [])
            if current and current.get("assignment", {}).get("role") != assignment["role"]:
                history.append({"at": _now(), "from": current["assignment"].get("role"),
                                "to": assignment["role"], "reason": "escopo ou objetivo mudou"})
            work_item = {
                "id": f"{assignment['team'].split('_')[0].upper()}-{str(task.id)[:8]}",
                "objective": task.objective,
                "assignment": assignment,
                "scope": {"allowed_files": paths, "restricted_files": assignment["protected_files"]},
                "acceptance": {"criteria": task.acceptance_criteria or "",
                               "verification_methods": ["portão de verificação independente"]
                               + (["revisão registrada do papel de coordenação"]
                                  if assignment["protected_files"] or assignment["shared_contracts"] else [])},
                "reviews": list((current or {}).get("reviews") or []),
                "history": history,
                "signature": signature,
                "created_at": (current or {}).get("created_at") or _aware_iso(task.created_at),
            }
        if agent is not None:
            work_item["assignment"]["agent_id"] = str(agent.id)
        if not persist:
            return work_item
        if work_item != current:
            meta[WORK_ITEM_KEY] = work_item
            task.metadata_json = meta
        if agent is not None:
            agent_meta = dict(agent.metadata_json or {})
            summary = {k: work_item["assignment"][k] for k in ("team", "role", "reviewer_role", "specialties")}
            summary["agent_id"] = str(agent.id)
            if agent_meta.get("assignment") != summary:
                agent_meta["assignment"] = summary
                agent.metadata_json = agent_meta
        self._session.flush()
        return work_item

    def work_item(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Contrato de trabalho da tarefa, atribuído na hora se ainda não existir.

        Args:
            task_id: tarefa consultada.

        Returns:
            O contrato, com o handoff do agente quando houver.

        Raises:
            LookupError: quando a tarefa não existe.
        """
        task = self._task(task_id)
        agent = self._agent_for(task.id)
        item = self.assign(task, agent, persist=False)
        if agent is not None:
            item["handoff"] = (agent.metadata_json or {}).get("handoff")
        item.pop("signature", None)
        return item

    def _agent_for(self, task_id: uuid.UUID) -> AgentModel | None:
        """Agente lógico da tarefa, quando já criado."""
        return self._session.scalar(
            select(AgentModel).where(AgentModel.task_id == task_id).order_by(AgentModel.created_at).limit(1)
        )

    # -------------------------------------------------------------- revisão

    def record_review(
        self,
        task_id: uuid.UUID,
        *,
        role: str,
        decision: str,
        reason: str = "",
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Registra a revisão de um papel independente.

        A revisão pode reprovar uma tarefa já concluída pelo runtime: o status não volta, mas o
        portão G3 reprova e a etapa passa a `REWORK`, o que conta como defeito escapado.

        Args:
            task_id: tarefa revisada.
            role: papel de quem revisa.
            decision: `approved` ou `rejected`.
            reason: motivo (obrigatório para reprovar).
            evidence_ids: evidências conferidas pelo revisor.

        Returns:
            A revisão gravada.

        Raises:
            LookupError: quando a tarefa não existe.
            ReviewRejectedError: decisão inválida, motivo ausente na reprovação ou revisor sem
                independência (o próprio executor, ou papel que não revisa o executor).
        """
        task = self._task(task_id)
        item = self.assign(task, self._agent_for(task.id))
        executor = item["assignment"]["role"]
        if decision not in _REVIEW_DECISIONS:
            raise ReviewRejectedError(f"decisão inválida: {decision!r} (use approved ou rejected)")
        if decision == "rejected" and not reason.strip():
            raise ReviewRejectedError("reprovar exige um motivo")
        if not reviewer_allowed(executor, role):
            raise ReviewRejectedError(
                f"{role or 'papel vazio'} não pode revisar o trabalho de {executor}: a revisão precisa ser independente"
            )
        known = {str(e.id) for e in self._evidences(task.id)}
        cited = [e for e in (evidence_ids or []) if e in known]
        review = {"at": _now(), "role": role, "decision": decision, "reason": reason.strip()[:1000],
                  "evidence_ids": cited, "task_status": task.status}
        meta = dict(task.metadata_json or {})
        work_item = dict(meta.get(WORK_ITEM_KEY) or item)
        work_item["reviews"] = [*(work_item.get("reviews") or []), review][-_MAX_REVIEWS:]
        meta[WORK_ITEM_KEY] = work_item
        task.metadata_json = meta
        self._session.flush()
        return review

    # -------------------------------------------------------------- handoff

    def build_handoff(self, task: TaskModel, *, next_owner: str | None = None) -> dict[str, Any]:
        """Resumo estruturado para quem continua o trabalho, montado só do estado persistido.

        Reaproveita `structured_summary` (arquivos, testes, evidências, problemas) e acrescenta
        origem, próximo responsável, hipóteses do agente e a próxima ação.

        Args:
            task: tarefa que muda de mãos.
            next_owner: papel que assume; por padrão, o revisor do contrato.

        Returns:
            O handoff, com referências às evidências de origem.
        """
        from agent.orchestrator.subtask_summary import structured_summary

        agent = self._agent_for(task.id)
        item = self.assign(task, agent, persist=False)
        summary = structured_summary(self._session, task)
        agent_meta = (agent.metadata_json or {}) if agent is not None else {}
        findings = [f for f in agent_meta.get("findings") or [] if isinstance(f, dict)]
        hypotheses = [str(f.get("text") or "")[:300] for f in findings if f.get("kind") == "hypothesis"]
        discarded = [str(f.get("text") or "")[:300] for f in findings if f.get("kind") == "discarded_hypothesis"]
        evidences = self._evidences(task.id)
        return {
            "task_id": str(task.id),
            "work_item_id": item.get("id"),
            "from_agent_id": str(agent.id) if agent is not None else None,
            "from_role": item["assignment"]["role"],
            "next_owner": next_owner or item["assignment"]["reviewer_role"],
            "objective": task.objective,
            "findings": summary.get("findings") or [],
            "files_examined": summary.get("files_analyzed") or [],
            "files_changed": summary.get("files_changed") or [],
            "decisions": summary.get("decisions") or [],
            "hypotheses": hypotheses,
            "discarded_hypotheses": discarded,
            "problems": summary.get("problems") or [],
            "tests_run": summary.get("tests_run") or [],
            "results": summary.get("result"),
            "evidence_ids": [str(e.id) for e in evidences],
            "limitations": summary.get("risks") or [],
            "pending": summary.get("pending") or [],
            "next_action": (summary.get("next_actions") or [None])[0],
            "created_at": _now(),
        }

    def record_handoff(self, task_id: uuid.UUID, *, next_owner: str | None = None) -> dict[str, Any] | None:
        """Grava o handoff no agente da tarefa (sobrescreve o anterior: vale o estado mais recente).

        Args:
            task_id: tarefa que muda de mãos.
            next_owner: papel que assume.

        Returns:
            O handoff gravado, ou `None` quando a tarefa não tem agente.
        """
        task = self._session.get(TaskModel, task_id)
        agent = self._agent_for(task_id) if task is not None else None
        if task is None or agent is None:
            return None
        handoff = self.build_handoff(task, next_owner=next_owner)
        meta = dict(agent.metadata_json or {})
        previous = meta.get("handoff") or {}
        comparable = {k: v for k, v in handoff.items() if k != "created_at"}
        if {k: v for k, v in previous.items() if k != "created_at"} != comparable:
            meta["handoff"] = handoff
            agent.metadata_json = meta
            self._session.flush()
            return handoff
        return previous

    # ------------------------------------------------------------- portões

    def _evidences(self, task_id: uuid.UUID) -> list[EvidenceModel]:
        """Evidências da tarefa em ordem cronológica."""
        return list(self._session.scalars(
            select(EvidenceModel).where(EvidenceModel.task_id == task_id)
            .order_by(EvidenceModel.created_at, EvidenceModel.id)
        ).all())

    def snapshot(self, task: TaskModel) -> WorkSnapshot:
        """Retrato da tarefa para os portões, lido do banco.

        Args:
            task: tarefa avaliada.

        Returns:
            O `WorkSnapshot` correspondente.
        """
        from agent.orchestrator.requirements import load_requirements, root_of
        from agent.orchestrator.subtask_summary import files_changed_by

        item = self.assign(task, self._agent_for(task.id), persist=False)
        meta = task.metadata_json or {}
        is_root = task.parent_id is None
        try:
            reqs = [str(r.get("description") or "") for r in load_requirements(self._session, root_of(self._session, task))]
        except Exception:  # contrato ilegível não derruba a leitura dos portões
            reqs = []
        children = [c.status for c in self._session.scalars(
            select(TaskModel).where(TaskModel.parent_id == task.id)).all()]
        verification_count = self._session.scalar(
            select(func.count(OperationAttemptModel.id)).where(
                OperationAttemptModel.task_id == task.id,
                OperationAttemptModel.kind == AttemptKind.VERIFICATION.value,
            )
        ) or 0
        return WorkSnapshot(
            status=task.status,
            objective=task.objective or "",
            acceptance=task.acceptance_criteria or "",
            requirements=reqs,
            assignment=item.get("assignment"),
            allowed_files=[str(p) for p in (meta.get("allowed_files") or []) if isinstance(p, str)],
            changed_files=files_changed_by(self._session, task),
            evidences=[{"id": str(e.id), "verifier": e.verifier, "passed": e.passed, "summary": e.summary}
                       for e in self._evidences(task.id)],
            reviews=list(item.get("reviews") or []),
            read_only=bool(meta.get("read_only")),
            is_root=is_root,
            children=children,
            blocked_reason=str(meta.get("blocked_reason") or ""),
            verification_attempts=verification_count,
        )

    def gates(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Portões, etapa do fluxo e avaliação da entrega de uma tarefa.

        Args:
            task_id: tarefa consultada.

        Returns:
            `{"stage", "gates", "evaluation", "out_of_scope", "reviews"}`.

        Raises:
            LookupError: quando a tarefa não existe.
        """
        task = self._task(task_id)
        snap = self.snapshot(task)
        verdicts = evaluate_gates(snap)
        return {
            "task_id": str(task.id),
            "status": task.status,
            "stage": stage_for(snap, verdicts).value,
            "gates": [v.to_dict() for v in verdicts],
            "evaluation": evaluate_delivery(snap, verdicts),
            "out_of_scope": out_of_scope(snap),
            "reviews": snap.reviews,
        }

    def board(self, project_id: uuid.UUID, *, limit: int = 200) -> list[dict[str, Any]]:
        """Quadro do projeto: cada tarefa com etapa, responsável, revisor e portões resumidos.

        Args:
            project_id: projeto consultado.
            limit: máximo de tarefas (as mais recentes).

        Returns:
            Uma linha por tarefa.
        """
        tasks = self._session.scalars(
            select(TaskModel).where(TaskModel.project_id == project_id)
            .order_by(TaskModel.created_at.desc()).limit(limit)
        ).all()
        rows: list[dict[str, Any]] = []
        for task in tasks:
            snap = self.snapshot(task)
            verdicts = evaluate_gates(snap)
            assignment = snap.assignment or {}
            rows.append({
                "task_id": str(task.id),
                "parent_id": str(task.parent_id) if task.parent_id else None,
                "title": task.title,
                "status": task.status,
                "stage": stage_for(snap, verdicts).value,
                "team": assignment.get("team"),
                "role": assignment.get("role"),
                "reviewer_role": assignment.get("reviewer_role"),
                "risk": assignment.get("risk"),
                "gates": {v.id: v.state for v in verdicts},
                "blocking": [b for v in verdicts for b in v.blocking][:5],
            })
        return rows
