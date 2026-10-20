# src/agent/automation/actions/__init__.py — tipos de ação registrados
from agent.automation.actions.base import (
    Action,
    ActionContext,
    ActionFactory,
    ActionResult,
    action_factories,
    build_action,
    register_action,
)
from agent.automation.actions.callidus import CallidusActionRunner
from agent.automation.actions.script import ScriptActionRunner

register_action("callidus", CallidusActionRunner)
register_action("script", ScriptActionRunner)

__all__ = [
    "Action",
    "ActionContext",
    "ActionFactory",
    "ActionResult",
    "CallidusActionRunner",
    "ScriptActionRunner",
    "action_factories",
    "build_action",
    "register_action",
]
