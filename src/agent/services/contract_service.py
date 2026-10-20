"""
Arquivo: src/agent/services/contract_service.py
Nome: contract_service.py
Propósito: manter os contratos explícitos entre tarefas (entradas, saídas, invariantes e aceite).
Responsabilidade: camada de aplicação — gravação, validação e impacto dos contratos das tarefas.
Componentes: ContractService.
Dependências: agent.persistence.models, sqlalchemy.
Observações: o contrato de uma tarefa é único; gravar de novo atualiza apenas os campos informados.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.persistence.models import KgNodeModel, TaskContractModel, TaskModel


class ContractService:
    """Serviço dos contratos das tarefas, gravados em `task_contracts`.

    Atributos:
        _session: sessão usada nas leituras e gravações.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
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
        """Grava ou atualiza o contrato de uma tarefa.

        Args:
            task_id: identificador da tarefa dona do contrato.
            inputs: entradas esperadas.
            outputs: saídas prometidas.
            invariants: invariantes que a tarefa deve respeitar.
            acceptance: critérios de aceite.

        Returns:
            O contrato gravado.

        Raises:
            LookupError: quando a tarefa não existe.
        """
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
        """Verifica se contrato mínimo existe quando a tarefa exige integração.

        Args:
            task_id: identificador da tarefa validada.

        Returns:
            Tupla com o resultado da validação e a lista de problemas encontrados.
        """
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

    def get(self, task_id: uuid.UUID) -> TaskContractModel | None:
        """Contrato de uma tarefa.

        Args:
            task_id: identificador da tarefa.

        Returns:
            O contrato, ou `None` quando a tarefa ainda não tem contrato.
        """
        return self._session.scalar(select(TaskContractModel).where(TaskContractModel.task_id == task_id))

    def file_refs_from_contract(self, row: TaskContractModel) -> list[str]:
        """Arquivos citados no contrato da tarefa.

        Args:
            row: contrato consultado.

        Returns:
            A lista de caminhos citados nas entradas, saídas e aceite.
        """
        refs: list[str] = []
        for blob in (row.outputs_json, row.inputs_json, row.acceptance_json):
            if not isinstance(blob, dict):
                continue
            for key in ("files", "paths", "modules"):
                val = blob.get(key)
                if isinstance(val, list):
                    refs.extend(str(x) for x in val)
                elif isinstance(val, str):
                    refs.append(val)
        return refs

    def find_impacted_tasks(self, project_id: uuid.UUID, file_refs: list[str]) -> list[uuid.UUID]:
        """Tarefas do projeto afetadas pelos arquivos citados no contrato.

        Args:
            project_id: projeto varrido.
            file_refs: caminhos citados no contrato.

        Returns:
            Os identificadores das tarefas impactadas.
        """
        if not file_refs:
            return []
        stmt = select(TaskModel).where(TaskModel.project_id == project_id)
        tasks = list(self._session.scalars(stmt).all())
        impacted: set[uuid.UUID] = set()
        needles = [f.lower() for f in file_refs]
        for t in tasks:
            hay = f"{t.objective} {t.title} {t.metadata_json}".lower()
            if any(n in hay for n in needles):
                impacted.add(t.id)
        nodes = list(
            self._session.scalars(select(KgNodeModel).where(KgNodeModel.project_id == project_id)).all()
        )
        for ref in file_refs:
            q = ref.lower()
            for n in nodes:
                if q in n.ref.lower() or q in n.label.lower():
                    for t in tasks:
                        if q in t.objective.lower():
                            impacted.add(t.id)
        return list(impacted)

    def upsert_with_impact(
        self,
        task_id: uuid.UUID,
        *,
        inputs: dict | None = None,
        outputs: dict | None = None,
        invariants: list | None = None,
        acceptance: dict | None = None,
    ) -> dict:
        """Grava o contrato e devolve as tarefas impactadas pelos arquivos citados.

        Args:
            task_id: identificador da tarefa dona do contrato.
            inputs: entradas esperadas.
            outputs: saídas prometidas.
            invariants: invariantes que a tarefa deve respeitar.
            acceptance: critérios de aceite.

        Returns:
            Um dicionário com o identificador do contrato e as tarefas impactadas.

        Raises:
            LookupError: quando a tarefa não existe.
        """
        task = self._session.get(TaskModel, task_id)
        if task is None:
            raise LookupError(str(task_id))
        row = self.upsert(
            task_id,
            inputs=inputs,
            outputs=outputs,
            invariants=invariants,
            acceptance=acceptance,
        )
        refs = self.file_refs_from_contract(row)
        impacted = self.find_impacted_tasks(task.project_id, refs)
        return {"contract_id": str(row.id), "impacted_task_ids": [str(x) for x in impacted]}
