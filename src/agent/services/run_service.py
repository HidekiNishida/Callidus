"""
Arquivo: src/agent/services/run_service.py
Nome: run_service.py
Propósito: manter as execuções (runs) do projeto: início, pausa, retomada e cancelamento.
Responsabilidade: camada de aplicação — ciclo de vida dos runs e registro dos fatos correspondentes.
Componentes: RunService.
Dependências: agent.domain.enums, agent.domain.schemas, agent.persistence.models, agent.services.agent_service.
Observações: retomar um run não refaz o que já foi comprovado nem zera o consumo. O teto de tokens só cresce com autorização explícita.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, TaskStatusUpdate
from agent.persistence.models import EventLogModel, ExecutionRunModel, TaskModel
from agent.services.agent_service import AgentService


class RunService:
    """Ciclo de vida das execuções de um projeto.

    Atributos:
        _session: sessão usada nas leituras, gravações e no registro de eventos.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    def start_run(self, project_id: uuid.UUID, data: ExecutionRunCreate) -> ExecutionRunModel:
        """Inicia um run a partir da tarefa raiz.

        Args:
            project_id: projeto dono do run.
            data: tarefa raiz e configuração do run.

        Returns:
            O run criado, já com o agente lógico da raiz e o fato `run.started` registrado.

        Raises:
            LookupError: quando a tarefa raiz não pertence ao projeto.
        """
        task = self._session.get(TaskModel, data.root_task_id)
        if task is None or task.project_id != project_id:
            raise LookupError("Tarefa raiz inválida")

        config = dict(data.config or {})
        meta = dict(task.metadata_json or {})
        if config.get("model_id"):
            meta["model_id"] = config["model_id"]
            if config.get("provider"):
                meta["provider"] = config["provider"]
            task.metadata_json = meta
        run = ExecutionRunModel(
            project_id=project_id,
            root_task_id=data.root_task_id,
            status=RunStatus.ACTIVE.value,
            config_json=data.config,
        )
        self._session.add(run)
        self._session.flush()
        self._session.add(
            EventLogModel(
                project_id=project_id,
                run_id=run.id,
                task_id=task.id,
                event_type="run.started",
                payload_json={"root_task_id": str(task.id)},
            )
        )
        # O run começa com um agente lógico na raiz: é quem delega e quem recebe as
        # respostas dos filhos.
        AgentService(self._session).ensure_agent(task.id)
        return run

    def list_runs(self, project_id: uuid.UUID) -> list[ExecutionRunModel]:
        """Runs de um projeto, do mais recente para o mais antigo.

        Args:
            project_id: projeto consultado.

        Returns:
            A lista de runs do projeto.
        """
        stmt = (
            select(ExecutionRunModel)
            .where(ExecutionRunModel.project_id == project_id)
            .order_by(ExecutionRunModel.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def pause_run(self, run_id: uuid.UUID) -> ExecutionRunModel:
        """Pausa um run em andamento.

        Args:
            run_id: identificador do run.

        Returns:
            O run pausado.

        Raises:
            LookupError: quando o run não existe.
        """
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        run.status = RunStatus.PAUSED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                event_type="run.paused",
                payload_json={},
            )
        )
        return run

    def resume_run(self, run_id: uuid.UUID, *, retry_blocked: bool = False) -> ExecutionRunModel:
        """Retoma um run pausado sem refazer o que foi comprovado: volta a ACTIVE, o motivo da pausa vai para
        o histórico `pauses` da raiz e os limites recomeçam a contar do evento `run.resumed`. Com
        `retry_blocked`, etapas bloqueadas voltam a PLANNING (depois de corrigida a causa de fora).

        Args:
            run_id: identificador do run pausado.
            retry_blocked: quando `True`, as etapas bloqueadas voltam a `PLANNING`.

        Returns:
            O run retomado.

        Raises:
            LookupError: quando o run não existe.
            ValueError: quando o run não está pausado.
        """
        from agent.services.task_service import TaskService

        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        if run.status != RunStatus.PAUSED.value:
            raise ValueError(f"run não está pausado ({run.status})")
        root = self._session.get(TaskModel, run.root_task_id)
        retried: list[str] = []
        pause = None
        if root is not None:
            meta = dict(root.metadata_json or {})
            pause = meta.pop("pause", None)
            if pause:
                meta["pauses"] = [*(meta.get("pauses") or []), pause][-10:]
            root.metadata_json = meta
            report = dict(root.consolidated_result_json or {})
            if report.pop("paused", None) is not None:
                report.pop("final_answer", None)
                report.pop("achieved", None)
                root.consolidated_result_json = report or None
            if retry_blocked:
                tasks = TaskService(self._session)
                for task in self._session.scalars(select(TaskModel).where(TaskModel.project_id == run.project_id)).all():
                    if task.status == TaskStatus.BLOCKED.value and self._under(task, root.id):
                        tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.PLANNING, reason="retomada"))
                        retried.append(str(task.id))
        run.status = RunStatus.ACTIVE.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=run.root_task_id,
                event_type="run.resumed",
                payload_json={
                    "pause": pause,
                    "retried": retried,
                    # O consumo acumulado viaja com a retomada: ela concede cota nova, mas
                    # o que já foi gasto continua contando, e a auditoria mostra por quê.
                    "usage": self._usage(run),
                },
            )
        )
        self._session.flush()
        return run

    def _usage(self, run: ExecutionRunModel) -> dict[str, Any]:
        """Consumo acumulado do run até este ponto.

        Args:
            run: run consultado.

        Returns:
            O consumo por indicador, ou um dicionário vazio quando o cálculo falha.
        """
        try:
            from agent.orchestrator.stagnation import usage_since

            return usage_since(self._session, run)
        except Exception:  # noqa: BLE001 — a auditoria não pode impedir a retomada
            return {}

    def _under(self, task: TaskModel, root_id: uuid.UUID) -> bool:
        """Indica se uma tarefa está na subárvore de outra.

        Args:
            task: tarefa consultada.
            root_id: identificador da possível raiz.

        Returns:
            `True` quando a tarefa é a raiz ou está abaixo dela.
        """
        seen: set[uuid.UUID] = set()
        current: TaskModel | None = task
        while current is not None and current.id not in seen:
            if current.id == root_id:
                return True
            seen.add(current.id)
            current = self._session.get(TaskModel, current.parent_id) if current.parent_id else None
        return False

    def cancel_run(self, run_id: uuid.UUID) -> ExecutionRunModel:
        """Cancela um run em andamento.

        Args:
            run_id: identificador do run.

        Returns:
            O run cancelado.

        Raises:
            LookupError: quando o run não existe.
        """
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        run.status = RunStatus.CANCELLED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                event_type="run.cancelled",
                payload_json={},
            )
        )
        return run
