"""
Arquivo: src/agent/persistence/models.py
Nome: models.py
Propósito: definir os modelos SQLAlchemy que mapeiam o estado canônico do Callidus no SQLite.
Responsabilidade: camada de infraestrutura — esquema relacional do agente, das execuções e das automações.
Componentes: Base e os modelos Project, Conversation, Task, Branch, ExecutionRun, Automation, AutomationFiring, AutomationEvent, OperationAttempt, EventLog, MemoryRecord, KgNode, KgEdge, TaskContract, ContextSnapshot, InferenceRecord, Evidence, Agent, AgentExecution, AgentQuery.
Dependências: sqlalchemy, agent.domain.agent_enums, agent.domain.enums.
Observações: o SQLite é a fonte da verdade; o formato das evidências e do histórico de tentativas é contrato.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from agent.domain.agent_enums import AgentStatus, ExecutionStatus, QueryStatus
from agent.domain.enums import RunStatus, TaskKind, TaskStatus


def utcnow() -> datetime:
    """Instante atual em UTC, usado como valor padrão das colunas de tempo.

    Returns:
        O datetime atual com fuso horário UTC.
    """
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos do Callidus."""


class ProjectModel(Base):
    """Projeto do usuário: a pasta de trabalho onde as tarefas são executadas."""

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


class ProjectRemoteModel(Base):
    """Computador remoto do projeto: quando existe, as ações do projeto rodam lá por SSH."""

    __tablename__ = "project_remotes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationModel(Base):
    """Conversa do usuário: a linha de tempo que agrupa tarefas, memórias e ramos."""

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
    """Tarefa do agente: objetivo, escopo, estado e resultado consolidado."""

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
    """Ramo de conversa: linha de trabalho isolada, nascida de uma bifurcagem de tarefa."""

    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    fork_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskDependencyModel(Base):
    """Dependência entre tarefas: a tarefa só roda depois da tarefa de que depende."""

    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dep"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)


class ExecutionRunModel(Base):
    """Run de execução: a unidade de orquestração que percorre a árvore de tarefas."""

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
    """Agendamento legado (tabela `scheduled_runs`), migrado para automações.

    A tabela é preservada para inspeção; a migração é idempotente e cria no máximo
    uma automação por linha antiga.
    """

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


class AutomationModel(Base):
    """Automação persistente: a definição aprovada de um trabalho que roda sozinho.

    A definição é um contrato versionado (`contract_version`): gatilho, ação,
    dependências, permissões e política de recuperação ficam em colunas JSON
    validadas pelo serviço de automações. `next_run_at` é o relógio de parede do
    próximo disparo, em UTC — quem calcula é o gatilho, não a API.
    """

    __tablename__ = "automations"
    __table_args__ = (
        Index("ix_automations_project", "project_id"),
        Index("ix_automations_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Versão do contrato de definição: quando o formato muda, o dado antigo continua legível.
    contract_version: Mapped[int] = mapped_column(Integer, default=1)
    # `local` (nesta máquina) ou `remote` (computador do projeto, por SSH).
    target_kind: Mapped[str] = mapped_column(String(16), default="local")
    trigger_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dependencies_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    permissions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Fuso do gatilho. Os carimbos persistidos são sempre UTC.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # Política para disparos perdidos durante interrupções.
    missed_policy: Mapped[str] = mapped_column(String(16), default="run_once")
    # `enabled` | `suspended` | `disabled`.
    state: Mapped[str] = mapped_column(String(16), default="disabled")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    # Objetivo congelado no momento da aprovação (`frozen`) ou sempre a versão mais
    # recente da conversa/tarefa (`latest`).
    objective_mode: Mapped[str] = mapped_column(String(16), default="frozen")
    objective_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_sec: Mapped[float | None] = mapped_column(nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AutomationFiringModel(Base):
    """Disparo de uma automação: a unidade de trabalho registrada e recuperável.

    `idempotency_key` é único: reprocessar o mesmo disparo (reinício, retentativa,
    evento repetido) nunca cria uma segunda execução equivalente.
    """

    __tablename__ = "automation_firings"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_automation_firing_key"),
        Index("ix_automation_firings_automation", "automation_id"),
        Index("ix_automation_firings_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    # Instante teórico do disparo (UTC) — o que a chave de idempotência resume.
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # `pending` | `preparing` | `waiting_dependency` | `running` | `completed` |
    # `failed` | `blocked` | `skipped` | `cancelled`.
    state: Mapped[str] = mapped_column(String(24), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AutomationEventModel(Base):
    """Evento durável de automação: a entrada de adaptadores (webhook, arquivo, watcher).

    `dedupe_key` protege contra o mesmo evento chegar duas vezes (reconexão, retentativa
    do emissor). A entrega é idempotente: o gatilho de evento cria um disparo por evento.
    """

    __tablename__ = "automation_events"
    __table_args__ = (
        Index("ix_automation_events_type", "event_type"),
        Index("ix_automation_events_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="internal")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(191), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationAttemptModel(Base):
    """Tentativa de operação: chamada de modelo, de ferramenta ou de verificação, com o registro do pedido e da resposta."""

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
    """Evento persistido do run, com a sequência que permite a ressincronização do stream."""

    __tablename__ = "event_logs"
    __table_args__ = (Index("ix_event_logs_run_seq", "run_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MemoryRecordModel(Base):
    """Registro de memória do projeto, versionado e com resumo e outline para o prompt."""

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
    """Nó do grafo de conhecimento do projeto (arquivo, símbolo ou documento)."""

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
    """Aresta do grafo de conhecimento, com a relação entre dois nós do projeto."""

    __tablename__ = "kg_edges"
    __table_args__ = (UniqueConstraint("project_id", "src_id", "dst_id", "rel", name="uq_kg_edge"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kg_nodes.id"), nullable=False)
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kg_nodes.id"), nullable=False)
    rel: Mapped[str] = mapped_column(String(64), nullable=False)


class TaskContractModel(Base):
    """Contrato de entradas e saídas esperado de uma tarefa."""

    __tablename__ = "task_contracts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False, unique=True)
    inputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    invariants_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    acceptance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContextSnapshotModel(Base):
    """Instantâneo do contexto usado por uma tarefa: componentes, notas de estratégia e referências."""

    __tablename__ = "context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    components_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    strategy_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Composição estimada do que entrou no prompt, por categoria. Ausente em snapshots antigos.
    categories_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InferenceRecordModel(Base):
    """Uma inferência contabilizada: a unidade canônica do consumo de tokens.

    O total da execução é a soma destes registros. Estimativa, uso informado pelo
    provedor e métrica ausente ficam em colunas diferentes — ausência não vira zero.
    Tokens de cache e de raciocínio não entram de novo no total de entrada ou saída.
    """

    __tablename__ = "inference_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_inference_idempotency"),
        Index("ix_inference_run", "run_id"),
        Index("ix_inference_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    call_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # exact | estimate | partial | unavailable
    measurement: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("context_snapshots.id"), nullable=True
    )
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Instrumentação de contexto (Fase A)
    components_included_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_results_attached_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    external_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    compaction_events_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    budget_pressure: Mapped[bool] = mapped_column(Boolean, default=False)
    input_budget_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_reserve_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calibration_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceModel(Base):
    """Evidência de verificação: verificador, resultado (aprovado, reprovado ou inconclusivo) e detalhe."""

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


class AgentModel(Base):
    """Agente lógico: identidade, papel, instruções, permissões e responsabilidade.

    Existe independente da execução: um agente suspenso continua consultável e
    recuperável. A hierarquia é recursiva (`parent_id` aponta para outro agente) e não
    depende de uma quantidade fixa de gerações.
    """

    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_task", "task_id"), Index("ix_agents_parent", "parent_id"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    # Agente que delegou a este agente (o "pai" lógico).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    # Tarefa que este agente executa. A relação é 1:1 na prática, mas não por
    # restrição: o agente pode acompanhar a tarefa e continuar existindo depois dela.
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="worker")
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=AgentStatus.IDLE.value)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AgentExecutionModel(Base):
    """Execução: instância ativa que usa modelo, contexto e ferramentas.

    É o que ocupa memória de inferência. Quando termina, o que fica é o `checkpoint_json`
    — estado estruturado, não transcrição — e as referências a artefatos.
    """

    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_agent_executions_agent", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default=ExecutionStatus.PENDING.value)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    # Estado estruturado para retomar: objetivo, etapa, descobertas, decisões.
    checkpoint_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Referências a arquivos, trechos e artefatos examinados (o histórico bruto fica
    # nos eventos, que são a trilha de auditoria).
    context_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentQueryModel(Base):
    """Consulta de um agente a outro.

    Identificador, origem, destino, tarefa relacionada, estado, limite de tentativas e
    correlação da resposta — o que impede respostas associadas à tarefa errada.
    """

    __tablename__ = "agent_queries"
    __table_args__ = (
        Index("ix_agent_queries_target", "target_agent_id"),
        Index("ix_agent_queries_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    requester_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )
    # Agente que realmente respondeu (pode ser um descendente do alvo).
    answered_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    questions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), default=QueryStatus.PENDING.value)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeItemModel(Base):
    """Item de conhecimento adquirido e processado."""

    __tablename__ = "knowledge_items"
    __table_args__ = (
        Index("ix_knowledge_items_project", "project_id"),
        Index("ix_knowledge_items_kind", "kind"),
        Index("ix_knowledge_items_tech_version", "technology", "version"),
        Index("ix_knowledge_items_confidence", "confidence"),
        Index("ix_knowledge_items_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="fact")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    technology: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    validation_status: Mapped[str] = mapped_column(String(32), default="unvalidated")
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    sources: Mapped[list[KnowledgeSourceModel]] = relationship(back_populates="item", cascade="all, delete-orphan")
    validations: Mapped[list[KnowledgeValidationModel]] = relationship(back_populates="item", cascade="all, delete-orphan")
    usages: Mapped[list[KnowledgeUsageModel]] = relationship(back_populates="item", cascade="all, delete-orphan")
    versions: Mapped[list[KnowledgeVersionModel]] = relationship(back_populates="item", cascade="all, delete-orphan")


class KnowledgeSourceModel(Base):
    """Fonte de um item de conhecimento."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index("ix_knowledge_sources_item", "item_id"),
        Index("ix_knowledge_sources_kind", "source_kind"),
        Index("ix_knowledge_sources_url", "url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    credibility: Mapped[float] = mapped_column(Float, default=0.5)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    item: Mapped[KnowledgeItemModel] = relationship(back_populates="sources")


class KnowledgeRequestModel(Base):
    """Solicitação de aquisição de conhecimento."""

    __tablename__ = "knowledge_requests"
    __table_args__ = (
        Index("ix_knowledge_requests_project", "project_id"),
        Index("ix_knowledge_requests_task", "task_id"),
        Index("ix_knowledge_requests_agent", "agent_id"),
        Index("ix_knowledge_requests_status", "status"),
        Index("ix_knowledge_requests_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    constraints_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    desired_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    depth: Mapped[str] = mapped_column(String(16), default="standard")
    validation_criteria_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_acquisition_time_sec: Mapped[int] = mapped_column(Integer, default=120)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_items.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeValidationModel(Base):
    """Validação de um item de conhecimento."""

    __tablename__ = "knowledge_validations"
    __table_args__ = (
        Index("ix_knowledge_validations_item", "item_id"),
        Index("ix_knowledge_validations_status", "status"),
        Index("ix_knowledge_validations_kind", "validation_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    validation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unvalidated")
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criteria_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[KnowledgeItemModel] = relationship(back_populates="validations")


class KnowledgeRelationModel(Base):
    """Relação entre itens de conhecimento."""

    __tablename__ = "knowledge_relations"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation_type", name="uq_knowledge_relation"),
        Index("ix_knowledge_relations_source", "source_id"),
        Index("ix_knowledge_relations_target", "target_id"),
        Index("ix_knowledge_relations_type", "relation_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=1.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeUsageModel(Base):
    """Uso de um item de conhecimento em uma task/execução."""

    __tablename__ = "knowledge_usage"
    __table_args__ = (
        Index("ix_knowledge_usage_item", "item_id"),
        Index("ix_knowledge_usage_task", "task_id"),
        Index("ix_knowledge_usage_run", "run_id"),
        Index("ix_knowledge_usage_outcome", "outcome"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    success: Mapped[bool | None] = mapped_column(nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[KnowledgeItemModel] = relationship(back_populates="usages")


class KnowledgeVersionModel(Base):
    """Versão de um item de conhecimento (histórico de mudanças)."""

    __tablename__ = "knowledge_versions"
    __table_args__ = (
        Index("ix_knowledge_versions_item", "item_id"),
        Index("ix_knowledge_versions_number", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[KnowledgeItemModel] = relationship(back_populates="versions")


class BenchmarkScenarioModel(Base):
    """Cenário versionado de benchmark: objetivo, critérios de aceite e restrições de execução."""

    __tablename__ = "benchmark_scenarios"
    __table_args__ = (
        Index("ix_benchmark_scenarios_category", "category"),
        Index("ix_benchmark_scenarios_difficulty", "difficulty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context_initial_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tools_allowed_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_limit_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acceptance_criteria_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    validation_tests_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_benchmark_scenarios_id_version", "scenario_id", "version", unique=True),
    )


class BenchmarkExecutionModel(Base):
    """Execução de um benchmark: uma passagem de um cenário com um modelo/configuração."""

    __tablename__ = "benchmark_executions"
    __table_args__ = (
        Index("ix_benchmark_executions_scenario", "scenario_id"),
        Index("ix_benchmark_executions_model", "provider", "model_id"),
        Index("ix_benchmark_executions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_scenarios.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkResultModel(Base):
    """Resultado de uma execução de benchmark: métricas, pontuação e evidências."""

    __tablename__ = "benchmark_results"
    __table_args__ = (
        Index("ix_benchmark_results_execution", "execution_id"),
        Index("ix_benchmark_results_scenario", "scenario_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_executions.id"), nullable=False
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_scenarios.id"), nullable=False
    )
    task_completed: Mapped[bool] = mapped_column(default=False, nullable=False)
    requirements_satisfied: Mapped[int] = mapped_column(default=0, nullable=False)
    requirements_total: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    inference_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(default=0.0, nullable=False)
    latency_p50_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    latency_p95_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    tool_calls: Mapped[int] = mapped_column(default=0, nullable=False)
    recovery_count: Mapped[int] = mapped_column(default=0, nullable=False)
    peak_memory_mb: Mapped[float | None] = mapped_column(nullable=True)
    peak_vram_mb: Mapped[float | None] = mapped_column(nullable=True)
    scores_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiagnosticModel(Base):
    """Diagnóstico gerado a partir de evidências: gargalo, anomalia ou oportunidade de otimização."""

    __tablename__ = "diagnostics"
    __table_args__ = (
        Index("ix_diagnostics_category", "category"),
        Index("ix_diagnostics_severity", "severity"),
        Index("ix_diagnostics_state", "state"),
        Index("ix_diagnostics_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    diagnostic_id: Mapped[str] = mapped_column(String(100), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metric_affected: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_period_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    probable_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_state: Mapped[str] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TelemetryAggregateModel(Base):
    """Agregação temporal de métricas: preserva métricas calculadas com retenção distinta do histórico detalhado."""

    __tablename__ = "telemetry_aggregates"
    __table_args__ = (
        Index("ix_telemetry_aggregates_run_period", "run_id", "period_start"),
        Index("ix_telemetry_aggregates_metric", "metric_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_runs.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float | None] = mapped_column(nullable=True)
    p50: Mapped[float | None] = mapped_column(nullable=True)
    p95: Mapped[float | None] = mapped_column(nullable=True)
    p99: Mapped[float | None] = mapped_column(nullable=True)
    min_value: Mapped[float | None] = mapped_column(nullable=True)
    max_value: Mapped[float | None] = mapped_column(nullable=True)
    count: Mapped[int] = mapped_column(default=0, nullable=False)
    measurement_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

