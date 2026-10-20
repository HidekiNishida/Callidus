"""
Arquivo: src/agent/automation/triggers/base.py
Nome: base.py
Propósito: definir o contrato dos gatilhos de automação e o registro de novos tipos.
Responsabilidade: camada de domínio — protocolo do gatilho e registro extensível.
Componentes: Trigger, TriggerFactory, register_trigger, trigger_factories, build_trigger.
Dependências: agent.automation.contracts, agent.automation.enums.
Observações: um gatilho só diz quais instantes são elegíveis; a entrega é do despachante.

Gatilho: a parte da automação que decide *quando*.

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
    """Registra (ou substitui) um tipo de gatilho.

    Args:
        kind: identificador do tipo de gatilho.
        factory: fábrica que constrói o gatilho a partir da especificação.
    """
    _REGISTRY[str(kind)] = factory


def trigger_factories() -> dict[str, TriggerFactory]:
    """Fábricas de gatilho registradas.

    Returns:
        Uma cópia do registro de fábricas.
    """
    return dict(_REGISTRY)


def build_trigger(spec: TriggerSpec) -> Trigger:
    """Instancia o gatilho de uma especificação.

    Args:
        spec: especificação do gatilho.

    Returns:
        O gatilho pronto para uso.

    Raises:
        ValueError: quando o tipo de gatilho não está registrado.
    """
    factory = _REGISTRY.get(str(spec.kind))
    if factory is None:
        raise ValueError(f"tipo de gatilho desconhecido: {spec.kind}")
    return factory(spec)
