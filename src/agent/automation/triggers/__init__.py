# src/agent/automation/triggers/__init__.py — tipos de gatilho registrados
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
