"""
Arquivo: src/agent/automation/triggers/__init__.py
Nome: __init__.py
Propósito: expor os tipos de gatilho de automação e registrar as implementações conhecidas.
Responsabilidade: camada de aplicação — registro extensível dos gatilhos de disparo.
Componentes: Trigger, TriggerFactory, build_trigger, register_trigger, trigger_factories, CronTrigger, DailyAtTrigger, IntervalTrigger, OnceTrigger, EventTrigger.
Dependências: agent.automation.triggers.base, agent.automation.triggers.internal, agent.automation.triggers.temporal.
Observações: o registro acontece na importação; novos tipos exigem uma chamada a `register_trigger`.
"""
from agent.automation.triggers.base import (
    Trigger,
    TriggerFactory,
    build_trigger,
    register_trigger,
    trigger_factories,
)
from agent.automation.triggers.internal import EventTrigger
from agent.automation.triggers.temporal import (
    CronTrigger,
    DailyAtTrigger,
    IntervalTrigger,
    OnceTrigger,
)

register_trigger("once", OnceTrigger)
register_trigger("cron", CronTrigger)
register_trigger("interval", IntervalTrigger)
register_trigger("event", EventTrigger)

__all__ = [
    "CronTrigger",
    "DailyAtTrigger",
    "EventTrigger",
    "IntervalTrigger",
    "OnceTrigger",
    "Trigger",
    "TriggerFactory",
    "build_trigger",
    "register_trigger",
    "trigger_factories",
]
