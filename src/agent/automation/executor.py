"""
Arquivo: src/agent/automation/executor.py
Nome: executor.py
Propósito: transformar um disparo registrado em trabalho executado e reconciliar o estado.
Responsabilidade: camada de aplicação — execução da ação, política de recuperação e fechamento do disparo.
Componentes: AutomationExecutor, ExecutionOutcome, TERMINAL_RUN_STATES.
Dependências: agent.automation.actions, agent.automation.dependencies, agent.automation.security, agent.persistence.models.
Observações: registrar o disparo não é concluir a automação; a reconciliação fecha o estado do run.

O executor transforma um disparo registrado em trabalho executado.

Ordem: dependências → ação → evidência → estado.

- Dependência crítica indisponível: o disparo vai para `waiting_dependency`, a
  tentativa é reagendada e **nenhuma inferência é consumida** para o trabalho
  impossível.
- Ação que termina com erro retentável: nova tentativa com backoff, até o limite.
- Ação Callidus entregue ao worker: o disparo fica `running` e a **reconciliação**
  fecha o estado quando o run chega a um estado terminal. Registrar o disparo não é
  concluir a automação.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.automation.actions import ActionContext, build_action
from agent.automation.contracts import (
    DependencySpec,
    PermissionSpec,
    RecoveryPolicy,
    parse_action,
)
from agent.automation.dependencies import DependencyResolver
from agent.automation.enums import FiringState, TargetKind
from agent.automation.security import redact_evidence
from agent.config import Settings, get_settings
from agent.domain.enums import RunStatus
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    EventLogModel,
    ExecutionRunModel,
    ProjectModel,
    ProjectRemoteModel,
)

TERMINAL_RUN_STATES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


@dataclass
class ExecutionOutcome:
    """Desfecho da execução de um disparo.

    Atributos:
        firing_id: identificador do disparo executado.
        state: estado final do disparo.
        ok: indica se a execução foi bem-sucedida.
        detail: resumo do desfecho.
        retry_at: instante da próxima tentativa, quando houve reagendamento.
    """

    firing_id: uuid.UUID
    state: str
    ok: bool
    detail: str = ""
    retry_at: datetime | None = None


class AutomationExecutor:
    """Executa disparos de automação.

    Atributos:
        _session: sessão usada nas leituras, gravações e no registro de eventos.
        _settings: configurações do processo.
    """

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        """Cria o executor ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
            settings: configurações a usar; quando ausentes, são lidas do ambiente.
        """
        self._session = session
        self._settings = settings or get_settings()

    # ------------------------------------------------------------ contexto

    def _target_info(self, automation: AutomationModel) -> dict[str, Any]:
        """Resolve o destino da automação: local ou remoto, com suas permissões.

        Args:
            automation: automação a executar.

        Returns:
            O dicionário de destino entregue à ação.
        """
        project = self._session.get(ProjectModel, automation.project_id)
        permissions = PermissionSpec.model_validate(automation.permissions_json or {})
        remote_cfg = None
        remote_row = self._session.get(ProjectRemoteModel, automation.project_id)
        if remote_row is not None:
            remote_cfg = dict(remote_row.config_json or {})
        kind = str(automation.target_kind or TargetKind.LOCAL.value)
        return {
            "kind": kind,
            "name": automation.name,
            "project_root": project.root_path if project is not None else None,
            "permissions": permissions,
            "remote": remote_cfg,
            "objective_mode": automation.objective_mode,
            "objective_json": automation.objective_json,
            "task_kind": "objective",
        }

    # ------------------------------------------------------------ execução

    async def execute(self, firing: AutomationFiringModel) -> ExecutionOutcome:
        """Executa um disparo: dependências, ação, evidência e estado.

        Args:
            firing: disparo a executar.

        Returns:
            O desfecho da execução, com o estado final e a próxima tentativa, quando houve.
        """
        automation = self._session.get(AutomationModel, firing.automation_id)
        if automation is None:
            firing.state = FiringState.CANCELLED.value
            firing.error = "automação removida"
            return ExecutionOutcome(firing.id, firing.state, ok=False, detail="automação removida")
        if automation.state != "enabled" and firing.state not in {
            FiringState.PENDING.value,
            FiringState.WAITING_DEPENDENCY.value,
        }:
            firing.state = FiringState.CANCELLED.value
            firing.error = f"automação {automation.state}"
            return ExecutionOutcome(firing.id, firing.state, ok=False, detail=firing.error)

        policy = RecoveryPolicy.model_validate(automation.policy_json or {})
        target = self._target_info(automation)
        dependencies = [
            DependencySpec.model_validate(item)
            for item in (automation.dependencies_json or [])
        ]

        firing.state = FiringState.PREPARING.value
        firing.attempt = int(firing.attempt or 0) + 1
        self._session.flush()

        resolver = DependencyResolver(
            settings=self._settings,
            project_root=target.get("project_root"),
            remote=target.get("remote"),
            target_kind=str(target.get("kind")),
        )
        check = await resolver.check_all(dependencies)
        target["dependencies"] = check.as_dict()
        if not check.ok:
            blocking = ", ".join(r.name or r.kind for r in check.blocking)
            firing.state = FiringState.WAITING_DEPENDENCY.value
            firing.next_attempt_at = self._next_attempt(policy, firing.attempt)
            firing.error = f"dependências indisponíveis: {blocking}"
            firing.result_json = {
                **(firing.result_json or {}),
                "dependencies": check.as_dict(),
            }
            self._log(automation, firing, "automation.dependency_blocked", {"blocking": blocking})
            return ExecutionOutcome(
                firing.id,
                firing.state,
                ok=False,
                detail=firing.error,
                retry_at=firing.next_attempt_at,
            )

        action_spec = parse_action(automation.action_json or {})
        try:
            action = build_action(action_spec)
        except ValueError as exc:
            firing.state = FiringState.BLOCKED.value
            firing.error = str(exc)
            self._log(automation, firing, "automation.blocked", {"error": str(exc)})
            return ExecutionOutcome(firing.id, firing.state, ok=False, detail=str(exc))

        ctx = ActionContext(
            session=self._session,
            settings=self._settings,
            automation_id=automation.id,
            project_id=automation.project_id,
            firing_id=firing.id,
            idempotency_key=firing.idempotency_key,
            target=target,
            dependencies=check.as_dict(),
            event=(firing.result_json or {}).get("payload"),
            timeout_sec=policy.timeout_sec or automation.timeout_sec,
        )

        firing.state = FiringState.RUNNING.value
        self._session.flush()

        try:
            result = await action.execute(ctx)
        except Exception as exc:  # noqa: BLE001 — falha da ação vira estado, não crash
            firing.state = FiringState.FAILED.value
            firing.error = f"{type(exc).__name__}: {exc}"
            self._log(automation, firing, "automation.failed", {"error": firing.error})
            return ExecutionOutcome(firing.id, firing.state, ok=False, detail=firing.error)

        evidence = redact_evidence(
            {
                **(firing.result_json or {}),
                "dependencies": check.as_dict(),
                "action": result.evidence,
                "summary": result.summary,
            }
        )
        firing.result_json = evidence
        firing.run_id = uuid.UUID(result.run_id) if result.run_id else firing.run_id
        firing.task_id = uuid.UUID(result.task_id) if result.task_id else firing.task_id

        if result.ok and not result.finished:
            # O trabalho continua (run entregue ao worker): reconciliação fecha o estado.
            firing.state = FiringState.RUNNING.value
            firing.error = None
            firing.next_attempt_at = None
            self._log(automation, firing, "automation.running", {"run_id": result.run_id})
            return ExecutionOutcome(firing.id, firing.state, ok=True, detail=result.summary)

        if result.ok:
            firing.state = FiringState.COMPLETED.value
            firing.error = None
            firing.next_attempt_at = None
            self._log(automation, firing, "automation.completed", {"summary": result.summary})
            return ExecutionOutcome(firing.id, firing.state, ok=True, detail=result.summary)

        retryable = bool(result.retryable) and (result.category or "") in (
            policy.retry_on or []
        )
        if retryable and firing.attempt < int(firing.max_attempts or policy.max_attempts):
            firing.state = FiringState.PENDING.value
            firing.next_attempt_at = self._next_attempt(policy, firing.attempt)
            firing.error = result.error or result.category
            self._log(
                automation,
                firing,
                "automation.retry_scheduled",
                {"attempt": firing.attempt, "error": firing.error},
            )
            return ExecutionOutcome(
                firing.id,
                firing.state,
                ok=False,
                detail=firing.error or "",
                retry_at=firing.next_attempt_at,
            )

        final_state = (
            FiringState.WAITING_DEPENDENCY.value
            if result.category == "dependency_unavailable"
            else FiringState.FAILED.value
        )
        firing.state = final_state
        firing.error = result.error or result.category
        if final_state == FiringState.WAITING_DEPENDENCY.value:
            firing.next_attempt_at = self._next_attempt(policy, firing.attempt)
        self._log(
            automation,
            firing,
            "automation.failed" if final_state == FiringState.FAILED.value else "automation.dependency_blocked",
            {"error": firing.error, "category": result.category},
        )
        return ExecutionOutcome(
            firing.id,
            firing.state,
            ok=False,
            detail=firing.error or "",
            retry_at=firing.next_attempt_at,
        )

    # -------------------------------------------------------- reconciliação

    def reconcile(self) -> list[ExecutionOutcome]:
        """Fecha os disparos que ficaram rodando, olhando o estado real do run.

        Returns:
            A lista dos desfechos reconciliados.
        """
        outcomes: list[ExecutionOutcome] = []
        rows = list(
            self._session.scalars(
                select(AutomationFiringModel).where(
                    AutomationFiringModel.state == FiringState.RUNNING.value
                )
            ).all()
        )
        for firing in rows:
            if firing.run_id is None:
                continue
            run = self._session.get(ExecutionRunModel, firing.run_id)
            if run is None:
                continue
            if run.status not in TERMINAL_RUN_STATES:
                continue
            ok = run.status == RunStatus.COMPLETED.value
            firing.state = FiringState.COMPLETED.value if ok else FiringState.FAILED.value
            firing.error = None if ok else f"execução terminou como {run.status}"
            firing.result_json = redact_evidence(
                {
                    **(firing.result_json or {}),
                    "run_status": run.status,
                }
            )
            automation = self._session.get(AutomationModel, firing.automation_id)
            if automation is not None:
                self._log(
                    automation,
                    firing,
                    "automation.completed" if ok else "automation.failed",
                    {"run_status": run.status},
                )
            outcomes.append(
                ExecutionOutcome(
                    firing.id,
                    firing.state,
                    ok=ok,
                    detail=firing.error or "reconciliado",
                )
            )
        if outcomes:
            self._session.flush()
        return outcomes

    # ------------------------------------------------------------- apoio

    def _next_attempt(self, policy: RecoveryPolicy, attempt: int) -> datetime:
        """Instante da próxima tentativa, com backoff exponencial limitado.

        Args:
            policy: política de recuperação da automação.
            attempt: número da tentativa que acabou de falhar.

        Returns:
            O instante, em UTC, da próxima tentativa.
        """
        delay = float(policy.backoff_sec or 10.0) * (
            float(policy.backoff_multiplier or 2.0) ** max(0, attempt - 1)
        )
        delay = min(delay, float(policy.max_backoff_sec or 900.0))
        return datetime.now(timezone.utc).replace(tzinfo=timezone.utc) + _seconds(delay)

    def _log(
        self,
        automation: AutomationModel,
        firing: AutomationFiringModel,
        event_type: str,
        payload: dict,
    ) -> None:
        """Registra um fato da automação no log de eventos.

        Args:
            automation: automação dona do disparo.
            firing: disparo relacionado.
            event_type: tipo do evento.
            payload: conteúdo do evento.
        """
        self._session.add(
            EventLogModel(
                project_id=automation.project_id,
                run_id=firing.run_id,
                task_id=firing.task_id,
                event_type=event_type,
                payload_json={
                    "automation_id": str(automation.id),
                    "firing_id": str(firing.id),
                    **payload,
                },
            )
        )


def _seconds(value: float):
    """Converte segundos em um intervalo de tempo.

    Args:
        value: quantidade de segundos.

    Returns:
        O `timedelta` correspondente.
    """
    from datetime import timedelta

    return timedelta(seconds=value)
