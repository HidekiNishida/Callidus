# src/agent/orchestrator/decomposition.py — decomposição hierárquica
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import TaskCreate, TaskStatusUpdate
from agent.providers.base import LLMProvider
from agent.context.budget import ContextComponent, assemble_messages
from agent.providers.base import ChatCompletionRequest, ModelProfile
from agent.providers.mock import decomposition_json
from agent.services.task_service import TaskService
from agent.util.json_parse import parse_json_object


class SubTaskSpec(BaseModel):
    title: str
    objective: str
    kind: TaskKind = TaskKind.OPERATION
    scope: str | None = None
    acceptance_criteria: str | None = None
    metadata: dict[str, Any] | None = None
    depends_on_indices: list[int] = Field(default_factory=list)


class DecompositionResult(BaseModel):
    subtasks: list[SubTaskSpec]


BUILTIN_E2E_PLAN = DecompositionResult(
    subtasks=[
        SubTaskSpec(
            title="Inspecionar projeto",
            objective="Listar arquivos relevantes do projeto de teste",
            metadata={"tool": "search_grep", "tool_args": {"pattern": "def "}},
        ),
        SubTaskSpec(
            title="Corrigir implementação",
            objective="Corrigir bug em calc.py conforme critérios",
            metadata={
                "tool": "write_file",
                "tool_args": {
                    "path": "calc.py",
                    "content": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
            depends_on_indices=[0],
        ),
        SubTaskSpec(
            title="Verificar testes",
            objective="Executar pytest no fixture",
            metadata={
                "verification": {"type": "pytest", "path": "tests"},
            },
            depends_on_indices=[1],
        ),
    ]
)


async def plan_with_model(
    provider: LLMProvider,
    profile: ModelProfile,
    objective: str,
    context_snippet: str,
) -> DecompositionResult | None:
    prompt = (
        f"Objetivo: {objective}\n\nContexto:\n{context_snippet}\n\n"
        'Responda SOMENTE JSON: {"subtasks":[{"title":"...","objective":"...",'
        '"kind":"operation|subsystem","metadata":{},"depends_on_indices":[]}]}'
    )
    budget = assemble_messages(
        profile,
        [
            ContextComponent(name="objetivo", text=prompt, required=True, priority=100),
        ],
    )
    resp = await provider.chat(
        ChatCompletionRequest(messages=budget.messages, profile=profile)
    )
    data, err = parse_json_object(resp.content)
    if err or not data:
        return None
    try:
        return DecompositionResult.model_validate(data)
    except Exception:
        return None


def apply_decomposition(
    session: Session,
    project_id: uuid.UUID,
    parent_id: uuid.UUID,
    plan: DecompositionResult,
) -> list[uuid.UUID]:
    ts = TaskService(session)
    parent = ts.get_task(parent_id)
    if parent.status == TaskStatus.PENDING.value:
        ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.PLANNING))

    created_ids: list[uuid.UUID] = []
    for spec in plan.subtasks:
        task = ts.create_task(
            project_id,
            TaskCreate(
                title=spec.title,
                objective=spec.objective,
                scope=spec.scope,
                acceptance_criteria=spec.acceptance_criteria,
                kind=spec.kind,
                parent_id=parent_id,
                metadata=spec.metadata,
            ),
        )
        created_ids.append(task.id)

    for idx, spec in enumerate(plan.subtasks):
        for dep_idx in spec.depends_on_indices:
            if 0 <= dep_idx < len(created_ids):
                from agent.domain.schemas import TaskDependencyCreate

                ts.add_dependency(
                    created_ids[idx],
                    TaskDependencyCreate(depends_on_task_id=created_ids[dep_idx]),
                )

    return created_ids


def builtin_plan_for_objective(objective: str) -> DecompositionResult | None:
    if "e2e" in objective.lower() or "calc" in objective.lower():
        return BUILTIN_E2E_PLAN
    return None
