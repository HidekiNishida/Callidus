"""
Arquivo: src/agent/orchestrator/ledger.py
Nome: ledger.py
Propósito: persistir cada inferência e derivar os totais da execução a partir desses registros.
Responsabilidade: camada de aplicação — livro-razão do consumo, idempotente e imediato.
Componentes: bind_snapshot, record_inference, reconcile_task_usage, run_spend, consistency_report.
Dependências: agent.orchestrator.inference_usage, agent.memory.operational, agent.persistence.models, sqlalchemy.
Observações: gravar de novo a mesma chave não soma a chamada outra vez.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.memory.operational import remember_detail, upsert_operational
from agent.orchestrator.inference_usage import fold_usage, spend_of
from agent.persistence.models import InferenceRecordModel, TaskModel

_SNAPSHOT: ContextVar[str | None] = ContextVar("inference_snapshot", default=None)


@contextmanager
def bind_snapshot(snapshot_id: str | None) -> Iterator[None]:
    """Associa as inferências seguintes ao snapshot de contexto já gravado.

    Args:
        snapshot_id: identificador do snapshot, ou `None` para limpar.

    Yields:
        Nada. O identificador fica disponível para `record_inference`.
    """
    token = _SNAPSHOT.set(snapshot_id)
    try:
        yield
    finally:
        _SNAPSHOT.reset(token)


def _uuid(value: Any) -> uuid.UUID | None:
    """Converte um identificador solto em UUID, ou devolve `None`.

    Args:
        value: texto, UUID ou vazio.

    Returns:
        O UUID, ou `None` quando o valor não é um identificador.
    """
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def record_inference(session: Session, *, idempotency_key: str, **fields: Any) -> InferenceRecordModel:
    """Grava uma inferência. A mesma chave devolve o registro que já existe.

    Args:
        session: sessão do banco.
        idempotency_key: identidade estável da chamada (o `output_id` do evento).
        **fields: colunas do registro. Tokens ausentes devem chegar como `None`.

    Returns:
        O registro persistido, novo ou já existente.

    Observações:
        O flush acontece na hora. Repetir a chave, inclusive depois de uma falha
        de recuperação, não soma os tokens de novo.
    """
    existing = session.scalar(
        select(InferenceRecordModel).where(InferenceRecordModel.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    snapshot_id = fields.pop("context_snapshot_id", None) or _SNAPSHOT.get()
    row = InferenceRecordModel(
        idempotency_key=idempotency_key,
        context_snapshot_id=_uuid(snapshot_id),
        run_id=_uuid(fields.pop("run_id", None)),
        task_id=_uuid(fields.pop("task_id", None)),
        project_id=_uuid(fields.pop("project_id", None)),
        **fields,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        found = session.scalar(
            select(InferenceRecordModel).where(InferenceRecordModel.idempotency_key == idempotency_key)
        )
        if found is not None:
            return found
        raise
    task = session.get(TaskModel, row.task_id) if row.task_id else None
    if task is not None:
        note = f"{row.purpose}: {row.status}"
        if row.measurement == "unavailable":
            note += " (uso do provedor indisponível)"
        upsert_operational(session, task, status_note=note)
        reconcile_task_usage(session, task)
    return row


def records_for(
    session: Session,
    *,
    run_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> list[InferenceRecordModel]:
    """Lista os registros de uma execução ou de uma tarefa, na ordem em que aconteceram.

    Args:
        session: sessão do banco.
        run_id: filtra pela execução.
        task_id: filtra pela tarefa.

    Returns:
        Os registros, do mais antigo para o mais novo.
    """
    stmt = select(InferenceRecordModel)
    if run_id is not None:
        stmt = stmt.where(InferenceRecordModel.run_id == run_id)
    if task_id is not None:
        stmt = stmt.where(InferenceRecordModel.task_id == task_id)
    stmt = stmt.order_by(InferenceRecordModel.created_at, InferenceRecordModel.id)
    return list(session.scalars(stmt).all())


def run_spend(session: Session, run_id: uuid.UUID) -> tuple[int | None, str]:
    """Gasto contabilizado da execução, para o limite acumulado.

    Args:
        session: sessão do banco.
        run_id: execução consultada.

    Returns:
        O gasto e a qualidade. Sem registros, o valor é `None` e a qualidade é `unavailable`.
    """
    rows = records_for(session, run_id=run_id)
    if not rows:
        return None, "unavailable"
    folded = fold_usage(rows)
    spend = folded["spend"]
    return spend["value"], spend["measurement"]


def reconcile_task_usage(session: Session, task: TaskModel) -> bool:
    """Substitui o uso acumulado da tarefa pela soma dos registros dela.

    Args:
        session: sessão do banco.
        task: tarefa a reconciliar.

    Returns:
        `True` quando havia registros e o metadado foi reescrito a partir deles.

    Observações:
        Não soma o metadado antigo por cima: isso duplicaria a última chamada.
        Uso anterior à existência do livro-razão permanece só enquanto a tarefa
        ainda não tem nenhum registro.
    """
    rows = records_for(session, task_id=task.id)
    if not rows:
        return False
    folded = fold_usage(rows)
    prompt = folded["prompt"]["value"]
    completion = folded["completion"]["value"]
    known_total = None
    if prompt is not None or completion is not None:
        known_total = int(prompt or 0) + int(completion or 0)
        if folded["prompt"]["missing"] or folded["completion"]["missing"]:
            measurement = "partial"
        else:
            measurement = "exact"
    else:
        measurement = folded["spend"]["measurement"]
        known_total = folded["spend"]["value"]
    meta = dict(task.metadata_json or {})
    meta["usage"] = {
        "prompt": prompt,
        "completion": completion,
        "total": known_total,
        "reasoning": folded["reasoning"]["value"],
        "cache_read": folded["cache_read"]["value"],
        "cache_write": folded["cache_write"]["value"],
        "calls": folded["calls"],
        "failed": folded["failed"],
        "measurement": measurement,
        "prompt_missing": folded["prompt"]["missing"],
        "completion_missing": folded["completion"]["missing"],
    }
    task.metadata_json = meta
    return True


def consistency_report(session: Session, run_id: uuid.UUID) -> dict[str, Any]:
    """Compara a soma dos registros com a soma dos metadados das tarefas.

    Args:
        session: sessão do banco.
        run_id: execução conferida.

    Returns:
        Os dois totais e se batem. Tarefa sem registro não entra na soma do metadado
        quando o metadado é só estimativa antiga sem `measurement`.
    """
    rows = records_for(session, run_id=run_id)
    folded = fold_usage(rows)
    task_ids = {row.task_id for row in rows if row.task_id is not None}
    meta_total = 0
    meta_calls = 0
    for task_id in task_ids:
        task = session.get(TaskModel, task_id)
        usage = ((task.metadata_json or {}).get("usage") if task is not None else None) or {}
        if usage.get("total") is not None:
            meta_total += int(usage.get("total") or 0)
        meta_calls += int(usage.get("calls") or 0)
    ledger_total = folded["spend"]["value"]
    return {
        "calls": folded["calls"],
        "ledger_spend": ledger_total,
        "ledger_measurement": folded["spend"]["measurement"],
        "metadata_total": meta_total,
        "metadata_calls": meta_calls,
        "match": ledger_total == meta_total and folded["calls"] == meta_calls,
    }


def task_reported_total(session: Session, task_id: uuid.UUID) -> tuple[int | None, str]:
    """Total informado para a tarefa, sem cair na estimativa de janela.

    Args:
        session: sessão do banco.
        task_id: tarefa consultada.

    Returns:
        O total e a qualidade. Sem registro, devolve o metadado legado quando ele
        já tem `measurement`; caso contrário, indisponível.
    """
    rows = records_for(session, task_id=task_id)
    if rows:
        folded = fold_usage(rows)
        return folded["spend"]["value"], folded["spend"]["measurement"]
    task = session.get(TaskModel, task_id)
    usage = ((task.metadata_json or {}).get("usage") if task is not None else None) or {}
    if usage.get("measurement") and usage.get("total") is not None:
        return int(usage["total"]), str(usage["measurement"])
    if usage.get("total"):
        return int(usage["total"]), "partial"
    return None, "unavailable"


def note_budget_pause(session: Session, task: TaskModel | None, reason: str) -> None:
    """Registra a pausa por orçamento como detalhe recuperável da tarefa.

    Args:
        session: sessão do banco.
        task: tarefa interrompida; pode ser a raiz.
        reason: motivo da pausa.
    """
    if task is None:
        return
    upsert_operational(session, task, status_note=reason)
    remember_detail(
        session,
        task,
        title="Pausa por orçamento",
        body=reason,
        facts={"state": "paused", "subject": "orcamento"},
    )


def iter_spend(rows: list[InferenceRecordModel]) -> list[tuple[InferenceRecordModel, int, str]]:
    """Associa cada registro ao gasto considerado no orçamento.

    Args:
        rows: registros na ordem cronológica.

    Returns:
        Trios com o registro, o gasto e a qualidade.
    """
    return [(row, *spend_of(row)) for row in rows]
