"""
Arquivo: src/agent/orchestrator/subtask_summary.py
Nome: subtask_summary.py
Propósito: resumo estruturado de uma subtarefa, montado do estado persistido (tentativas, evidências, falhas).
Responsabilidade: camada de aplicação — índice compacto que o pai consulta sem carregar o histórico de inferência do filho.
Componentes: structured_summary, files_changed_by, shared_files.
Dependências: agent.domain.enums, agent.persistence.models, sqlalchemy.
Observações: o resumo não substitui os artefatos: cada item aponta para a tentativa ou a evidência de origem (`attempt:`/`evidence:`).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import AttemptKind, TaskStatus
from agent.persistence.models import EvidenceModel, OperationAttemptModel, TaskModel

#: Ferramentas que só leem: contam como "arquivos analisados".
_READ_TOOLS = frozenset({"read_file", "list_dir", "glob_files", "search_grep", "git_diff"})
#: Ferramentas que alteram o conteúdo de arquivos: contam como "arquivos alterados".
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "move_file", "delete_file"})
_LIMIT = 20


def _paths(request: dict[str, Any] | None) -> list[str]:
    """Caminhos citados nos argumentos de uma chamada de ferramenta."""
    out: list[str] = []
    for key in ("path", "to", "dest", "source", "from"):
        value = (request or {}).get(key)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    return out


def _attempts(session: Session, task_id: uuid.UUID) -> list[OperationAttemptModel]:
    """Tentativas registradas da etapa, da mais antiga para a mais recente."""
    return list(
        session.scalars(
            select(OperationAttemptModel)
            .where(OperationAttemptModel.task_id == task_id)
            .order_by(OperationAttemptModel.created_at, OperationAttemptModel.id)
        ).all()
    )


def _written_paths(attempt: OperationAttemptModel) -> list[str]:
    """Arquivos alterados por uma tentativa bem-sucedida (ferramenta do plano ou do ciclo do modelo)."""
    if not attempt.success or attempt.kind != AttemptKind.TOOL.value:
        return []
    if str(attempt.provider or "") not in _WRITE_TOOLS:
        return []
    return _paths(attempt.request_json)


def files_changed_by(session: Session, task: TaskModel) -> list[str]:
    """Arquivos que a etapa alterou com sucesso, pela ordem da primeira alteração.

    Args:
        session: sessão do banco.
        task: etapa consultada.

    Returns:
        Os caminhos alterados, sem repetição.
    """
    seen: dict[str, None] = {}
    for attempt in _attempts(session, task.id):
        for path in _written_paths(attempt):
            seen.setdefault(path, None)
    result = task.consolidated_result_json or {}
    write = result.get("write") if isinstance(result.get("write"), dict) else None
    if result.get("model_operation") and write and write.get("success"):
        path = write.get("path")
        if isinstance(path, str) and path:
            seen.setdefault(path, None)
    return list(seen)


def structured_summary(session: Session, task: TaskModel) -> dict[str, Any]:
    """Resumo estruturado e determinístico de uma subtarefa.

    Campos: objetivo, descobertas, arquivos analisados, arquivos alterados, decisões, resultado,
    testes/verificações executados, evidências, problemas, pendências, riscos e próximas ações.
    Tudo vem do estado persistido — nenhuma inferência.

    Args:
        session: sessão do banco.
        task: subtarefa consultada.

    Returns:
        O resumo, com referências (`attempt:<id>`, `evidence:<id>`, `task:<id>`) para o detalhe.
    """
    meta = task.metadata_json or {}
    result = task.consolidated_result_json if isinstance(task.consolidated_result_json, dict) else {}
    attempts = _attempts(session, task.id)
    analyzed: dict[str, None] = {}
    for attempt in attempts:
        if attempt.kind == AttemptKind.TOOL.value and str(attempt.provider or "") in _READ_TOOLS:
            for path in _paths(attempt.request_json):
                analyzed.setdefault(path, None)
    evidences = list(
        session.scalars(
            select(EvidenceModel)
            .where(EvidenceModel.task_id == task.id)
            .order_by(EvidenceModel.created_at, EvidenceModel.id)
        ).all()
    )
    tests_run = [
        {"verifier": a.provider, "passed": (a.response_json or {}).get("passed"), "ref": f"attempt:{a.id}"}
        for a in attempts
        if a.kind == AttemptKind.VERIFICATION.value
    ]
    problems = [
        {"category": f.get("category"), "cause": f.get("cause"), "detail": str(f.get("detail") or "")[:200]}
        for f in (meta.get("failures") or [])
        if isinstance(f, dict)
    ]
    decisions: list[str] = []
    disposition = meta.get("disposition")
    if isinstance(disposition, dict) and disposition.get("reason"):
        decisions.append(f"{disposition.get('action')}: {str(disposition['reason'])[:200]}")
    if meta.get("recursion_guard"):
        decisions.append(f"executar sem dividir: {meta['recursion_guard']}")
    findings: list[str] = []
    for key in ("summary", "markdown"):
        if isinstance(result.get(key), str) and result[key].strip():
            findings.append(result[key].strip()[:400])
            break
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}
    for key in ("summary", "stdout", "content"):
        if isinstance(inner.get(key), str) and inner[key].strip():
            findings.append(inner[key].strip()[:400])
            break
    risks: list[str] = []
    if result.get("verification_absent"):
        risks.append(f"sem verificador automático: {result['verification_absent']}")
    if evidences and evidences[-1].passed is False:
        risks.append(f"última verificação reprovou: {evidences[-1].summary[:160]}")
    if meta.get("rollback_conflicts"):
        risks.append("rollback não aplicado em arquivo alterado por terceiros")
    pending: list[str] = []
    next_actions: list[str] = []
    status = TaskStatus(task.status)
    if status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
        pending.append(str(meta.get("blocked_reason") or f"etapa em {task.status}"))
    if meta.get("awaiting_approval"):
        next_actions.append(f"decidir o pedido de aprovação {meta['awaiting_approval']}")
    recovery = meta.get("verification_recovery")
    if isinstance(recovery, dict) and recovery.get("guidance") and status != TaskStatus.COMPLETED:
        next_actions.append(str(recovery["guidance"])[:240])
    return {
        "task_id": str(task.id),
        "title": task.title,
        "status": task.status,
        "objective": (task.objective or "")[:400],
        "acceptance": task.acceptance_criteria or "",
        "findings": findings,
        "files_analyzed": list(analyzed)[:_LIMIT],
        "files_changed": files_changed_by(session, task)[:_LIMIT],
        "decisions": decisions,
        "result": {
            "verified": result.get("verified"),
            "summary": str(result.get("summary") or "")[:300],
        },
        "tests_run": tests_run[-_LIMIT:],
        "evidences": [
            {"verifier": e.verifier, "passed": e.passed, "summary": e.summary[:200], "ref": f"evidence:{e.id}"}
            for e in evidences[-_LIMIT:]
        ],
        "problems": problems,
        "pending": pending,
        "risks": risks,
        "next_actions": next_actions,
        "ref": f"task:{task.id}",
    }


def shared_files(session: Session, kids: list[TaskModel]) -> list[dict[str, Any]]:
    """Arquivos alterados por mais de uma subtarefa irmã: ponto de conflito a conferir.

    A evidência de cada irmã guarda o hash dos arquivos que ela avaliou; se uma irmã posterior
    reescreveu o arquivo, a evidência anterior deixa de valer (`verification_evidence_ok`) e a
    consolidação reabre a etapa. Esta lista torna o conflito visível no relatório do pai.

    Args:
        session: sessão do banco.
        kids: subtarefas irmãs.

    Returns:
        Uma entrada por arquivo compartilhado, com as subtarefas que o alteraram, na ordem.
    """
    owners: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for kid in kids:
        titles[str(kid.id)] = kid.title
        for path in files_changed_by(session, kid):
            owners.setdefault(path, []).append(str(kid.id))
    return [
        {"path": path, "tasks": ids, "titles": [titles[i] for i in ids]}
        for path, ids in owners.items()
        if len(ids) > 1
    ]
