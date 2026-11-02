"""
Arquivo: src/agent/services/approval_service.py
Nome: approval_service.py
Propósito: aprovação granular de operações arriscadas — pedir, decidir, consumir e auditar.
Responsabilidade: camada de aplicação — liga uma decisão humana a **uma** operação (ferramenta + argumentos + etapa) e retoma a execução que esperava por ela.
Componentes: ApprovalService, operation_key, APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_DENIED, APPROVAL_CONSUMED.
Dependências: agent.domain.enums, agent.domain.schemas, agent.persistence.models, agent.services.run_service, agent.services.task_service, agent.tools.policy.
Observações: a aprovação é de uso único e vale só para a mesma chamada; a flag `approve_risky_tools` do run continua existindo como aprovação ampla explícita.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel, ToolApprovalModel
from agent.tools.policy import redact

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"
APPROVAL_CONSUMED = "consumed"

#: Marca do motivo da pausa de um run que espera por decisão humana.
PAUSE_KIND_APPROVAL = "approval"


def operation_key(tool: str, args: dict[str, Any] | None) -> str:
    """Identidade estável de uma operação: a ferramenta e os argumentos normalizados.

    Args:
        tool: identificador canônico da ferramenta.
        args: argumentos já normalizados pelo registro.

    Returns:
        O hash SHA-256 (hex) da operação; argumentos iguais em outra ordem dão a mesma chave.
    """
    raw = json.dumps({"tool": tool, "args": args or {}}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApprovalService:
    """Pedidos e decisões de aprovação de operações de ferramenta.

    Atributos:
        _session: sessão usada nas leituras e gravações.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    # -- execução ---------------------------------------------------------------

    def check(
        self,
        *,
        tool: str,
        args: dict[str, Any] | None,
        task_id: uuid.UUID | None,
        run_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        risk: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Consulta (e, quando preciso, abre) o pedido de aprovação desta operação.

        Uma aprovação concedida e ainda não usada para a mesma etapa e a mesma operação é
        **consumida** aqui e libera a chamada. Sem decisão, o pedido fica pendente (um por
        operação — repetir a chamada não abre outro). Uma negação continua valendo.

        Args:
            tool: ferramenta pedida.
            args: argumentos normalizados da chamada.
            task_id: etapa que pediu a operação.
            run_id: execução em curso.
            project_id: projeto da execução.
            risk: nível de risco declarado pela ferramenta.
            reason: justificativa da política para exigir aprovação.

        Returns:
            Dicionário com `approved` (bool), `approval_id`, `status` do pedido e, quando o
            pedido acabou de ser aberto, `created`.
        """
        key = operation_key(tool, args)
        rows = list(
            self._session.scalars(
                select(ToolApprovalModel)
                .where(ToolApprovalModel.task_id == task_id, ToolApprovalModel.operation_key == key)
                .order_by(ToolApprovalModel.created_at.desc())
            ).all()
        )
        granted = next((row for row in rows if row.status == APPROVAL_APPROVED), None)
        if granted is not None:
            granted.status = APPROVAL_CONSUMED
            granted.consumed_at = datetime.now(UTC)
            self._session.flush()
            return {"approved": True, "approval_id": str(granted.id), "status": APPROVAL_CONSUMED}
        open_row = next((row for row in rows if row.status in {APPROVAL_PENDING, APPROVAL_DENIED}), None)
        if open_row is not None:
            return {"approved": False, "approval_id": str(open_row.id), "status": open_row.status}
        row = ToolApprovalModel(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            tool=tool,
            operation_key=key,
            args_preview_json=_preview(args),
            risk=risk,
            reason=(reason or "")[:500] or None,
            status=APPROVAL_PENDING,
        )
        self._session.add(row)
        self._session.flush()
        return {"approved": False, "approval_id": str(row.id), "status": APPROVAL_PENDING, "created": True}

    # -- decisão ----------------------------------------------------------------

    def get(self, approval_id: uuid.UUID) -> ToolApprovalModel:
        """Lê um pedido de aprovação.

        Args:
            approval_id: identificador do pedido.

        Returns:
            O pedido.

        Raises:
            LookupError: quando o pedido não existe.
        """
        row = self._session.get(ToolApprovalModel, approval_id)
        if row is None:
            raise LookupError(str(approval_id))
        return row

    def list_for_run(self, run_id: uuid.UUID) -> list[ToolApprovalModel]:
        """Lista os pedidos de aprovação de uma execução, do mais antigo ao mais novo.

        Args:
            run_id: execução consultada.

        Returns:
            Os pedidos da execução.
        """
        return list(
            self._session.scalars(
                select(ToolApprovalModel)
                .where(ToolApprovalModel.run_id == run_id)
                .order_by(ToolApprovalModel.created_at)
            ).all()
        )

    def decide(self, approval_id: uuid.UUID, *, approve: bool, note: str | None = None) -> ToolApprovalModel:
        """Registra a decisão humana e devolve a execução ao ponto em que parou.

        Aprovada: a etapa que esperava sai de BLOCKED para PLANNING (o orquestrador a
        promove e reexecuta a mesma chamada, que consome a aprovação). Negada: a etapa
        continua bloqueada com o motivo, e o replanejamento decide o caminho. Em ambos os
        casos o run pausado à espera de decisão é retomado quando não resta outro pedido
        pendente nele.

        Args:
            approval_id: pedido decidido.
            approve: `True` para aprovar, `False` para negar.
            note: observação opcional de quem decidiu.

        Returns:
            O pedido com a decisão gravada.

        Raises:
            LookupError: quando o pedido não existe.
            ValueError: quando o pedido já foi decidido.
        """
        row = self.get(approval_id)
        if row.status != APPROVAL_PENDING:
            raise ValueError(f"pedido de aprovação já decidido ({row.status})")
        row.status = APPROVAL_APPROVED if approve else APPROVAL_DENIED
        row.decision_note = (note or "")[:500] or None
        row.decided_at = datetime.now(UTC)
        task = self._session.get(TaskModel, row.task_id) if row.task_id else None
        if task is not None:
            self._release_task(task, row, approve)
        self._session.add(
            EventLogModel(
                project_id=row.project_id,
                run_id=row.run_id,
                task_id=row.task_id,
                event_type="approval.decided",
                payload_json={"approval_id": str(row.id), "status": row.status, "tool": row.tool},
            )
        )
        self._session.flush()
        self._resume_if_waiting(row.run_id)
        return row

    def _release_task(self, task: TaskModel, row: ToolApprovalModel, approve: bool) -> None:
        """Tira a etapa da espera conforme a decisão (só se ela espera **este** pedido)."""
        from agent.services.task_service import TaskService

        meta = dict(task.metadata_json or {})
        if meta.get("awaiting_approval") != str(row.id):
            return
        meta.pop("awaiting_approval", None)
        if approve:
            task.metadata_json = meta
            if task.status == TaskStatus.BLOCKED.value:
                TaskService(self._session).update_status(
                    task.id, TaskStatusUpdate(status=TaskStatus.PLANNING, reason=f"aprovação concedida: {row.tool}")
                )
        else:
            meta["approval_denied"] = {"approval_id": str(row.id), "tool": row.tool, "note": row.decision_note}
            meta["blocked_reason"] = f"operação negada por quem aprova: {row.tool}"
            task.metadata_json = meta

    def _resume_if_waiting(self, run_id: uuid.UUID | None) -> None:
        """Retoma o run pausado por aprovação quando nenhum pedido dele continua pendente."""
        if run_id is None:
            return
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None or run.status != RunStatus.PAUSED.value:
            return
        root = self._session.get(TaskModel, run.root_task_id)
        pause = (root.metadata_json or {}).get("pause") if root is not None else None
        if not isinstance(pause, dict) or pause.get("kind") != PAUSE_KIND_APPROVAL:
            return
        still_pending = self._session.scalar(
            select(ToolApprovalModel.id).where(
                ToolApprovalModel.run_id == run_id, ToolApprovalModel.status == APPROVAL_PENDING
            )
        )
        if still_pending is not None:
            return
        from agent.services.run_service import RunService

        RunService(self._session).resume_run(run_id)


def _preview(args: dict[str, Any] | None) -> dict[str, Any]:
    """Prévia auditável dos argumentos: segredos redigidos e textos longos cortados."""
    out: dict[str, Any] = {}
    for key, value in (redact(dict(args or {}))).items():
        if isinstance(value, str) and len(value) > 400:
            value = value[:400] + "…"
        out[str(key)] = value
    return out


def approval_view(row: ToolApprovalModel) -> dict[str, Any]:
    """Serializa um pedido de aprovação para a API.

    Args:
        row: pedido persistido.

    Returns:
        Dicionário com identificação, operação, risco, estado e datas.
    """
    return {
        "id": str(row.id),
        "run_id": str(row.run_id) if row.run_id else None,
        "task_id": str(row.task_id) if row.task_id else None,
        "tool": row.tool,
        "operation_key": row.operation_key,
        "args": row.args_preview_json or {},
        "risk": row.risk,
        "reason": row.reason,
        "status": row.status,
        "note": row.decision_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
    }
