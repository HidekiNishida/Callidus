# src/agent/domain/agent_enums.py — enums da hierarquia de agentes
"""Estados do agente lógico, da execução e da consulta.

Três conceitos, três Conjuntos de estados:

- **Agente lógico** ([`AgentStatus`][agent.domain.agent_enums.AgentStatus]) — identidade,
  papel, permissões. Um agente existe mesmo sem execução.
- **Execução** ([`ExecutionStatus`][agent.domain.agent_enums.ExecutionStatus]) — instância
  ativa que usa modelo, contexto e ferramentas. Uma execução termina; o agente continua.
- **Consulta** ([`QueryStatus`][agent.domain.agent_enums.QueryStatus]) — pergunta de um
  agente a outro, com identificação, tentativas e correlação da resposta.
"""
from enum import StrEnum


class AgentStatus(StrEnum):
    """Estado do agente lógico. Não é o estado da tarefa: o agente sobrevive à tarefa."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DISCARDED = "DISCARDED"


class ExecutionStatus(StrEnum):
    """Estado da execução — a parte que ocupa memória de inferência.

    A distinção importa: `SUSPENDED` é recuperável (o checkpoint existe), `CANCELLED`
    é uma decisão confirmada e `DISCARDED` é o descarte do estado recuperável.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    WAITING_FOR_CHILD = "WAITING_FOR_CHILD"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DISCARDED = "DISCARDED"


class QueryStatus(StrEnum):
    """Estado da consulta entre agentes."""

    PENDING = "PENDING"
    ROUTED = "ROUTED"
    ANSWERED = "ANSWERED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


#: Execuções que ainda ocupam (ou podem ocupar) memória de inferência.
LIVE_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.RUNNING,
        ExecutionStatus.RESUMING,
        ExecutionStatus.SUSPENDING,
    }
)

#: Execuções sem estado recuperável: o agente precisa recomeçar do zero.
CLOSED_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.CANCELLED,
        ExecutionStatus.DISCARDED,
    }
)

#: Execuções que liberam a memória de inferência mas guardam o checkpoint.
RELEASED_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUSPENDED,
        ExecutionStatus.WAITING_FOR_CHILD,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
    }
)
