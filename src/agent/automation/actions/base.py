# src/agent/automation/actions/base.py — contrato das ações e registro de novos tipos
"""Ação: a parte da automação que decide *o que fazer* quando o horário chega.

Uma ação não sabe de gatilho, e o gatilho não sabe de ação. A execução recebe o
contexto pronto (dependências verificadas, destino resolvido) e devolve um resultado
com evidência.

Novos tipos de ação entram por registro:

    from agent.automation.actions import register_action

    register_action("ferramenta", ToolAction)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from agent.automation.contracts import ActionSpec
from agent.automation.enums import ActionKind


@dataclass
class ActionContext:
    """Tudo o que a ação precisa, já resolvido."""

    session: Session
    settings: Any
    automation_id: uuid.UUID
    project_id: uuid.UUID
    firing_id: uuid.UUID
    idempotency_key: str
    # Informações do destino (local ou remoto) já validadas.
    target: dict[str, Any] = field(default_factory=dict)
    # Resultado da verificação de dependências.
    dependencies: dict[str, Any] = field(default_factory=dict)
    # Payload do evento que disparou (quando o gatilho é de evento).
    event: dict[str, Any] | None = None
    timeout_sec: float | None = None


@dataclass
class ActionResult:
    """Desfecho de uma ação."""

    ok: bool
    summary: str = ""
    # Evidências persistidas (saída do script, id do run, códigos de saída...).
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # Categoria da falha: `timeout`, `remote_unreachable`, `permission_denied`...
    category: str | None = None
    # A falha vale uma nova tentativa?
    retryable: bool = False
    # Identificadores para reconciliação posterior (run criado, tarefa criada...).
    run_id: str | None = None
    task_id: str | None = None
    # `True` quando a ação foi executada por completo; `False` quando ficou em curso
    # (ex.: um run entregue ao worker autônomo).
    finished: bool = True


class Action(Protocol):
    """O mínimo que o runtime precisa de uma ação."""

    kind: ActionKind

    async def execute(self, ctx: ActionContext) -> ActionResult: ...


ActionFactory = Callable[[ActionSpec], Action]

_REGISTRY: dict[str, ActionFactory] = {}


def register_action(kind: str, factory: ActionFactory) -> None:
    """Registra (ou substitui) um tipo de ação."""
    _REGISTRY[str(kind)] = factory


def action_factories() -> dict[str, ActionFactory]:
    return dict(_REGISTRY)


def build_action(spec: ActionSpec) -> Action:
    factory = _REGISTRY.get(str(spec.kind))
    if factory is None:
        raise ValueError(f"tipo de ação desconhecido: {spec.kind}")
    return factory(spec)
