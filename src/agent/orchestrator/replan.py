"""
Arquivo: src/agent/orchestrator/replan.py
Nome: replan.py
Propósito: revisar o plano quando uma etapa para no meio.
Responsabilidade: camada de aplicação.
Componentes: ReplanDecision, replan_decision, replan_under, replan_parent.
Dependências: agent.domain.enums, agent.domain.failures, agent.domain.schemas, agent.observability, agent.orchestrator.consolidation, agent.orchestrator.decomposition….
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.

O replanejamento aqui **não** é uma nova tentativa com o contador zerado: ele escolhe a próxima
abordagem da lista de alternativas da falha e a leva junto, declarada, para a etapa nova. Sem
abordagem nova sobrando, o replanejamento é recusado e a etapa precisa de ação de fora.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.failures import Failure, FailureCategory
from agent.domain.schemas import TaskStatusUpdate
from agent.observability import emit
from agent.orchestrator.approach import approach_of
from agent.orchestrator.consolidation import children_of, pending_reason, superseded
from agent.orchestrator.decomposition import (
    DecompositionResult,
    SubTaskSpec,
    apply_decomposition,
)
from agent.orchestrator.requirements import effective_covers, normalize_covers
from agent.orchestrator.stagnation import normalize_error
from agent.persistence.models import TaskModel
from agent.services.task_service import TaskService

REPLAN_BUDGET = 3
_STOP = {TaskStatus.BLOCKED.value, TaskStatus.FAILED.value}
_CANCEL = {
    TaskStatus.PENDING.value,
    TaskStatus.READY.value,
    TaskStatus.PLANNING.value,
    TaskStatus.RETRY_PENDING.value,
}
_NEEDS_OUTSIDE_ACTION = {FailureCategory.CONFIGURATION, FailureCategory.EXTERNAL_UNAVAILABLE}


@dataclass(frozen=True)
class ReplanDecision:
    """Decisão do orquestrador sobre replanejar uma etapa parada.

    Atributos:
        replan: indica se um plano novo deve ser feito.
        reason: justificativa da decisão, gravada na tarefa pai.
    """

    replan: bool
    reason: str = ""


def replan_decision(parent_meta: dict, stopped: TaskModel, completed: int) -> ReplanDecision:
    """Política: replanejar só quando um plano novo pode resolver e há orçamento e progresso.

    - Configuração e falta externa (aprovação, servidor, verificação manual) pedem ação de fora: não replaneja.
    - O orçamento `REPLAN_BUDGET` é da linhagem inteira (o nó replanejado herda a contagem).
    - Sem etapa nova concluída desde o último replanejamento e com o mesmo motivo (comparado normalizado:
      números, ids e aspas não contam), o plano novo não ajudou.
    - Sem alternativa de abordagem sobrando, replanejar de novo seria repetir a mesma operação com
      o contador zerado: é recusado, e a etapa precisa de ação de fora.
    """
    failure = Failure.from_dict((stopped.metadata_json or {}).get("last_failure"))
    if failure is not None and failure.category in _NEEDS_OUTSIDE_ACTION:
        return ReplanDecision(False, f"precisa de ação externa ({failure.category.value}): {failure.detail[:200]}")
    approach = approach_of(stopped)
    if approach.get("exhausted"):
        return ReplanDecision(False, "não há outra abordagem disponível para esta falha")
    if int(parent_meta.get("replan_count") or 0) >= REPLAN_BUDGET:
        return ReplanDecision(False, f"limite de {REPLAN_BUDGET} replanejamentos atingido")
    history = parent_meta.get("replan_history") or []
    if history:
        last = history[-1]
        same = normalize_error(str(last.get("reason") or "")) == normalize_error(pending_reason(stopped))
        if completed <= int(last.get("completed") or 0) and same:
            return ReplanDecision(False, "o replanejamento anterior não trouxe progresso")
    return ReplanDecision(True)

def replan_under(session: Session, root_id: uuid.UUID) -> dict | None:
    """Se algum filho parou, revisa o pai (conforme a política) e deixa o plano novo seguir."""
    kids = children_of(session, root_id)
    parents = [session.get(TaskModel, root_id)]
    seen = {root_id}
    pending = list(kids)
    while pending:
        current = pending.pop(0)
        if current.id in seen:
            continue
        seen.add(current.id)
        parents.append(current)
        pending.extend(children_of(session, current.id))
    for parent in parents:
        if parent is None:
            continue
        revised = replan_parent(session, parent)
        if revised:
            return revised
    return None


def _carried_covers(session: Session, kids: list[TaskModel], stopped: TaskModel) -> list[dict] | None:
    """Requisitos que a etapa parada e as irmãs ainda não feitas cobriam passam para o plano corrigido,
    para o replanejamento não perder requisito. `None` quando o plano não declara cobertura (implícita)."""
    if not any(normalize_covers((k.metadata_json or {}).get("covers")) is not None for k in kids):
        return None
    pending = [stopped] + [k for k in kids if k.status in _CANCEL and k.id != stopped.id]
    merged: dict[str, dict] = {}
    for kid in pending:
        for cover in effective_covers(session, kid):
            current = merged.get(cover["req"])
            if current is None or (current["partial"] and not cover["partial"]):
                merged[cover["req"]] = cover
    return list(merged.values())


def replan_parent(session: Session, parent: TaskModel) -> dict | None:
    """Refaz o plano de uma tarefa cujo filho parou, quando a política permite.

    Args:
        session: sessão do banco.
        parent: tarefa cujo plano pode ser refeito.

    Returns:
        O resumo do replanejamento quando ele acontece, ou `None` quando não há o que refazer ou a política recusa.

    Observações:
        As etapas concluídas permanecem; as canceladas são marcadas como substituídas e os requisitos cobertos por elas passam para o plano corrigido.
    """
    meta = dict(parent.metadata_json or {})
    kids = children_of(session, parent.id)
    stopped = next((kid for kid in kids if kid.status in _STOP and not superseded(kid)), None)
    if stopped is None:
        return None
    if any((kid.metadata_json or {}).get("replan") and kid.status not in {*_STOP, TaskStatus.CANCELLED.value, TaskStatus.COMPLETED.value} for kid in kids):
        return None
    done = [kid.title for kid in kids if kid.status == TaskStatus.COMPLETED.value]
    reason = pending_reason(stopped)
    decision = replan_decision(meta, stopped, len(done))
    if not decision.replan:
        if meta.get("replan_refused") != decision.reason:
            meta["replan_refused"] = decision.reason
            parent.metadata_json = meta
            session.flush()
        return None

    tasks = TaskService(session)
    carried = _carried_covers(session, kids, stopped)
    cancelled: list[str] = []
    for kid in kids:
        if kid.id == stopped.id or children_of(session, kid.id):
            continue
        if kid.status in _CANCEL:
            # A etapa cancelada foi **substituída** pelo replanejamento: o marcação importa,
            # senão a consolidação entende "trabalho não feito" e bloqueia o pai, mesmo
            # com o plano novo já concluído.
            kid.metadata_json = {**(kid.metadata_json or {}), "superseded_by_replan": True}
            tasks.update_status(
                kid.id,
                TaskStatusUpdate(status=TaskStatus.CANCELLED, reason="plano revisado"),
            )
            cancelled.append(kid.title)
    stopped.metadata_json = {**(stopped.metadata_json or {}), "superseded_by_replan": True}
    if stopped.status == TaskStatus.BLOCKED.value:
        tasks.update_status(stopped.id, TaskStatusUpdate(status=TaskStatus.CANCELLED, reason="substituída pelo replanejamento"))

    count = int(meta.get("replan_count") or 0) + 1
    approach = approach_of(stopped)
    change = str(approach.get("next_change") or "").strip()
    hypothesis = str(approach.get("hypothesis") or "").strip()
    success = str(approach.get("success_criterion") or "").strip()
    failure_criterion = str(approach.get("failure_criterion") or "").strip()
    tried = approach.get("tried") or []
    lines = [
        f"Replanejar o que falta de «{parent.title}». ",
        f"Já concluído: {', '.join(done) or 'nada'}. Não refazer isso. ",
        f"Parou em «{stopped.title}»: {reason[:240]}.",
    ]
    if hypothesis:
        lines.append(f"Hipótese da falha: {hypothesis[:240]}.")
    if tried:
        last = tried[-1]
        lines.append(f"O que foi tentado: {last.get('what') or ''!s} → {str(last.get('result') or '')[:200]}.")
    if change:
        # A abordagem nova vai escrita no pedido: o modelo recebe a alternativa concreta, não
        # a instrução genérica de "use outra abordagem".
        lines.append(f"Agora é preciso fazer diferente: {change}.")
    else:
        lines.append("Use outra abordagem para essa parte.")
    if success:
        lines.append(f"Sucesso: {success}.")
    if failure_criterion:
        lines.append(f"Se acontecer isto, a hipótese também está errada: {failure_criterion}.")
    lines.append(f"Objetivo original: {parent.objective[:500]}")
    objective = " ".join(lines)
    carried_approach = {
        **approach,
        "current_change": change,
        "changed_at": approach.get("changed_at"),
    }
    plan = DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Ver o que ainda falta",
                objective=objective,
                metadata={
                    "tool": "list_dir",
                    "tool_args": {"path": "."},
                    "atomic": True,
                    "replan": True,
                    **({"covers": []} if carried is not None else {}),
                },
            ),
            SubTaskSpec(
                title="Seguir com o plano corrigido",
                objective=objective,
                kind=TaskKind.SUBSYSTEM,
                metadata={
                    "replan": True,
                    "replan_count": count,
                    # A etapa nova nasce com a abordagem declarada: o contador de repetição
                    # reconhece a mudança material e a memória viaja com o trabalho.
                    "approach": carried_approach,
                    **({"covers": carried} if carried is not None else {}),
                },
                depends_on_indices=[0],
            ),
        ]
    )
    apply_decomposition(session, parent.project_id, parent.id, plan)
    meta["replan_count"] = count
    meta["last_replan_reason"] = reason[:240]
    meta["replan_history"] = [*(meta.get("replan_history") or []), {"completed": len(done), "reason": reason}][-REPLAN_BUDGET:]
    meta.pop("replan_refused", None)
    parent.metadata_json = meta
    session.flush()
    emit(
        "task.replanned",
        {
            "reason": reason[:500],
            "stopped_at": stopped.title,
            "stopped_task_id": str(stopped.id),
            "count": count,
            "kept": done,
            "cancelled": cancelled,
            "tasks": [
                {"id": str(k.id), "title": k.title}
                for k in children_of(session, parent.id)
                if (k.metadata_json or {}).get("replan") and k.status == TaskStatus.PENDING.value
            ],
        },
        task_id=parent.id,
    )
    return {
        "action": "replanned",
        "task_id": str(parent.id),
        "stopped_at": stopped.title,
        "cancelled": cancelled,
        "thought": f"Replanejei depois de «{stopped.title}». O que já passou fica como está.",
    }
