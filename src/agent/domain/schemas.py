# src/agent/domain/schemas.py — contratos Pydantic (API e fronteiras)
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agent.domain.agent_enums import AgentStatus, ExecutionStatus, QueryStatus
from agent.domain.enums import MemoryKind, RunStatus, TaskKind, TaskStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    root_path: str = ""
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    root_path: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = None
    locale: str | None = None


class ConversationMove(BaseModel):
    project_id: UUID | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    root_path: str | None = None
    clear_root: bool = False


class BranchRead(BaseModel):
    id: UUID
    parent_id: UUID | None = None
    fork_task_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationFork(BaseModel):
    task_id: UUID
    objective: str = Field(min_length=1)


class ConversationRead(BaseModel):
    id: UUID
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    title: str
    locale: str
    root_path: str | None = None
    path_origin: str = "home"
    active_branch_id: UUID | None = None
    branches: list[BranchRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectRead(BaseModel):
    id: UUID
    name: str
    root_path: str
    description: str | None
    path_origin: str = "chosen"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1)
    scope: str | None = None
    acceptance_criteria: str | None = None
    kind: TaskKind = TaskKind.OBJECTIVE
    parent_id: UUID | None = None
    conversation_id: UUID | None = None
    branch_id: UUID | None = None
    metadata: dict | None = None


class TaskRead(BaseModel):
    id: UUID
    project_id: UUID
    conversation_id: UUID | None = None
    branch_id: UUID | None = None
    parent_id: UUID | None
    title: str
    display_title: str | None = None
    objective: str
    scope: str | None
    acceptance_criteria: str | None
    status: TaskStatus
    kind: TaskKind
    sort_order: int
    metadata_json: dict | None
    consolidated_result_json: dict | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    usage_tokens: int = 0

    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    reason: str | None = None


class TaskDependencyCreate(BaseModel):
    depends_on_task_id: UUID


class ExecutionRunCreate(BaseModel):
    root_task_id: UUID
    config: dict | None = None


class ExecutionRunRead(BaseModel):
    id: UUID
    project_id: UUID
    root_task_id: UUID
    status: RunStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EventRead(BaseModel):
    id: UUID
    run_id: UUID | None
    task_id: UUID | None
    event_type: str
    payload_json: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryCreate(BaseModel):
    kind: MemoryKind
    title: str
    content: str
    task_id: UUID | None = None
    conversation_id: UUID | None = None
    branch_id: UUID | None = None
    source_refs: list[str] | None = None


class MemoryRead(BaseModel):
    id: UUID
    project_id: UUID
    conversation_id: UUID | None = None
    branch_id: UUID | None = None
    task_id: UUID | None
    kind: MemoryKind
    title: str
    content: str
    summary: str | None = None
    outline_json: dict | None = None
    version: int
    source_refs_json: list[str] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRead(BaseModel):
    """Agente lógico: identidade, papel, estado e o que ele sabe."""

    id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    task_id: UUID | None = None
    role: str = "worker"
    instructions: str | None = None
    status: AgentStatus = AgentStatus.IDLE
    depth: int = 0
    children: int = 0
    execution_status: ExecutionStatus | None = None
    findings: list[dict] = Field(default_factory=list)
    checkpoint: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AgentAsk(BaseModel):
    """Consulta de um agente a outro."""

    requester_agent_id: UUID
    question: str | list[str]
    task_id: UUID | None = None
    correlation_id: str | None = None
    provider: str | None = None


class AgentDiscard(BaseModel):
    """Descarte do estado recuperável de um agente."""

    reason: str = ""
    purge: bool = False
    force: bool = False


class AgentQueryRead(BaseModel):
    """Consulta e sua resposta (correlacionadas por identificador)."""

    id: UUID
    project_id: UUID
    requester_agent_id: UUID
    target_agent_id: UUID
    answered_by_agent_id: UUID | None = None
    task_id: UUID | None = None
    correlation_id: str
    questions_json: list[str] = Field(default_factory=list)
    status: QueryStatus = QueryStatus.PENDING
    answer: str | None = None
    answer_json: dict | None = None
    attempts: int = 0
    max_attempts: int = 3
    error_message: str | None = None
    created_at: datetime
    answered_at: datetime | None = None

    model_config = {"from_attributes": True}
