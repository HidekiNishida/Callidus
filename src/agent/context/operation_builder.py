# src/agent/context/operation_builder.py — Context Builder por operação
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from agent.context.assembler import build_operation_context
from agent.context.budget import BudgetResult
from agent.domain.enums import MemoryKind
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.knowledge.indexer import grep_symbols_in_objective
from agent.persistence.models import ContextSnapshotModel, MemoryRecordModel, TaskModel
from agent.providers.base import ModelProfile
from agent.security.paths import PathSecurityError, resolve_under_root
from sqlalchemy import select


GLOBAL_RULES = (
    "Responda de forma concisa. Use ferramentas apenas quando autorizado. "
    "Não invente arquivos ou testes executados."
)


class OperationContextBuilder:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._kg = KnowledgeGraphService(session)

    def build_for_task(
        self,
        *,
        project_id: uuid.UUID,
        root_path: str,
        task: TaskModel,
        profile: ModelProfile,
        run_id: uuid.UUID | None = None,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        project_rules = self._memory_block(project_id, MemoryKind.CANONICAL)
        technical = self._technical_snippet(root_path, project_id, task.objective)
        acceptance = task.acceptance_criteria or "Atender o objetivo sem violar requisitos canônicos."
        tools_summary = "Ferramentas locais: read_file, write_file, search_grep, run_pytest, git_diff."
        output_format = '{"path":"...","content":"..."}' if (task.metadata_json or {}).get("model_operation") else "JSON estruturado quando solicitado."

        budget = build_operation_context(
            profile,
            global_rules=GLOBAL_RULES,
            project_rules=project_rules,
            objective=task.objective,
            technical=technical,
            acceptance=acceptance,
            tools_summary=tools_summary,
            output_format=output_format,
        )
        components = [{"role": m.role, "chars": len(m.content)} for m in budget.messages]

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task.id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=components,
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
        )
        self._session.add(snap)
        self._session.flush()
        return budget, snap

    def _memory_block(self, project_id: uuid.UUID, kind: MemoryKind) -> str:
        stmt = (
            select(MemoryRecordModel)
            .where(MemoryRecordModel.project_id == project_id, MemoryRecordModel.kind == kind.value)
            .order_by(MemoryRecordModel.created_at.desc())
            .limit(5)
        )
        rows = list(self._session.scalars(stmt).all())
        if not rows:
            return "(sem memória canônica registrada)"
        return "\n".join(f"- {r.title}: {r.content[:400]}" for r in rows)

    def _technical_snippet(self, root_path: str, project_id: uuid.UUID, objective: str) -> str:
        parts: list[str] = []
        for token in grep_symbols_in_objective(objective)[:8]:
            hits = self._kg.search(project_id, token, limit=3)
            for h in hits:
                parts.append(f"[{h['kind']}] {h['ref']}")
        root = Path(root_path).expanduser().resolve()
        for hint in ("calc.py", "main.py", "app.py"):
            if hint in objective.lower():
                try:
                    full = resolve_under_root(root, hint)
                    if full.is_file():
                        text = full.read_text(encoding="utf-8", errors="replace")
                        parts.append(f"--- {hint} (trecho) ---\n" + text[:1200])
                except PathSecurityError:
                    pass
        return "\n".join(parts) if parts else "(nenhum trecho automático; use grep na operação anterior)"
