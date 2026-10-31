"""
Arquivo: src/agent/orchestrator/task_ir.py
Nome: task_ir.py
Propósito: representação intermediária (IR) de tarefas — versão, hierarquia, dependências, requisitos rastreáveis, orçamento de contexto e contratos de entrada/saída.
Responsabilidade: camada de aplicação — IR persistente e independente do modelo, usada pelo compilador de tarefas e pelo orquestrador para decompor, executar e validar unidades de trabalho.
Componentes: TaskIR, IRSchema, ArtifactRef, RequirementLink, ContextBudget, ExecutionConstraint, to_ir, from_ir, apply_ir_to_task.
Dependências: agent.domain.enums, agent.persistence.models, pydantic, uuid.
Observações: o IR não armazena grandes conteúdos — usa referências (artifact://, file://) para documentos, arquivos e artefatos persistidos.
"""

from __future__ import annotations

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent.domain.enums import TaskKind, TaskStatus


class IRSchema(StrEnum):
    """Versão do esquema do IR."""

    V1 = "1"


class ArtifactRef(BaseModel):
    """Referência a um artefato persistido (arquivo, diff, resultado de teste, decisão técnica).

    Atributos:
        uri: identificador do artefato (ex: artifact://inventory_model, file://services/inventory.py).
        kind: tipo do artefato (file, diff, test_result, decision, contract, evidence).
        description: descrição legível do conteúdo.
        hash: SHA-256 opcional do conteúdo para validação de integridade.
    """

    uri: str
    kind: str
    description: str = ""
    hash: str | None = None


class RequirementLink(BaseModel):
    """Ligação de rastreabilidade entre um requisito e uma tarefa/implementação/teste.

    Atributos:
        req_id: identificador do requisito (ex: R1).
        task_ids: tarefas que implementam o requisito.
        evidence_ids: evidências que comprovam o requisito.
        test_ids: testes que validam o requisito.
        status: status de rastreamento (pending, implemented, tested, verified, obsolete).
    """

    req_id: str
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    test_ids: list[uuid.UUID] = Field(default_factory=list)
    status: str = "pending"


class ContextBudget(BaseModel):
    """Orçamento de contexto para uma operação do modelo.

    Atributos:
        max_input_tokens: limite de tokens de entrada.
        max_output_tokens: reserva de saída.
        estimated_tokens: estimativa atual de uso.
        components: nomes dos componentes incluídos no contexto.
        dropped: nomes dos componentes descartados por falta de orçamento.
    """

    max_input_tokens: int
    max_output_tokens: int
    estimated_tokens: int = 0
    components: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)


class ExecutionConstraint(BaseModel):
    """Restrição de execução de uma tarefa.

    Atributos:
        kind: tipo da restrição (read_only, protect_tests, no_network, max_attempts, max_depth, max_tokens).
        value: valor da restrição.
        description: descrição legível.
    """

    kind: str
    value: Any
    description: str = ""


class TaskIR(BaseModel):
    """Representação intermediária de uma tarefa.

    É persistente, versionada e independente do modelo utilizado. Permite hierarquia,
    dependências, requisitos rastreáveis, critérios de aceitação, limites de contexto,
    restrições de execução, ferramentas autorizadas, arquivos envolvidos, artefatos esperados,
    estado e histórico, e evidências de conclusão.

    Atributos:
        schema_version: versão do esquema do IR.
        task_id: identificador único da tarefa.
        parent_id: identificador da tarefa-pai (None para raiz).
        objective: objetivo da tarefa.
        requirements: requisitos originais.
        constraints: restrições de execução.
        acceptance_criteria: critérios de aceitação.
        complexity: pontuação e fatores de complexidade.
        context_budget: orçamento de contexto.
        dependencies: IDs de tarefas das quais depende.
        affected_components: componentes afetados.
        allowed_tools: ferramentas autorizadas.
        allowed_files: arquivos permitidos para leitura/escrita.
        expected_artifacts: artefatos que deverá entregar.
        inputs: referências de entrada (contratos, artefatos).
        outputs: referências de saída esperadas.
        status: estado da tarefa.
        attempts: número de tentativas.
        max_attempts: limite de tentativas.
        depth: profundidade na árvore.
        max_depth: profundidade máxima permitida.
        created_at: timestamp de criação.
        updated_at: timestamp de atualização.
        completed_at: timestamp de conclusão.
        result: resultado estruturado (status, resumo, artefatos, decisões, testes, evidências, problemas, próximos passos).
        trace_links: ligações de rastreabilidade de requisitos.
    """

    schema_version: str = IRSchema.V1
    task_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_id: uuid.UUID | None = None
    objective: str
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[ExecutionConstraint] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    complexity: dict[str, Any] = Field(default_factory=dict)
    context_budget: ContextBudget | None = None
    dependencies: list[uuid.UUID] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_files: list[str] = Field(default_factory=list)
    expected_artifacts: list[ArtifactRef] = Field(default_factory=list)
    inputs: list[ArtifactRef] = Field(default_factory=list)
    outputs: list[ArtifactRef] = Field(default_factory=list)
    status: str = TaskStatus.PENDING.value
    attempts: int = 0
    max_attempts: int = 8
    depth: int = 0
    max_depth: int = 16
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    trace_links: list[RequirementLink] = Field(default_factory=list)


def to_ir(task_id: uuid.UUID, task: Any, session: Any) -> TaskIR:
    """Converte um TaskModel do banco para um TaskIR.

    Args:
        task_id: identificador da tarefa.
        task: instância de TaskModel.
        session: sessão SQLAlchemy para carregar dependências e contratos.

    Returns:
        O TaskIR correspondente.
    """
    from agent.services.contract_service import ContractService

    metadata = task.metadata_json or {}
    contract = ContractService(session).get(task_id)

    return TaskIR(
        task_id=task_id,
        parent_id=task.parent_id,
        objective=task.objective,
        requirements=(contract.acceptance_json or {}).get("requirements", []) if contract else [],
        constraints=[
            ExecutionConstraint(kind=k, value=v, description="")
            for k, v in (metadata.get("constraints") or {}).items()
        ],
        acceptance_criteria=[task.acceptance_criteria] if task.acceptance_criteria else [],
        complexity=metadata.get("complexity", {}),
        context_budget=(
            ContextBudget(**metadata["context_budget"])
            if metadata.get("context_budget")
            else None
        ),
        dependencies=metadata.get("dependencies", []),
        affected_components=metadata.get("affected_components", []),
        allowed_tools=metadata.get("allowed_tools", []),
        allowed_files=metadata.get("allowed_files", []),
        expected_artifacts=[
            ArtifactRef(uri=a["uri"], kind=a["kind"], description=a.get("description", ""), hash=a.get("hash"))
            for a in metadata.get("expected_artifacts", [])
        ],
        inputs=[
            ArtifactRef(uri=i["uri"], kind=i["kind"], description=i.get("description", ""), hash=i.get("hash"))
            for i in metadata.get("inputs", [])
        ],
        outputs=[
            ArtifactRef(uri=o["uri"], kind=o["kind"], description=o.get("description", ""), hash=o.get("hash"))
            for o in metadata.get("outputs", [])
        ],
        status=task.status,
        attempts=metadata.get("attempts", 0),
        max_attempts=metadata.get("max_attempts", 8),
        depth=metadata.get("depth", 0),
        max_depth=metadata.get("max_depth", 16),
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        result=task.consolidated_result_json,
        trace_links=[
            RequirementLink(
                req_id=t["req_id"],
                task_ids=[uuid.UUID(tid) for tid in t.get("task_ids", [])],
                evidence_ids=[uuid.UUID(eid) for eid in t.get("evidence_ids", [])],
                test_ids=[uuid.UUID(tid) for tid in t.get("test_ids", [])],
                status=t.get("status", "pending"),
            )
            for t in metadata.get("trace_links", [])
        ],
    )


def from_ir(ir: TaskIR, session: Any, project_id: uuid.UUID, parent_id: uuid.UUID | None = None) -> Any:
    """Aplica um TaskIR a um TaskModel do banco (cria ou atualiza).

    Args:
        ir: representação intermediária da tarefa.
        session: sessão SQLAlchemy.
        project_id: identificador do projeto.
        parent_id: identificador da tarefa-pai (sobrepõe ir.parent_id se fornecido).

    Returns:
        A instância de TaskModel criada ou atualizada.
    """
    from agent.domain.schemas import TaskCreate, TaskStatusUpdate
    from agent.services.task_service import TaskService

    ts = TaskService(session)
    metadata = {
        "complexity": ir.complexity,
        "constraints": {c.kind: c.value for c in ir.constraints},
        "context_budget": ir.context_budget.model_dump() if ir.context_budget else None,
        "dependencies": [str(d) for d in ir.dependencies],
        "affected_components": ir.affected_components,
        "allowed_tools": ir.allowed_tools,
        "allowed_files": ir.allowed_files,
        "expected_artifacts": [a.model_dump() for a in ir.expected_artifacts],
        "inputs": [i.model_dump() for i in ir.inputs],
        "outputs": [o.model_dump() for o in ir.outputs],
        "attempts": ir.attempts,
        "max_attempts": ir.max_attempts,
        "depth": ir.depth,
        "max_depth": ir.max_depth,
        "trace_links": [
            {
                "req_id": tl.req_id,
                "task_ids": [str(t) for t in tl.task_ids],
                "evidence_ids": [str(e) for e in tl.evidence_ids],
                "test_ids": [str(t) for t in tl.test_ids],
                "status": tl.status,
            }
            for tl in ir.trace_links
        ],
    }

    if session.get(TaskModel, ir.task_id) is not None:
        ts.update_status(ir.task_id, TaskStatusUpdate(status=ir.status))
        task = session.get(TaskModel, ir.task_id)
        task.metadata_json = metadata
        task.consolidated_result_json = ir.result
        task.completed_at = ir.completed_at
        session.flush()
        return task

    task = ts.create_task(
        project_id,
        TaskCreate(
            title=ir.objective[:120],
            objective=ir.objective,
            scope=None,
            acceptance_criteria="\n".join(ir.acceptance_criteria) or None,
            kind=TaskKind.OPERATION,
            parent_id=parent_id or ir.parent_id,
            metadata=metadata,
        ),
    )
    # Garante que o ID criado bate com o do IR (quando possível)
    return task


def apply_ir_to_task(session: Any, ir: TaskIR, project_id: uuid.UUID) -> uuid.UUID:
    """Cria ou atualiza uma tarefa no banco a partir de um TaskIR.

    Args:
        session: sessão SQLAlchemy.
        ir: representação intermediária.
        project_id: identificador do projeto.

    Returns:
        O identificador da tarefa criada ou atualizada.
    """
    task = from_ir(ir, session, project_id)
    session.flush()
    return task.id
