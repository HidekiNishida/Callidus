# src/agent/persistence/models.py — modelos SQLAlchemy
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from agent.domain.enums import MemoryKind, RunStatus, TaskKind, TaskStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    root_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    path_origin: Mapped[str] = mapped_column(String(16), default="chosen")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    tasks: Mapped[list[TaskModel]] = relationship(back_populates="project")


class ConversationModel(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="pt")
    root_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    active_branch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value)
    kind: Mapped[str] = mapped_column(String(32), default=TaskKind.OBJECTIVE.value)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    consolidated_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[ProjectModel] = relationship(back_populates="tasks")
    parent: Mapped[TaskModel | None] = relationship(remote_side=[id])


class BranchModel(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    fork_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dep"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)


class ExecutionRunModel(Base):
    __tablename__ = "execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    root_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.ACTIVE.value)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ScheduledRunModel(Base):
    __tablename__ = "scheduled_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "0 10 * * 1" para toda segunda às 10h
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OperationAttemptModel(Base):
    __tablename__ = "operation_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventLogModel(Base):
    __tablename__ = "event_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryRecordModel(Base):
    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outline_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KgNodeModel(Base):
    __tablename__ = "kg_nodes"
    __table_args__ = (UniqueConstraint("project_id", "kind", "ref", name="uq_kg_node_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KgEdgeModel(Base):
    __tablename__ = "kg_edges"
    __table_args__ = (UniqueConstraint("project_id", "src_id", "dst_id", "rel", name="uq_kg_edge"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kg_nodes.id"), nullable=False)
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kg_nodes.id"), nullable=False)
    rel: Mapped[str] = mapped_column(String(64), nullable=False)


class TaskContractModel(Base):
    __tablename__ = "task_contracts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False, unique=True)
    inputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    invariants_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    acceptance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContextSnapshotModel(Base):
    __tablename__ = "context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    components_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    strategy_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceModel(Base):
    __tablename__ = "evidences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_attempts.id"), nullable=True
    )
    verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
