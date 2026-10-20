# src/agent/services/attempt_service.py — tentativas e detecção de loops
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import AttemptKind
from agent.domain.failures import Failure
from agent.persistence.models import EventLogModel, OperationAttemptModel


class AttemptService:
    def __init__(self, session: Session, max_attempts: int = 8) -> None:
        self._session = session
        self._max_attempts = max_attempts

    def record(
        self,
        *,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
        kind: AttemptKind,
        provider: str | None,
        request: dict | None,
        response: dict | None,
        success: bool,
        error: str | None = None,
        project_id: uuid.UUID | None = None,
        failure: Failure | None = None,
    ) -> OperationAttemptModel:
        if failure is not None and not error:
            error = f"[{failure.category.value}/{failure.cause.value}] {failure.detail}"[:2000]
        row = OperationAttemptModel(
            run_id=run_id,
            task_id=task_id,
            kind=kind.value,
            provider=provider,
            request_json=request,
            response_json=response,
            success=success,
            error_message=error,
        )
        self._session.add(row)
        self._session.flush()
        if project_id:
            payload: dict = {"kind": kind.value, "success": success}
            if failure is not None:
                payload["failure"] = failure.as_dict()
            self._session.add(
                EventLogModel(
                    project_id=project_id,
                    run_id=run_id,
                    task_id=task_id,
                    event_type="attempt.recorded",
                    payload_json=payload,
                )
            )
        return row

    def count_attempts(self, task_id: uuid.UUID, kind: AttemptKind = AttemptKind.MODEL) -> int:
        """Quantas tentativas a tarefa consumiu.

        Conta as tentativas de operação: cada resposta final do modelo é uma tentativa. As
        iterações internas do ciclo de ferramentas (o modelo inspecionando antes de responder)
        são chamadas de modelo, mas não tentativas — contá-las esgotaria o orçamento da tarefa
        sem que a estratégia tivesse sido testada de novo.
        """
        stmt = select(OperationAttemptModel).where(
            OperationAttemptModel.task_id == task_id,
            OperationAttemptModel.kind == kind.value,
        )
        rows = list(self._session.scalars(stmt).all())
        if kind == AttemptKind.MODEL:
            return sum(1 for row in rows if not (row.request_json or {}).get("iteration_fp"))
        return len(rows)

    def count_model_calls(self, task_id: uuid.UUID) -> int:
        """Chamadas ao modelo da tarefa, incluindo as iterações do ciclo de ferramentas."""
        stmt = select(OperationAttemptModel).where(
            OperationAttemptModel.task_id == task_id,
            OperationAttemptModel.kind == AttemptKind.MODEL.value,
        )
        return len(list(self._session.scalars(stmt).all()))

    def count_tool_calls(self, task_id: uuid.UUID) -> int:
        stmt = select(OperationAttemptModel).where(
            OperationAttemptModel.task_id == task_id,
            OperationAttemptModel.kind == AttemptKind.TOOL.value,
        )
        return len(list(self._session.scalars(stmt).all()))

    def attempts_exhausted(self, task_id: uuid.UUID) -> bool:
        return self.count_attempts(task_id) >= self._max_attempts

    def repeated_output_detected(
        self,
        task_id: uuid.UUID,
        output_fingerprint: str,
        window: int = 3,
        kind: AttemptKind | None = None,
    ) -> bool:
        stmt = (
            select(OperationAttemptModel)
            .where(OperationAttemptModel.task_id == task_id)
            .order_by(OperationAttemptModel.created_at.desc())
            .limit(window)
        )
        if kind is not None:
            stmt = stmt.where(OperationAttemptModel.kind == kind.value)
        rows = list(self._session.scalars(stmt).all())
        if len(rows) < window:
            return False
        hashes = []
        for r in rows:
            raw = str(r.response_json or r.error_message or "")
            hashes.append(hashlib.sha256(raw.encode()).hexdigest()[:16])
        return len(set(hashes)) == 1 and hashes[0] == output_fingerprint

    def prompt_already_sent(self, task_id: uuid.UUID, prompt_fp: str) -> bool:
        """O mesmo prompt já foi enviado ao modelo nesta tarefa (impressão em `request_json.prompt_fp`)."""
        stmt = select(OperationAttemptModel.request_json).where(
            OperationAttemptModel.task_id == task_id,
            OperationAttemptModel.kind == AttemptKind.MODEL.value,
        )
        return any((req or {}).get("prompt_fp") == prompt_fp for req in self._session.scalars(stmt))

    @staticmethod
    def fingerprint(data: dict | str) -> str:
        text = data if isinstance(data, str) else str(data)
        return hashlib.sha256(text.encode()).hexdigest()[:16]
