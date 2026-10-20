"""
Arquivo: src/agent/automation/actions/__init__.py
Nome: __init__.py
Propósito: expor os tipos de ação de automação e registrar as implementações conhecidas.
Responsabilidade: camada de aplicação — registro extensível das ações executáveis.
Componentes: Action, ActionContext, ActionFactory, ActionResult, CallidusActionRunner, ScriptActionRunner, build_action, register_action, action_factories.
Dependências: agent.automation.actions.base, agent.automation.actions.callidus, agent.automation.actions.script.
Observações: o registro acontece na importação; novos tipos exigem uma chamada a `register_action`.
"""
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
