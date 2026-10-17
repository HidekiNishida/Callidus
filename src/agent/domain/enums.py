# src/agent/domain/enums.py — enums de domínio
from enum import StrEnum


class TaskStatus(StrEnum):
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
    OBJECTIVE = "objective"
    SUBSYSTEM = "subsystem"
    OPERATION = "operation"


class MemoryKind(StrEnum):
    CANONICAL = "canonical"
    EXECUTION = "execution"
    CONTEXTUAL = "contextual"
    EVIDENCE = "evidence"
    PROCEDURE = "procedure"


class RunStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    VERIFICATION = "verification"
