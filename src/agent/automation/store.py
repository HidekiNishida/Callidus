"""
Arquivo: src/agent/automation/store.py
Nome: store.py
Propósito: manter a definição aprovada das automações, com contrato validado.
Responsabilidade: camada de aplicação — CRUD da definição e cálculo do próximo disparo.
Componentes: AutomationService, AutomationNotFound.
Dependências: agent.automation.contracts, agent.automation.enums, agent.automation.triggers, agent.persistence.models.
Observações: `next_run_at` é derivado do gatilho e recalculado sempre que a definição muda.

CRUD da definição da automação, com contrato validado.

O que fica gravado é o **documento aprovado**: gatilho, ação, dependências,
permissões e política. `next_run_at` é derivado do gatilho e recalculado sempre que
a definição muda — o banco guarda o resultado para a interface, mas quem decide é o
gatilho.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.automation.contracts import (
    AutomationDefinition,
    DependencySpec,
    PermissionSpec,
    RecoveryPolicy,
    TriggerSpec,
    dump_action,
    parse_action,
)
from agent.automation.enums import AutomationState, MissedPolicy, ObjectiveMode, TargetKind
from agent.automation.timezones import to_utc
from agent.automation.triggers import build_trigger
from agent.persistence.models import AutomationModel, EventLogModel


class AutomationNotFound(LookupError):
    """Automação inexistente ou com identificador inválido."""


class AutomationService:
    """Serviço das automações de um projeto.

    Atributos:
        _session: sessão usada nas leituras, gravações e no registro de eventos.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    # ------------------------------------------------------------ leitura

    def get(self, automation_id: uuid.UUID | str) -> AutomationModel:
        """Automação por identificador.

        Args:
            automation_id: identificador da automação.

        Returns:
            A automação encontrada.

        Raises:
            AutomationNotFound: quando a automação não existe ou o identificador é inválido.
        """
        try:
            key = uuid.UUID(str(automation_id))
        except (ValueError, AttributeError) as exc:
            raise AutomationNotFound(str(automation_id)) from exc
        row = self._session.get(AutomationModel, key)
        if row is None:
            raise AutomationNotFound(str(automation_id))
        return row

    def list(
        self, project_id: uuid.UUID | None = None, *, state: str | None = None
    ) -> list[AutomationModel]:
        """Automações do catálogo, filtradas por projeto e por estado.

        Args:
            project_id: projeto a filtrar; `None` devolve todas.
            state: estado a filtrar, quando informado.

        Returns:
            A lista de automações, da mais antiga para a mais recente.
        """
        stmt = select(AutomationModel).order_by(AutomationModel.created_at)
        if project_id is not None:
            stmt = stmt.where(AutomationModel.project_id == project_id)
        if state:
            stmt = stmt.where(AutomationModel.state == state)
        return list(self._session.scalars(stmt).all())

    def enabled(self) -> list[AutomationModel]:
        """Automações habilitadas, que o supervisor deve vigiar.

        Returns:
            A lista de automações no estado `enabled`.
        """
        return list(
            self._session.scalars(
                select(AutomationModel).where(
                    AutomationModel.state == AutomationState.ENABLED.value
                )
            ).all()
        )

    # ------------------------------------------------------------ escrita

    def create(self, definition: AutomationDefinition) -> AutomationModel:
        """Grava a definição aprovada de uma automação.

        Args:
            definition: documento validado da automação.

        Returns:
            A automação criada, com o próximo disparo já calculado.
        """
        project_id = uuid.UUID(str(definition.project_id))
        trigger = definition.trigger
        action = definition.action
        row = AutomationModel(
            project_id=project_id,
            name=definition.name,
            description=definition.description,
            contract_version=definition.contract_version,
            target_kind=str(definition.target_kind),
            trigger_json=trigger.model_dump(mode="json"),
            action_json=dump_action(action),
            dependencies_json=[d.model_dump(mode="json") for d in definition.dependencies],
            permissions_json=definition.permissions.model_dump(mode="json"),
            policy_json=definition.policy.model_dump(mode="json"),
            timezone=definition.timezone,
            missed_policy=str(definition.missed_policy),
            state=definition.state,
            conversation_id=_uuid_or_none(definition.conversation_id),
            task_id=_uuid_or_none(definition.task_id),
            objective_mode=str(definition.objective_mode),
            objective_json=self._objective_snapshot(definition, action=action.model_dump(mode="json")),
            max_attempts=definition.policy.max_attempts,
            timeout_sec=definition.policy.timeout_sec,
        )
        self._session.add(row)
        self._session.flush()
        self._recompute_next_run(row)
        self._session.flush()
        self._log(row, "automation.created", {"name": row.name})
        return row

    def update(self, automation_id: uuid.UUID | str, changes: dict[str, Any]) -> AutomationModel:
        """Aplica alterações na definição de uma automação.

        Args:
            automation_id: identificador da automação.
            changes: campos a alterar; cada um é validado antes de ser gravado.

        Returns:
            A automação atualizada, com o próximo disparo recalculado.

        Raises:
            AutomationNotFound: quando a automação não existe.
        """
        row = self.get(automation_id)
        definition = self.to_definition(row)
        payload = changes.copy()

        for key in ("name", "description"):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        if payload.get("state"):
            row.state = str(payload["state"])
        if payload.get("timezone"):
            row.timezone = str(payload["timezone"])
        if payload.get("missed_policy"):
            row.missed_policy = str(payload["missed_policy"])
        if payload.get("target_kind"):
            row.target_kind = str(payload["target_kind"])
        if payload.get("objective_mode"):
            row.objective_mode = str(payload["objective_mode"])
        if payload.get("conversation_id") is not None:
            row.conversation_id = _uuid_or_none(payload["conversation_id"])
        if payload.get("task_id") is not None:
            row.task_id = _uuid_or_none(payload["task_id"])
        if payload.get("trigger") is not None:
            row.trigger_json = TriggerSpec.model_validate(payload["trigger"]).model_dump(mode="json")
        if payload.get("action") is not None:
            row.action_json = dump_action(parse_action(payload["action"]))
        if payload.get("dependencies") is not None:
            row.dependencies_json = [
                DependencySpec.model_validate(item).model_dump(mode="json")
                for item in payload["dependencies"]
            ]
        if payload.get("permissions") is not None:
            row.permissions_json = PermissionSpec.model_validate(
                payload["permissions"]
            ).model_dump(mode="json")
        if payload.get("policy") is not None:
            policy = RecoveryPolicy.model_validate(payload["policy"])
            row.policy_json = policy.model_dump(mode="json")
            row.max_attempts = policy.max_attempts
            row.timeout_sec = policy.timeout_sec
        if payload.get("freeze_objective"):
            row.objective_json = self._objective_snapshot(definition, action=row.action_json)

        self._session.flush()
        self._recompute_next_run(row)
        self._session.flush()
        self._log(row, "automation.updated", {"fields": sorted(payload.keys())})
        return row

    def set_state(self, automation_id: uuid.UUID | str, state: AutomationState) -> AutomationModel:
        """Muda o estado da automação (habilitada, suspensa ou desabilitada).

        Args:
            automation_id: identificador da automação.
            state: novo estado.

        Returns:
            A automação com o novo estado e o próximo disparo recalculado.

        Raises:
            AutomationNotFound: quando a automação não existe.
        """
        row = self.get(automation_id)
        row.state = str(state)
        self._session.flush()
        self._recompute_next_run(row)
        self._session.flush()
        self._log(row, f"automation.{row.state}", {})
        return row

    def delete(self, automation_id: uuid.UUID | str) -> bool:
        """Remove uma automação.

        Args:
            automation_id: identificador da automação.

        Returns:
            `True` quando a automação existia e foi removida.

        Raises:
            AutomationNotFound: quando a automação não existe.
        """
        row = self.get(automation_id)
        self._session.delete(row)
        self._session.flush()
        return True

    # -------------------------------------------------------------derived

    def to_definition(self, row: AutomationModel) -> AutomationDefinition:
        """Documento validado da automação gravada.

        Args:
            row: linha da automação.

        Returns:
            A definição reconstruída e validada.
        """
        return AutomationDefinition(
            name=row.name,
            description=row.description,
            project_id=str(row.project_id),
            contract_version=row.contract_version,
            target_kind=TargetKind(row.target_kind),
            trigger=TriggerSpec.model_validate(row.trigger_json or {}),
            action=parse_action(row.action_json or {}),
            dependencies=[DependencySpec.model_validate(item) for item in (row.dependencies_json or [])],
            permissions=PermissionSpec.model_validate(row.permissions_json or {}),
            policy=RecoveryPolicy.model_validate(row.policy_json or {}),
            timezone=row.timezone,
            missed_policy=MissedPolicy(row.missed_policy),
            conversation_id=str(row.conversation_id) if row.conversation_id else None,
            task_id=str(row.task_id) if row.task_id else None,
            objective_mode=ObjectiveMode(row.objective_mode),
            state=row.state,
        )

    def trigger_of(self, row: AutomationModel):
        """Gatilho da automação, já instanciado.

        Args:
            row: linha da automação.

        Returns:
            O gatilho correspondente à definição gravada.
        """
        spec = TriggerSpec.model_validate(row.trigger_json or {})
        if spec.kind.value == "event":

            trigger = build_trigger(spec)
            return trigger.with_project(str(row.project_id))
        return build_trigger(spec)

    def next_occurrence(self, row: AutomationModel, *, after: datetime | None = None) -> datetime | None:
        """Próximo instante elegível da automação.

        Args:
            row: linha da automação.
            after: instante de referência; por padrão, agora.

        Returns:
            O próximo instante, ou `None` quando a definição é inválida.
        """
        trigger = self.trigger_of(row)
        reference = after or datetime.now(timezone.utc)
        try:
            return trigger.next_occurrence(reference)
        except Exception:  # noqa: BLE001 — definição inválida não derruba o runtime
            return None

    def _recompute_next_run(self, row: AutomationModel) -> None:
        """Recalcula o próximo disparo a partir do gatilho da definição.

        Args:
            row: linha da automação.
        """
        if row.state != AutomationState.ENABLED.value:
            row.next_run_at = None
            return
        row.next_run_at = self.next_occurrence(row)

    # ------------------------------------------------------------ apoio

    def _objective_snapshot(self, definition: AutomationDefinition, *, action: dict | None = None) -> dict | None:
        """Congela o objetivo no momento da aprovação (modo `frozen`).

        Args:
            definition: definição da automação.
            action: documento da ação, quando já conhecido.

        Returns:
            O objetivo congelado com o instante do congelamento, ou `None`.
        """
        if definition.objective_mode is not ObjectiveMode.FROZEN:
            return None
        objective = None
        task_id = definition.task_id
        if action is not None:
            objective = action.get("objective")
            task_id = action.get("task_id") or task_id
        if objective is None:
            objective = getattr(definition.action, "objective", None)
        if objective:
            return {"objective": str(objective), "frozen_at": datetime.now(timezone.utc).isoformat()}
        if task_id:
            from agent.persistence.models import TaskModel

            try:
                task = self._session.get(TaskModel, uuid.UUID(str(task_id)))
            except (ValueError, AttributeError):
                task = None
            if task is not None and task.objective:
                return {"objective": task.objective, "frozen_at": datetime.now(timezone.utc).isoformat()}
        return None

    def _log(self, row: AutomationModel, event_type: str, payload: dict) -> None:
        """Registra um fato da automação no log de eventos.

        Args:
            row: linha da automação.
            event_type: tipo do evento.
            payload: conteúdo do evento.
        """
        self._session.add(
            EventLogModel(
                project_id=row.project_id,
                event_type=event_type,
                payload_json=payload,
            )
        )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Converte um valor em UUID, tolerando ausência e texto inválido.

    Args:
        value: valor de entrada.

    Returns:
        O UUID correspondente, ou `None` quando o valor está ausente ou é inválido.
    """
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


__all__ = [
    "AutomationNotFound",
    "AutomationService",
    "ValidationError",
    "to_utc",
]
