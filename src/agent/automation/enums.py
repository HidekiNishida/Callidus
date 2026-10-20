# src/agent/automation/enums.py — vocabulário das automações
from __future__ import annotations

from enum import StrEnum


class AutomationState(StrEnum):
    """Estado da definição da automação (o que o usuário controla)."""

    ENABLED = "enabled"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class TriggerKind(StrEnum):
    """Modalidades iniciais de gatilho. Novas modalidades entram por registro."""

    ONCE = "once"
    CRON = "cron"
    INTERVAL = "interval"
    EVENT = "event"


class ActionKind(StrEnum):
    """Tipos de ação. A arquitetura permite novos tipos por registro."""

    CALLIDUS = "callidus"
    SCRIPT = "script"


class TargetKind(StrEnum):
    """Onde a ação acontece: nesta máquina ou no computador remoto do projeto."""

    LOCAL = "local"
    REMOTE = "remote"


class ObjectiveMode(StrEnum):
    """Como a automação escolhe o objetivo de uma conversa/tarefa.

    `frozen` guarda o objetivo no momento da aprovação — alterações posteriores na
    conversa não mudam uma automação já aprovada. `latest` usa sempre a versão mais
    recente, e só quando o usuário pediu explicitamente.
    """

    FROZEN = "frozen"
    LATEST = "latest"


class MissedPolicy(StrEnum):
    """O que fazer com disparos perdidos durante uma interrupção."""

    RUN_ONCE = "run_once"
    CATCH_UP = "catch_up"
    GROUP = "group"
    SKIP = "skip"


class DependencyKind(StrEnum):
    """Tipos de dependência verificável antes da execução."""

    PROJECT_DIR = "project_dir"
    WORKDIR = "workdir"
    OS = "os"
    INTERPRETER = "interpreter"
    SCRIPT = "script"
    REMOTE = "remote"
    PROVIDER = "provider"
    TOOL = "tool"
    MCP = "mcp"
    CREDENTIAL = "credential"


class StartMechanism(StrEnum):
    """Como uma dependência pode ser iniciada automaticamente.

    Só `NONE` significa "não iniciar". Os demais exigem configuração e autorização
    explícitas: o Callidus não instala nem reinicia nada por conta própria.
    """

    NONE = "none"
    COMMAND = "command"
    MCP_RESTART = "mcp_restart"
    SERVICE = "service"


class FiringState(StrEnum):
    """Estados do disparo (a máquina de estados do trabalho executado)."""

    PENDING = "pending"
    PREPARING = "preparing"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_FIRING_STATES = frozenset(
    {
        FiringState.COMPLETED.value,
        FiringState.FAILED.value,
        FiringState.SKIPPED.value,
        FiringState.CANCELLED.value,
    }
)

ACTIVE_FIRING_STATES = frozenset(
    {
        FiringState.PENDING.value,
        FiringState.PREPARING.value,
        FiringState.WAITING_DEPENDENCY.value,
        FiringState.RUNNING.value,
    }
)
