# src/agent/automation/triggers/base.py — contrato dos gatilhos e registro de novos tipos
"""Gatilho: a parte da automação que decide *quando*.

Um gatilho não executa nada: ele diz quais instantes (UTC) são elegíveis. A
entrega do disparo — com chave de idempotência — é do despachante.

Novos tipos entram por registro, sem tocar na lógica central:

    from agent.automation.triggers import register_trigger

    register_trigger("arquivo", FileTrigger)
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol, runtime_checkable

from agent.automation.contracts import TriggerSpec
from agent.automation.enums import TriggerKind


@runtime_checkable
class Trigger(Protocol):
    """O mínimo que o runtime precisa de um gatilho."""

    kind: TriggerKind

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Próximo instante elegível depois de `after` (UTC)."""

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        """Instantes elegíveis na janela (UTC) — usado para recuperar disparos perdidos."""


TriggerFactory = Callable[[TriggerSpec], Trigger]

_REGISTRY: dict[str, TriggerFactory] = {}


def register_trigger(kind: str, factory: TriggerFactory) -> None:
    """Registra (ou substitui) um tipo de gatilho."""
    _REGISTRY[str(kind)] = factory


def trigger_factories() -> dict[str, TriggerFactory]:
    return dict(_REGISTRY)


def build_trigger(spec: TriggerSpec) -> Trigger:
    """Instancia o gatilho de uma especificação."""
    factory = _REGISTRY.get(str(spec.kind))
    if factory is None:
        raise ValueError(f"tipo de gatilho desconhecido: {spec.kind}")
    return factory(spec)
