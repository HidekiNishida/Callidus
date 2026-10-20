"""
Arquivo: src/agent/domain/enums.py
Nome: enums.py
Propósito: definir os enums de domínio do Callidus (tarefa, run, tentativa e memória).
Responsabilidade: camada de domínio — vocabulário de estados compartilhado por toda a aplicação.
Componentes: TaskStatus, TaskKind, MemoryKind, RunStatus, AttemptKind.
Dependências: enum (stdlib).
Observações: são `StrEnum`; o valor gravado no banco e o exibido na API são o mesmo texto.
"""
from enum import StrEnum


class TaskStatus(StrEnum):
    """Ciclo de vida de uma tarefa: do planejamento à verificação e ao desfecho final."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    RETRY_PENDING = "RETRY_PENDING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskKind(StrEnum):
    """Papel da tarefa na decomposição: objetivo do usuário, subsistema ou operação concreta."""

    OBJECTIVE = "objective"
    SUBSYSTEM = "subsystem"
    OPERATION = "operation"


class MemoryKind(StrEnum):
    """Natureza do registro de memória: canônico, de execução, contextual, evidência ou procedimento."""

    CANONICAL = "canonical"
    EXECUTION = "execution"
    CONTEXTUAL = "contextual"
    EVIDENCE = "evidence"
    PROCEDURE = "procedure"


class RunStatus(StrEnum):
    """Estado do run: ativo, pausado para retomada ou encerrado de forma definitiva."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    """Natureza do registro de tentativa: chamada de modelo, de ferramenta ou de verificação."""

    MODEL = "model"
    TOOL = "tool"
    VERIFICATION = "verification"
