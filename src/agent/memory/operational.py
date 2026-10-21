"""
Arquivo: src/agent/memory/operational.py
Nome: operational.py
Propósito: guardar o estado da tarefa fora da janela do modelo e devolvê-lo sob demanda.
Responsabilidade: camada de aplicação — três níveis de memória da tarefa e o resumo que o pai recebe.
Componentes: upsert_operational, remember_detail, remember_artifact, recall, render_for_prompt, child_summary.
Dependências: agent.domain.enums, agent.persistence.models, sqlalchemy.
Observações: o prompt recebe o resumo operacional; detalhe e artefato ficam para consulta.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.persistence.models import MemoryRecordModel, TaskModel

_LEVEL1_CHARS = 1000


def _clip(text: str | None, limit: int) -> str:
    """Corta um texto longo deixando o tamanho original visível.

    Args:
        text: texto de origem.
        limit: máximo de caracteres do trecho devolvido.

    Returns:
        O texto inteiro quando cabe; senão, o começo e a contagem original.
    """
    raw = " ".join((text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def level1_payload(task: TaskModel, *, status_note: str = "") -> dict[str, Any]:
    """Monta o resumo operacional a partir do que a tarefa já persistiu.

    Args:
        task: tarefa dona do resumo.
        status_note: observação curta do último passo, quando houver.

    Returns:
        O dicionário do nível 1. Não inclui histórico de mensagens nem logs.
    """
    meta = task.metadata_json or {}
    failures = list(meta.get("failures") or [])
    last = failures[-1] if failures else {}
    inspection = meta.get("inspection") if isinstance(meta.get("inspection"), list) else []
    files = []
    for item in inspection:
        if isinstance(item, dict) and item.get("path"):
            files.append(str(item.get("path")))
    disposition = meta.get("disposition") if isinstance(meta.get("disposition"), dict) else {}
    return {
        "level": 1,
        "task_id": str(task.id),
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "objective": _clip(task.objective, 400),
        "acceptance": _clip(task.acceptance_criteria, 300),
        "status": task.status,
        "next_action": _clip(disposition.get("reason") or status_note, 240),
        "decisions": _clip(str(meta.get("approach") or ""), 240),
        "files": files[:8],
        "last_error": _clip(str(last.get("detail") or ""), 240),
        "status_note": _clip(status_note, 200),
    }


def render_level1(payload: dict[str, Any]) -> str:
    """Formata o nível 1 num bloco curto o bastante para a retomada.

    Args:
        payload: resumo estruturado.

    Returns:
        O texto do resumo, limitado a mil caracteres.
    """
    files = ", ".join(payload.get("files") or []) or "(nenhum arquivo registrado)"
    lines = [
        f"Objetivo: {payload.get('objective') or ''}",
        f"Aceite: {payload.get('acceptance') or '(não declarado)'}",
        f"Estado: {payload.get('status') or ''}",
        f"Próximo passo: {payload.get('next_action') or '(seguir o objetivo)'}",
        f"Decisões: {payload.get('decisions') or '(nenhuma registrada)'}",
        f"Arquivos: {files}",
        f"Último erro: {payload.get('last_error') or '(nenhum)'}",
    ]
    if payload.get("status_note"):
        lines.append(f"Nota: {payload['status_note']}")
    lines.append(f"ref: task:{payload.get('task_id')}")
    return _clip("\n".join(lines), _LEVEL1_CHARS)


def upsert_operational(session: Session, task: TaskModel, *, status_note: str = "") -> MemoryRecordModel:
    """Grava ou atualiza o resumo operacional da tarefa.

    Args:
        session: sessão do banco.
        task: tarefa cujo estado deve continuar fora do prompt.
        status_note: o que acabou de acontecer, em uma frase.

    Returns:
        O registro de memória de nível 1.

    Observações:
        Atualizar o mesmo registro evita uma memória nova a cada inferência.
    """
    payload = level1_payload(task, status_note=status_note)
    text = render_level1(payload)
    existing = session.scalar(
        select(MemoryRecordModel)
        .where(
            MemoryRecordModel.task_id == task.id,
            MemoryRecordModel.kind == MemoryKind.OPERATIONAL.value,
        )
        .order_by(MemoryRecordModel.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        existing.content = text
        existing.summary = _clip(text, 320)
        existing.outline_json = payload
        existing.title = f"Estado de {task.title}"[:500]
        existing.version = int(existing.version or 1) + 1
        return existing
    row = MemoryRecordModel(
        project_id=task.project_id,
        conversation_id=task.conversation_id,
        branch_id=task.branch_id,
        task_id=task.id,
        kind=MemoryKind.OPERATIONAL.value,
        title=f"Estado de {task.title}"[:500],
        content=text,
        summary=_clip(text, 320),
        outline_json=payload,
        source_refs_json=[f"task:{task.id}"],
    )
    session.add(row)
    session.flush()
    return row


def remember_detail(
    session: Session,
    task: TaskModel,
    *,
    title: str,
    body: str,
    facts: dict[str, Any] | None = None,
) -> MemoryRecordModel:
    """Guarda um detalhe recuperável, que não entra inteiro no próximo prompt.

    Args:
        session: sessão do banco.
        task: tarefa dona do detalhe.
        title: assunto do detalhe.
        body: texto do detalhe.
        facts: marcas para a busca (arquivo, símbolo, estado).

    Returns:
        O registro de nível 2.
    """
    row = MemoryRecordModel(
        project_id=task.project_id,
        conversation_id=task.conversation_id,
        branch_id=task.branch_id,
        task_id=task.id,
        kind=MemoryKind.TASK_DETAIL.value,
        title=title[:500],
        content=body,
        summary=_clip(body, 320),
        outline_json={"level": 2, **(facts or {})},
        source_refs_json=[f"task:{task.id}"],
    )
    session.add(row)
    session.flush()
    return row


def remember_artifact(
    session: Session,
    task: TaskModel,
    *,
    title: str,
    ref: str,
    summary: str,
) -> MemoryRecordModel:
    """Guarda a referência de um artefato grande, não o conteúdo integral.

    Args:
        session: sessão do banco.
        task: tarefa dona do artefato.
        title: nome curto do artefato.
        ref: identificador para buscar o original (snapshot, tentativa, arquivo).
        summary: diagnóstico conciso.

    Returns:
        O registro de nível 3.
    """
    row = MemoryRecordModel(
        project_id=task.project_id,
        conversation_id=task.conversation_id,
        branch_id=task.branch_id,
        task_id=task.id,
        kind=MemoryKind.ARTIFACT.value,
        title=title[:500],
        content=f"{summary}\nref: {ref}",
        summary=_clip(summary, 320),
        outline_json={"level": 3, "ref": ref},
        source_refs_json=[ref],
    )
    session.add(row)
    session.flush()
    return row


def render_for_prompt(session: Session, task: TaskModel) -> str:
    """Devolve só o nível 1 da tarefa, para a retomada e para a próxima inferência.

    Args:
        session: sessão do banco.
        task: tarefa em execução.

    Returns:
        O resumo persistido, ou um resumo montado na hora quando ainda não há registro.
    """
    row = session.scalar(
        select(MemoryRecordModel)
        .where(
            MemoryRecordModel.task_id == task.id,
            MemoryRecordModel.kind == MemoryKind.OPERATIONAL.value,
        )
        .order_by(MemoryRecordModel.created_at.desc())
        .limit(1)
    )
    if row is not None and (row.content or "").strip():
        return _clip(row.content, _LEVEL1_CHARS)
    return render_level1(level1_payload(task))


def child_summary(session: Session, task: TaskModel) -> str:
    """Resumo que o pai recebe de uma subtarefa. Não inclui o histórico dela.

    Args:
        session: sessão do banco.
        task: subtarefa já executada ou em curso.

    Returns:
        Algumas linhas com resultado, aceite e a referência para consultar o resto.
    """
    operational = session.scalar(
        select(MemoryRecordModel)
        .where(
            MemoryRecordModel.task_id == task.id,
            MemoryRecordModel.kind == MemoryKind.OPERATIONAL.value,
        )
        .order_by(MemoryRecordModel.created_at.desc())
        .limit(1)
    )
    result = task.consolidated_result_json if isinstance(task.consolidated_result_json, dict) else {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    piece = ""
    for key in ("summary", "stdout", "content", "markdown"):
        if isinstance(inner, dict) and isinstance(inner.get(key), str) and inner.get(key).strip():
            piece = str(inner.get(key))
            break
    if not piece and result:
        piece = str({key: result.get(key) for key in list(result)[:4]})
    lines = [f"- {task.title} [{task.status}]"]
    if operational is not None and operational.summary:
        lines.append(f"  estado: {_clip(operational.summary, 280)}")
        lines.append(f"  ref: memory:{operational.id}")
    else:
        if task.acceptance_criteria:
            lines.append(f"  aceite: {_clip(task.acceptance_criteria, 180)}")
        lines.append(f"  ref: task:{task.id}")
    if piece:
        lines.append(f"  resultado: {_clip(piece, 280)}")
    elif operational is None:
        lines.append("  resultado: (sem resultado consolidado)")
    return "\n".join(lines)


def recall(
    session: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    parent_task_id: uuid.UUID | None = None,
    kind: str | None = None,
    text: str | None = None,
    file: str | None = None,
    state: str | None = None,
    limit: int = 20,
) -> list[MemoryRecordModel]:
    """Busca memória por tarefa, assunto, arquivo, tipo ou estado.

    Args:
        session: sessão do banco.
        project_id: projeto dono dos registros.
        task_id: restringe a uma tarefa.
        parent_task_id: inclui a tarefa e as filhas diretas.
        kind: tipo do registro (`operational`, `task_detail`, `artifact` ou os anteriores).
        text: trecho procurado no título, no resumo ou no conteúdo.
        file: caminho ou símbolo procurado.
        state: estado guardado no resumo operacional.
        limit: máximo de registros devolvidos.

    Returns:
        Os registros mais recentes que casam com o filtro. A busca é textual no SQLite.
    """
    stmt = select(MemoryRecordModel).where(MemoryRecordModel.project_id == project_id)
    if parent_task_id is not None:
        child_ids = list(
            session.scalars(select(TaskModel.id).where(TaskModel.parent_id == parent_task_id)).all()
        )
        stmt = stmt.where(MemoryRecordModel.task_id.in_([parent_task_id, *child_ids]))
    elif task_id is not None:
        stmt = stmt.where(MemoryRecordModel.task_id == task_id)
    if kind:
        stmt = stmt.where(MemoryRecordModel.kind == kind)
    if state:
        stmt = stmt.where(MemoryRecordModel.content.contains(state))
    needle = (file or text or "").strip()
    if needle:
        stmt = stmt.where(
            or_(
                MemoryRecordModel.title.contains(needle),
                MemoryRecordModel.summary.contains(needle),
                MemoryRecordModel.content.contains(needle),
            )
        )
    stmt = stmt.order_by(MemoryRecordModel.created_at.desc()).limit(max(1, min(limit, 50)))
    return list(session.scalars(stmt).all())
