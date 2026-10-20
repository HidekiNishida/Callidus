# src/agent/automation/__init__.py — runtime de automações persistentes
"""Automações persistentes, autônomas e multiplataforma.

Quatro responsabilidades, separadas de propósito:

- **Definição** — [`store.py`][agent.automation.store] grava o contrato aprovado.
- **Disparo** — [`dispatcher.py`][agent.automation.dispatcher] registra o disparo
  (com chave de idempotência) e aplica a política de disparos perdidos.
- **Runtime** — [`supervisor.py`][agent.automation.supervisor] mantém tudo vivo sem a
  interface; [`service/`][agent.automation.service] instala o arranque nativo.
- **Execução** — [`executor.py`][agent.automation.executor] verifica dependências,
  roda a ação ([`actions/`][agent.automation.actions]) e persiste a evidência.
"""
from agent.automation.contracts import (
    AutomationDefinition,
    CallidusAction,
    DependencySpec,
    PermissionSpec,
    RecoveryPolicy,
    ScriptAction,
    StartStrategy,
    TriggerSpec,
)
from agent.automation.dispatcher import Dispatcher
from agent.automation.enums import (
    ActionKind,
    AutomationState,
    DependencyKind,
    FiringState,
    MissedPolicy,
    ObjectiveMode,
    StartMechanism,
    TargetKind,
    TriggerKind,
)
from agent.automation.executor import AutomationExecutor
from agent.automation.store import AutomationService
from agent.automation.supervisor import AutomationSupervisor, build_supervisor

__all__ = [
    "ActionKind",
    "AutomationDefinition",
    "AutomationExecutor",
    "AutomationService",
    "AutomationState",
    "AutomationSupervisor",
    "CallidusAction",
    "DependencyKind",
    "DependencySpec",
    "Dispatcher",
    "FiringState",
    "MissedPolicy",
    "ObjectiveMode",
    "PermissionSpec",
    "RecoveryPolicy",
    "ScriptAction",
    "StartMechanism",
    "StartStrategy",
    "TargetKind",
    "TriggerKind",
    "TriggerSpec",
    "build_supervisor",
]
