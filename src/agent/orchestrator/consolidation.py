# src/agent/orchestrator/consolidation.py — consolidação bottom-up
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.persistence.models import EvidenceModel, TaskDependencyModel, TaskModel
from agent.services.task_service import TaskService
from agent.services.agent_service import AgentNotFoundError, AgentService
from agent.verification.fingerprint import is_current


def verification_spec(task: TaskModel) -> dict | None:
    """Verificação declarada ou, para escrita sem declaração, a implícita que já rodou."""
    meta = task.metadata_json or {}
    spec = meta.get("verification") or meta.get("implicit_verification")
    return spec if isinstance(spec, dict) and spec else None


def latest_verification_failed(session: Session, task: TaskModel) -> bool:
    """A verificação mais recente desta etapa reprovou (não é ausência de evidência)."""
    evs = collect_evidences(session, task.id)
    return bool(evs) and evs[-1].get("passed") is False


def verification_evidence_ok(session: Session, task: TaskModel) -> bool:
    """Vale só a evidência mais recente: precisa ter passado e os arquivos que ela avaliou não podem ter
    mudado desde então (evidência desatualizada não conta, mas fica gravada)."""
    if not verification_spec(task):
        return True
    evs = collect_evidences(session, task.id)
    if not evs or evs[-1].get("passed") is not True:
        return False
    detail = evs[-1].get("detail") or {}
    return detail.get("state") != "desatualizado" and is_current(detail.get("artifacts"))


def superseded(task: TaskModel) -> bool:
    """Etapa parada que um replanejamento já substituiu: não conta mais como pendência."""
    return bool((task.metadata_json or {}).get("superseded_by_replan"))


def is_optional(task: TaskModel) -> bool:
    """Subtarefa opcional: se falhar, não impede o avanço do pai (gera conclusão com ressalvas)."""
    meta = task.metadata_json or {}
    return bool(meta.get("optional") or meta.get("severity") == "optional")


def inherits_read_only(session: Session, task: TaskModel | None) -> bool:
    """A tarefa (ou um de seus ancestrais) é de um pedido que proíbe alterar arquivos.

    A restrição é do pedido, então ela **desce** pela árvore: uma etapa criada para
    comprovar um requisito de um pedido somente-leitura também não pode escrever.
    """
    return inherits_flag(session, task, "read_only")


def inherits_flag(session: Session, task: TaskModel | None, flag: str) -> bool:
    """A tarefa (ou um de seus ancestrais) carrega a marca `flag`."""
    current = task
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if (current.metadata_json or {}).get(flag):
            return True
        if not current.parent_id:
            return False
        current = session.get(TaskModel, current.parent_id)
    return False


# Cancelamentos que **não** deixam trabalho pendente: a etapa foi substituída por um
# replanejamento, ou o próprio plano foi corrigido (duplicata removida, plano inválido).
_EXPECTED_CANCEL = {"duplicate", "invalid_plan", "superseded"}


def cancelled_expected(task: TaskModel) -> bool:
    """Cancelamento previsto: outra etapa assume o trabalho, o pai pode seguir."""
    meta = task.metadata_json or {}
    if superseded(task):
        return True
    return str(meta.get("cancelled_reason") or "") in _EXPECTED_CANCEL


def settled(task: TaskModel) -> bool:
    """Filho que não impede o pai de seguir: concluído, cancelado ou falho já substituído/opcional."""
    status = TaskStatus(task.status)
    return status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} or (
        status == TaskStatus.FAILED and (superseded(task) or is_optional(task))
    )


def children_of(session: Session, parent_id: uuid.UUID) -> list[TaskModel]:
    stmt = select(TaskModel).where(TaskModel.parent_id == parent_id)
    return list(session.scalars(stmt).all())


def dependencies_of(session: Session, task_id: uuid.UUID) -> list[TaskModel]:
    """Tarefas das quais esta depende, pela aresta `task_dependencies`."""
    stmt = (
        select(TaskModel)
        .join(TaskDependencyModel, TaskDependencyModel.depends_on_task_id == TaskModel.id)
        .where(TaskDependencyModel.task_id == task_id)
    )
    return list(session.scalars(stmt).all())


def stages_outcome(session: Session, task: TaskModel) -> tuple[bool | None, str, dict[str, Any]]:
    """Conferência das etapas anteriores: o verificador `stages` não é mais uma aprovação automática.

    Ele confirma que as etapas das quais a tarefa declara dependência **concluíram com evidência
    válida**. Sem dependência declarada não há o que confirmar: o resultado é inconclusivo — um
    "sim" sem conteúdo seria um verde falso.
    """
    deps = dependencies_of(session, task.id)
    if not deps:
        return None, "a etapa não declara dependência: não há o que conferir", {"type": "stages", "dependencies": []}
    pending: list[str] = []
    detail: dict[str, Any] = {"type": "stages", "dependencies": []}
    for dep in deps:
        status = TaskStatus(dep.status)
        ok = status == TaskStatus.COMPLETED and verification_evidence_ok(session, dep)
        detail["dependencies"].append({"task_id": str(dep.id), "title": dep.title, "status": dep.status, "ok": ok})
        if not ok:
            pending.append(f"{dep.title} ({dep.status})")
    if pending:
        return False, "etapas anteriores não concluídas: " + ", ".join(pending), detail
    return True, f"{len(deps)} etapa(s) anterior(es) concluída(s) com evidência", detail


_TO_VERIFYING: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.PLANNING: [TaskStatus.VERIFYING],
    TaskStatus.READY: [TaskStatus.RUNNING, TaskStatus.VERIFYING],
    TaskStatus.RUNNING: [TaskStatus.VERIFYING],
    TaskStatus.VERIFYING: [],
}


def _walk(ts: TaskService, task_id: uuid.UUID, path: list[TaskStatus], reason: str | None = None) -> None:
    for status in path:
        ts.update_status(task_id, TaskStatusUpdate(status=status, reason=reason))


def consolidate_parent(session: Session, parent_id: uuid.UUID) -> dict[str, Any] | None:
    """Junta o resultado dos filhos no pai. O pai só conclui se todo filho não cancelado concluiu com
    evidência (filho substituído por replanejamento não conta; filho opcional falho gera conclusão com ressalvas).
    Filho concluído sem evidência é reaberto e o pai volta a PLANNING. Filho obrigatório que falhou deixa o
    pai como está, com `achieved=False` e a lista `pending`: replanejar ou parar é decisão do runner."""
    ts = TaskService(session)
    parent = ts.get_task(parent_id)
    kids = children_of(session, parent_id)
    if not kids:
        return None
    if any(TaskStatus(c.status) not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED} for c in kids):
        return None

    summaries = []
    gaps: list[TaskModel] = []
    failed_critical: list[TaskModel] = []
    failed_optional: list[TaskModel] = []
    cancelled: list[TaskModel] = []
    for c in kids:
        ev_ok = verification_evidence_ok(session, c)
        if c.status == TaskStatus.COMPLETED.value and not ev_ok:
            # "Sem evidência" reabre a etapa para verificar de novo. "Verificação reprovada"
            # **não** reabre: quem reprovou foi o código, não a etapa — reescrever a resposta
            # final não muda a medição, e a etapa de resposta final jamais é reaberta por
            # isso (a reprovação é reportada no rodapé da resposta).
            if not latest_verification_failed(session, c) and not (c.metadata_json or {}).get("final_answer"):
                gaps.append(c)
        elif c.status == TaskStatus.CANCELLED.value and not cancelled_expected(c):
            # Etapa cancelada sem previsão: o trabalho dela não foi feito. Ignorar isso
            # deixaria o pai concluir como se o plano inteiro tivesse sido cumprido.
            cancelled.append(c)
        elif c.status == TaskStatus.FAILED.value and not superseded(c):
            if is_optional(c):
                failed_optional.append(c)
            else:
                failed_critical.append(c)
        summaries.append(
            {
                "task_id": str(c.id),
                "title": c.title,
                "evidence_ok": ev_ok,
                "optional": is_optional(c),
                "status": c.status,
                "result": c.consolidated_result_json or {"status": c.status},
            }
        )
    achieved = not gaps and not failed_critical and not cancelled
    with_caveats = bool(failed_optional)
    report: dict[str, Any] = {
        "achieved": achieved,
        "with_caveats": with_caveats,
        "caveats": [
            {"task_id": str(c.id), "title": c.title, "reason": "subtarefa opcional falhou"}
            for c in failed_optional
        ],
        "children": summaries,
        "evidences": collect_evidences(session, parent_id),
        "pending": [
            {"task_id": str(c.id), "title": c.title, "status": c.status, "reason": pending_reason(c)}
            for c in [*gaps, *failed_critical, *cancelled]
        ],
    }
    for child in kids:
        meta = child.metadata_json or {}
        result = child.consolidated_result_json or {}
        if meta.get("final_answer") and result.get("markdown"):
            report["final_answer"] = result["markdown"]
            report["sources"] = result.get("sources") or []
    parent.consolidated_result_json = report
    # O que o filho produziu vira descoberta persistida do agente dele: é isso que
    # permite ao pai consultar o filho depois, sem reexecutar o trabalho.
    agents = AgentService(session)
    for child in kids:
        try:
            agents.record_task_result(child.id)
        except AgentNotFoundError:  # pragma: no cover - tarefa sem agente é normal
            continue
    if with_caveats:
        parent.metadata_json = {**(parent.metadata_json or {}), "completed_with_caveats": True}
    current = TaskStatus(parent.status)
    if current not in _TO_VERIFYING:
        return report
    if report["achieved"]:
        _walk(ts, parent_id, [*_TO_VERIFYING[current], TaskStatus.COMPLETED])
        return report
    if gaps:
        for c in gaps:
            _walk(ts, c.id, [TaskStatus.VERIFYING, TaskStatus.RETRY_PENDING], "evidência insuficiente")
        if current != TaskStatus.PLANNING:
            _walk(ts, parent_id, [*_TO_VERIFYING[current], TaskStatus.PLANNING], "filhos sem evidência")
    return report


def pending_reason(task: TaskModel) -> str:
    """Por que a tarefa não concluiu: última falha categorizada, motivo do bloqueio ou o status."""
    meta = task.metadata_json or {}
    failure = meta.get("last_failure") or {}
    return str(failure.get("detail") or meta.get("blocked_reason") or task.status)[:300]


def collect_evidences(session: Session, task_id: uuid.UUID) -> list[dict[str, Any]]:
    stmt = (
        select(EvidenceModel)
        .where(EvidenceModel.task_id == task_id)
        .order_by(EvidenceModel.created_at, EvidenceModel.id)
    )
    rows = list(session.scalars(stmt).all())
    return [
        {
            "verifier": r.verifier,
            "passed": r.passed,
            "summary": r.summary,
            "detail": r.detail_json,
        }
        for r in rows
    ]
