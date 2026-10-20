"""
Arquivo: src/agent/orchestrator/global_verify.py
Nome: global_verify.py
Propósito: critérios globais de conclusão.
Responsabilidade: camada de aplicação.
Componentes: requirements_report, unmet_requirements, evaluate_global_acceptance, invalidate_latest, reopen_verification_gaps, correct_requirement_gaps….
Dependências: agent.domain.enums, agent.domain.failures, agent.domain.schemas, agent.orchestrator.consolidation, agent.orchestrator.requirements, agent.persistence.models….
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.failures import Failure, FailureCategory, FailureCause
from agent.domain.schemas import TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.orchestrator.consolidation import (
    children_of,
    collect_evidences,
    inherits_flag,
    verification_evidence_ok,
    verification_spec,
)
from agent.orchestrator.requirements import MANDATORY, load_requirements, requirement_status
from agent.persistence.models import EvidenceModel, TaskModel
from agent.services.task_service import TaskService
from agent.verification.fingerprint import is_current


def _subtree_tasks(session: Session, root_id: uuid.UUID) -> list[TaskModel]:
    """Recolhe a tarefa raiz e todos os seus descendentes.

    Args:
        session: sessão do banco.
        root_id: identificador da raiz da árvore.

    Returns:
        As tarefas que pertencem à subárvore da raiz.

    Observações:
        A varredura é repetida até não encontrar novos filhos, para alcançar a profundidade toda.
    """
    all_tasks = list(session.scalars(select(TaskModel)).all())
    ids = {root_id}
    changed = True
    while changed:
        changed = False
        for t in all_tasks:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True
    return [t for t in all_tasks if t.id in ids]


REQUIREMENT_LABELS = {
    "satisfied": "comprovado",
    "uncovered": "sem etapa responsável",
    "unverified": "concluído sem evidência suficiente",
    "pending": "não executado",
    "failed": "reprovado",
    "blocked": "bloqueado",
    "bloqueado": "bloqueado (declarado)",
    "não_aplicável": "não aplicável",
    "informativo": "informativo",
}
_ACCEPTABLE = {"satisfied", "não_aplicável", "informativo"}


def requirements_report(session: Session, root: TaskModel) -> list[dict]:
    """Estado de cada requisito do objetivo, com rótulo legível, para o aceite e o relatório final."""
    return [
        {
            "id": r["id"],
            "description": r["description"],
            "applicability": r["applicability"],
            "status": r["status"],
            "label": REQUIREMENT_LABELS.get(r["status"], r["status"]),
            "partial": r["partial"],
            "tasks": r["tasks"],
            "evidence_ids": r["evidence_ids"],
        }
        for r in requirement_status(session, root)
    ]


def unmet_requirements(report: list[dict]) -> list[dict]:
    """Filtra do relatório os requisitos que ainda não têm comprovação aceitável.

    Args:
        report: relatório de requisitos do objetivo.

    Returns:
        Os requisitos cujo estado não é comprovado, não aplicável nem informativo.
    """
    return [r for r in report if r["status"] not in _ACCEPTABLE]


def evaluate_global_acceptance(session: Session, root_id: uuid.UUID) -> tuple[bool, str]:
    """Julga se o objetivo inteiro pode ser aceito como cumprido.

    Args:
        session: sessão do banco.
        root_id: identificador da tarefa raiz do objetivo.

    Returns:
        Um par com a decisão e o motivo que a justifica.

    Observações:
        A decisão é conservadora: raiz não concluída, evidência ausente ou desatualizada, consolidação falha ou requisito obrigatório sem comprovação reprovam o aceite.
    """
    root = session.get(TaskModel, root_id)
    if root is None:
        return False, "root ausente"
    if TaskStatus(root.status) not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        return False, "root ainda não concluído"

    for t in _subtree_tasks(session, root_id):
        if verification_spec(t) and TaskStatus(t.status) == TaskStatus.COMPLETED:
            if not verification_evidence_ok(session, t):
                return False, f"evidência ausente ou desatualizada: {t.title}"

    report = root.consolidated_result_json or {}
    if report and report.get("achieved") is False:
        return False, "consolidação do objetivo falhou"

    unmet = unmet_requirements(requirements_report(session, root))
    if unmet:
        listed = ", ".join(f"{r['id']} ({r['label']})" for r in unmet)
        return False, f"requisitos obrigatórios sem comprovação: {listed}"

    return True, "ok"


def _gap_failure(session: Session, task: TaskModel) -> Failure:
    """Classifica por que a evidência da tarefa não serve.

    Args:
        session: sessão do banco.
        task: tarefa cuja evidência foi avaliada.

    Returns:
        A falha recuperável correspondente, distinguindo evidência desatualizada de verificação reprovada.
    """
    evs = collect_evidences(session, task.id)
    last = evs[-1] if evs else None
    detail = (last or {}).get("detail") or {}
    if last and last.get("passed") is True and (detail.get("state") == "desatualizado" or not is_current(detail.get("artifacts"))):
        paths = ", ".join(((detail.get("artifacts") or {}).get("paths") or []))
        return Failure(
            FailureCategory.RECOVERABLE,
            FailureCause.STALE_EVIDENCE,
            f"os arquivos verificados ({paths}) mudaram depois da verificação; refazer com o estado atual",
        )
    return Failure(FailureCategory.RECOVERABLE, FailureCause.VERIFICATION_FAILED, "concluída sem evidência válida")


def invalidate_latest(session: Session, task_id: uuid.UUID, reason: str) -> None:
    """Marca a evidência mais recente como desatualizada (estado, momento e motivo); nunca apaga."""
    row = session.scalars(
        select(EvidenceModel)
        .where(EvidenceModel.task_id == task_id)
        .order_by(EvidenceModel.created_at.desc(), EvidenceModel.id.desc())
    ).first()
    if row is None:
        return
    detail = dict(row.detail_json or {})
    if detail.get("state") == "desatualizado":
        return
    detail.update(
        state="desatualizado",
        previous_state=detail.get("state") or "aprovado",
        invalidated_at=datetime.now(timezone.utc).isoformat(),
        invalidated_reason=reason[:300],
    )
    row.detail_json = detail


def reopen_verification_gaps(session: Session, root_id: uuid.UUID) -> list[uuid.UUID]:
    """Reabre tarefas verificadas cuja evidência mais recente não passou ou ficou desatualizada; o motivo
    entra em `last_failure`/`failures`. Desatualizada volta a VERIFYING: verifica-se o estado atual antes
    de repetir a operação. Sem evidência válida volta a RETRY_PENDING."""
    ts = TaskService(session)
    reopened: list[uuid.UUID] = []
    for t in _subtree_tasks(session, root_id):
        if not verification_spec(t):
            continue
        if TaskStatus(t.status) != TaskStatus.COMPLETED:
            continue
        if verification_evidence_ok(session, t):
            continue
        failure = _gap_failure(session, t)
        if failure.cause == FailureCause.STALE_EVIDENCE:
            invalidate_latest(session, t.id, failure.detail)
        meta = dict(t.metadata_json or {})
        meta["last_failure"] = failure.as_dict()
        meta["failures"] = [*(meta.get("failures") or []), failure.as_dict()][-5:]
        t.metadata_json = meta
        ts.update_status(t.id, TaskStatusUpdate(status=TaskStatus.VERIFYING, reason=failure.detail))
        if failure.cause != FailureCause.STALE_EVIDENCE:
            ts.update_status(
                t.id,
                TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason=failure.detail),
            )
        reopened.append(t.id)
        if t.parent_id:
            parent = ts.get_task(t.parent_id)
            if TaskStatus(parent.status) == TaskStatus.COMPLETED:
                ts.update_status(parent.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                ts.update_status(
                    parent.id,
                    TaskStatusUpdate(status=TaskStatus.PLANNING, reason="reabertura hierárquica"),
                )
    return reopened


def correct_requirement_gaps(session: Session, root: TaskModel) -> list[uuid.UUID]:
    """Correção localizada no aceite global: para cada requisito obrigatório sem etapa responsável ou
    concluído sem evidência, cria uma etapa sob a raiz que cobre só ele (uma vez por requisito) e reabre
    a resposta final para depender dela. Etapas irmãs já comprovadas ficam como estão."""
    kids = children_of(session, root.id)
    tried = {(k.metadata_json or {}).get("requirement_fix") for k in kids}
    targets = [
        r
        for r in requirement_status(session, root)
        if r["status"] in {"uncovered", "unverified"} and r["id"] not in tried
    ]
    if not targets:
        return []
    ts = TaskService(session)
    created: list[uuid.UUID] = []
    inherited = {
        flag: True
        for flag in ("read_only", "protect_tests")
        if inherits_flag(session, root, flag)
    }
    for req in targets:
        unverified = req["status"] == "unverified"
        objective = req["description"]
        if unverified:
            objective = (
                f"{objective}\n\nO trabalho foi dado como feito sem evidência. Verifique o estado atual "
                "(testes, sintaxe, conteúdo dos arquivos) e corrija o que faltar."
            )
        task = ts.create_task(
            root.project_id,
            TaskCreate(
                title=f"{'Comprovar' if unverified else 'Atender'} {req['id']}",
                objective=objective,
                acceptance_criteria=req["criterion"] or req["description"],
                kind=TaskKind.SUBSYSTEM,
                parent_id=root.id,
                metadata={
                    "covers": [req["id"]],
                    "requirement_fix": req["id"],
                    # A etapa de comprovação nasce sob a raiz: herda as restrições do pedido
                    # (comprovar não é alterar; e a régua não muda).
                    **inherited,
                },
            ),
        )
        created.append(task.id)
    final = next(
        (
            k
            for k in kids
            if (k.metadata_json or {}).get("final_answer") and TaskStatus(k.status) != TaskStatus.CANCELLED
        ),
        None,
    )
    if final is not None:
        for task_id in created:
            ts.add_dependency(final.id, TaskDependencyCreate(depends_on_task_id=task_id))
        _reopen(ts, final, "nova etapa de correção de requisito")
    _reopen(ts, root, "requisito obrigatório sem comprovação")
    session.flush()
    return created


def _reopen(ts: TaskService, task: TaskModel, reason: str) -> None:
    """Reabre uma tarefa concluída, devolve-a ao planejamento e registra o motivo.

    Args:
        ts: serviço de tarefas que faz as transições.
        task: tarefa reaberta.
        reason: motivo registrado nas transições.

    Observações:
        Tarefa que não estava concluída é deixada como está: a reabertura só vale para o que já foi aceito.
    """
    if TaskStatus(task.status) == TaskStatus.COMPLETED:
        ts.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING, reason=reason))
        ts.update_status(task.id, TaskStatusUpdate(status=TaskStatus.PLANNING, reason=reason))


def ensure_global_verification_task(
    session: Session,
    project_id: uuid.UUID,
    root: TaskModel,
) -> TaskModel | None:
    """Cria subtarefa de verificação global se o root pedir explicitamente. Ela cobre todos os requisitos
    obrigatórios: integração reprovada impede o aceite mesmo com as etapas aprovadas uma a uma."""
    meta = root.metadata_json or {}
    if not meta.get("global_verification"):
        return None
    kids = children_of(session, root.id)
    if any((k.metadata_json or {}).get("global_verification_step") for k in kids):
        return None
    spec = meta.get("global_verification")
    if not isinstance(spec, dict):
        spec = {"type": "pytest", "path": "."}
    task = TaskService(session).create_task(
        project_id,
        TaskCreate(
            title="Verificação global",
            objective="Validar critérios globais do objetivo",
            kind="operation",
            parent_id=root.id,
            metadata={
                "verification": spec,
                "global_verification_step": True,
                "covers": [r["id"] for r in load_requirements(session, root) if r["applicability"] == MANDATORY],
            },
        ),
    )
    _reopen(TaskService(session), root, "verificação global pendente")
    return task
