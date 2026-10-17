# src/agent/services/contract_service.py — contratos explícitos entre tarefas
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.persistence.models import TaskContractModel, TaskModel


class ContractService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        task_id: uuid.UUID,
        *,
        inputs: dict | None = None,
        outputs: dict | None = None,
        invariants: list | None = None,
        acceptance: dict | None = None,
    ) -> TaskContractModel:
        task = self._session.get(TaskModel, task_id)
        if task is None:
            raise LookupError(str(task_id))
        row = self._session.scalar(select(TaskContractModel).where(TaskContractModel.task_id == task_id))
        if row is None:
            row = TaskContractModel(task_id=task_id)
            self._session.add(row)
        if inputs is not None:
            row.inputs_json = inputs
        if outputs is not None:
            row.outputs_json = outputs
        if invariants is not None:
            row.invariants_json = invariants
        if acceptance is not None:
            row.acceptance_json = acceptance
        self._session.flush()
        return row

    def validate_for_run(self, task_id: uuid.UUID) -> tuple[bool, list[str]]:
        """Verifica se contrato mínimo existe quando a tarefa exige integração."""
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return False, ["tarefa inexistente"]
        meta = task.metadata_json or {}
        if not meta.get("requires_contract"):
            return True, []
        row = self._session.scalar(select(TaskContractModel).where(TaskContractModel.task_id == task_id))
        if row is None or not row.outputs_json:
            return False, ["contrato ausente ou saídas não definidas"]
        return True, []
