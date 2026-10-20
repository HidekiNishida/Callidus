"""
Arquivo: src/agent/observability/__init__.py
Nome: __init__.py
Propósito: expor a camada de observabilidade do Callidus (eventos de execução em tempo real).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.observability`.
Componentes: EventBus, EventEnvelope, EVENT_SPECS, SCHEMA_VERSION, RESYNC, emit, observe, scoped, set_task, current.
Dependências: agent.observability.bus, agent.observability.contracts, agent.observability.emitter.
Observações: o envelope dos eventos é um contrato público; mudá-lo quebra os assinantes SSE.
"""
from agent.observability.bus import RESYNC, EventBus, get_bus
from agent.observability.contracts import EVENT_SPECS, SCHEMA_VERSION, EventEnvelope, envelope_from_row
from agent.observability.emitter import current, emit, install, observe, scoped, set_task

__all__ = [
    "EVENT_SPECS",
    "RESYNC",
    "SCHEMA_VERSION",
    "EventBus",
    "EventEnvelope",
    "current",
    "emit",
    "envelope_from_row",
    "get_bus",
    "install",
    "observe",
    "scoped",
    "set_task",
]
