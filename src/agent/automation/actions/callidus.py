"""
Arquivo: src/agent/automation/actions/callidus.py
Nome: callidus.py
Propósito: implementar a ação Callidus, que cria (ou retoma) um trabalho do agente.
Responsabilidade: camada de aplicação — execução da automação pelos serviços existentes do Callidus.
Componentes: CallidusActionRunner, TERMINAL_RUN_STATES.
Dependências: agent.automation.actions.base, agent.services.run_service, agent.services.task_service.
Observações: criar o run não é concluir a automação; sem espera, o disparo fica `running` até a reconciliação.

Cria (ou retoma) um trabalho pelos serviços existentes do Callidus.

O caminho é o mesmo de um run disparado pela interface:

1. A tarefa raiz é criada pelo `TaskService` (contrato de tarefa respeitado).
2. O run é criado pelo `RunService` — **com** `root_task_id`, agente na raiz e evento
   de início. Um `ExecutionRunModel` pela metade não existe.
3. O run é entregue ao worker autônomo, que o executa com a máquina de estados e a
   verificação já existentes.

O disparo **não** é considerado concluído porque o run foi criado: quando a ação não
espera o fim, o disparo fica `running` e a reconciliação fecha o estado quando o run
chega a um estado terminal.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any


from agent.automation.actions.base import ActionContext, ActionResult
from agent.automation.contracts import CallidusAction
from agent.automation.enums import ActionKind, ObjectiveMode
from agent.automation.security import redact_evidence
from agent.domain.enums import RunStatus
from agent.domain.schemas import ExecutionRunCreate, TaskCreate
from agent.persistence.models import ExecutionRunModel, TaskModel
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

TERMINAL_RUN_STATES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


class CallidusActionRunner:
    """Ação Callidus.

    Atributos:
        _spec: especificação da ação (objetivo, modelo, espera e modo de objetivo).
    """

    kind = ActionKind.CALLIDUS

    def __init__(self, spec: CallidusAction) -> None:
        """Cria a ação a partir da sua especificação.

        Args:
            spec: especificação da ação.
        """
        self._spec = spec

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Cria a tarefa raiz, inicia o run e o entrega ao worker autônomo.

        Args:
            ctx: contexto da ação, com o destino, as dependências e o evento.

        Returns:
            O resultado da ação, com a evidência do run criado.
        """
        session = ctx.session
        spec = self._spec

        objective = self._resolve_objective(ctx)
        if not objective:
            return ActionResult(
                ok=False,
                error="a automação não tem objetivo definido",
                category="no_objective",
                retryable=False,
            )

        tasks = TaskService(session)
        try:
            task = tasks.create_task(
                ctx.project_id,
                TaskCreate(
                    title=ctx.target.get("name") or "Automação",
                    objective=objective,
                    conversation_id=_uuid_or_none(spec.conversation_id),
                    kind=ctx.target.get("task_kind", "objective"),
                    metadata={
                        "automation_id": str(ctx.automation_id),
                        "firing_id": str(ctx.firing_id),
                        "objective_mode": str(ctx.target.get("objective_mode") or ObjectiveMode.FROZEN),
                    },
                ),
            )
        except LookupError as exc:
            return ActionResult(
                ok=False,
                error=f"não foi possível criar a tarefa raiz: {exc}",
                category="invalid_target",
                retryable=False,
            )

        config: dict[str, Any] = {"autonomous": bool(spec.autonomous)}
        if spec.model_id:
            config["model_id"] = spec.model_id
        if spec.provider:
            config["provider"] = spec.provider

        try:
            run = RunService(session).start_run(
                ctx.project_id,
                ExecutionRunCreate(root_task_id=task.id, config=config),
            )
            session.flush()
        except Exception as exc:  # noqa: BLE001 — erro de contrato precisa virar evidência
            return ActionResult(
                ok=False,
                error=f"não foi possível iniciar a execução: {exc}",
                category="run_creation_failed",
                retryable=False,
                task_id=str(task.id),
                evidence=redact_evidence({"objective": objective, "config": config}),
            )

        evidence = {
            "task_id": str(task.id),
            "run_id": str(run.id),
            "objective": objective,
            "config": config,
        }

        if not spec.wait:
            return ActionResult(
                ok=True,
                summary="execução criada e entregue ao worker autônomo",
                evidence=redact_evidence(evidence),
                run_id=str(run.id),
                task_id=str(task.id),
                finished=False,
            )

        finished = await self._wait_for_run(ctx, str(run.id))
        if finished is None:
            return ActionResult(
                ok=False,
                error="tempo esgotado aguardando a execução",
                category="timeout",
                retryable=True,
                evidence=redact_evidence(evidence),
                run_id=str(run.id),
                task_id=str(task.id),
                finished=False,
            )
        status, report = finished
        ok = status == RunStatus.COMPLETED.value
        evidence = {**evidence, "run_status": status, "report": report}
        return ActionResult(
            ok=ok,
            summary=(
                "execução concluída com aceite"
                if ok
                else f"execução terminou como {status}"
            ),
            evidence=redact_evidence(evidence),
            error=None if ok else f"execução terminou como {status}",
            category=None if ok else "run_failed",
            retryable=False,
            run_id=str(run.id),
            task_id=str(task.id),
            finished=True,
        )

    # ------------------------------------------------------------ objetivo

    def _resolve_objective(self, ctx: ActionContext) -> str | None:
        """Objetivo da execução, conforme a política de versão.

        - `frozen`: o objetivo guardado na aprovação. Alterações posteriores na
          conversa **não** mudam a automação aprovada.
        - `latest`: o objetivo atual da tarefa/conversa ligada — só quando o usuário
          pediu explicitamente.

        Args:
            ctx: contexto da ação, com o objetivo congelado e o modo configurado.

        Returns:
            O objetivo da execução, ou `None` quando não há objetivo definido.
        """
        spec = self._spec
        mode = ctx.target.get("objective_mode") or spec.objective_mode
        frozen = ctx.target.get("objective_json")
        if isinstance(frozen, dict) and frozen.get("objective"):
            return str(frozen["objective"])
        if mode == ObjectiveMode.FROZEN:
            if spec.objective:
                return spec.objective
            return None

        task_id = _uuid_or_none(spec.task_id)
        if task_id is not None:
            task = ctx.session.get(TaskModel, task_id)
            if task is not None and task.objective:
                return task.objective
        if spec.objective:
            return spec.objective
        return None

    # ------------------------------------------------------------ espera

    async def _wait_for_run(
        self, ctx: ActionContext, run_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Espera o run chegar a um estado terminal.

        Args:
            ctx: contexto da ação, com a sessão e o tempo limite.
            run_id: identificador do run a acompanhar.

        Returns:
            Tupla com o estado final e o relatório consolidado, ou `None` em tempo esgotado.
        """
        timeout = float(
            self._spec.wait_timeout_sec
            or self._spec.timeout_sec
            or ctx.timeout_sec
            or 1800.0
        )
        deadline = asyncio.get_running_loop().time() + timeout
        interval = 1.0
        while asyncio.get_running_loop().time() < deadline:
            session = ctx.session
            run = session.get(ExecutionRunModel, uuid.UUID(run_id))
            if run is None:
                return None
            if run.status in TERMINAL_RUN_STATES:
                root = session.get(TaskModel, run.root_task_id)
                report = dict(root.consolidated_result_json or {}) if root else {}
                return run.status, report
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 5.0)
        return None


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    """Converte um texto em UUID, tolerando ausência e valor inválido.

    Args:
        value: valor de entrada.

    Returns:
        O UUID correspondente, ou `None` quando o valor está ausente ou é inválido.
    """
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None
