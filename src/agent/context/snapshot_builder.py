"""
Arquivo: src/agent/context/snapshot_builder.py
Nome: snapshot_builder.py
Propósito: construir e persistir snapshots de contexto para diferentes finalidades de inferência.
Responsabilidade: camada de aplicação — centraliza a criação de ContextSnapshotModel para garantir rastreabilidade.
Componentes: SnapshotBuilder, build_plan_snapshot, build_operation_snapshot, build_final_answer_snapshot, build_automation_snapshot, build_agent_query_snapshot.
Dependências: agent.context.assembler, agent.context.budget, agent.persistence.models, agent.providers.base.
Observações: cada finalidade tem seu próprio construtor de componentes; o snapshot é gravado e seu ID retornado para bind_snapshot.
OperationContextBuilder é importado preguiçosamente para evitar importação circular.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.context.assembler import build_operation_context
from agent.context.budget import BudgetResult, ContextComponent
from agent.persistence.models import ContextSnapshotModel, TaskModel
from agent.providers.base import ModelProfile


def _group_categories(selected: list) -> list[dict]:
    """Agrupa componentes selecionados por categoria para o snapshot.
    
    Aceita tanto objetos ContextComponent quanto dicionários (como retornado por assemble_messages).
    """
    from collections import defaultdict
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for comp in selected:
        if hasattr(comp, 'category'):
            cat = comp.category
            name = comp.name
            tokens = getattr(comp, 'tokens', None)
            if tokens is None:
                # ContextComponent não carrega tokens: sem medir o texto, cada fatia da
                # barra de composição tinha largura zero e a barra aparecia vazia.
                from agent.providers.base import estimate_text_tokens

                tokens = estimate_text_tokens(comp.text or "")
            required = comp.required
            priority = comp.priority
        else:
            cat = comp.get('category', 'other')
            name = comp.get('name', 'unknown')
            tokens = comp.get('tokens', 0)
            required = comp.get('required', False)
            priority = comp.get('priority', 50)
        comp_dict = {
            "name": name,
            "required": required,
            "priority": priority,
        }
        if tokens is not None:
            comp_dict["tokens"] = tokens
        by_cat[cat].append(comp_dict)
    return [
        {"category": cat, "components": comps}
        for cat, comps in by_cat.items()
    ]


class SnapshotBuilder:
    """Construtor unificado de snapshots de contexto para diferentes finalidades."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def build_plan_snapshot(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        run_id: uuid.UUID | None,
        profile: ModelProfile,
        messages: list,
        purpose: str = "plan",
        components: list[ContextComponent] | None = None,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Constrói snapshot para inferência de planejamento (decomposição, análise de lacunas, revisão final)."""
        budget = self._budget_from_messages(profile, messages, purpose, components)

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=[{"role": m.role, "chars": len(m.content)} for m in budget.messages],
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
            categories_json=_group_categories(budget.selected),
        )
        self._session.add(snap)
        self._session.flush()
        return budget, snap

    def build_operation_snapshot(
        self,
        *,
        project_id: uuid.UUID,
        task: TaskModel,
        profile: ModelProfile,
        run_id: uuid.UUID | None,
        root_path: str,
        settings: Any = None,
        compact: bool = False,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Constrói snapshot para inferência de operação (model_operation). Usa OperationContextBuilder."""
        from agent.context.operation_builder import OperationContextBuilder
        builder = OperationContextBuilder(self._session, settings)
        return builder.build_for_task(
            project_id=project_id,
            root_path=root_path,
            task=task,
            profile=profile,
            run_id=run_id,
            compact=compact,
        )

    def build_final_answer_snapshot(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        run_id: uuid.UUID | None,
        profile: ModelProfile,
        messages: list,
        purpose: str = "final_answer",
        components: list[ContextComponent] | None = None,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Constrói snapshot para inferência de resposta final (executor.py)."""
        budget = self._budget_from_messages(profile, messages, purpose, components)

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=[{"role": m.role, "chars": len(m.content)} for m in budget.messages],
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
            categories_json=_group_categories(budget.selected),
        )
        self._session.add(snap)
        self._session.flush()
        return budget, snap

    def build_automation_snapshot(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        run_id: uuid.UUID | None,
        profile: ModelProfile,
        messages: list,
        purpose: str = "automation",
        components: list[ContextComponent] | None = None,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Constrói snapshot para inferência de automação."""
        budget = self._budget_from_messages(profile, messages, purpose, components)

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=[{"role": m.role, "chars": len(m.content)} for m in budget.messages],
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
            categories_json=_group_categories(budget.selected),
        )
        self._session.add(snap)
        self._session.flush()
        return budget, snap

    def build_agent_query_snapshot(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        run_id: uuid.UUID | None,
        profile: ModelProfile,
        messages: list,
        purpose: str = "agent_query",
        components: list[ContextComponent] | None = None,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Constrói snapshot para consulta de agente (query_service.py)."""
        budget = self._budget_from_messages(profile, messages, purpose, components)

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=[{"role": m.role, "chars": len(m.content)} for m in budget.messages],
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
            categories_json=_group_categories(budget.selected),
        )
        self._session.add(snap)
        self._session.flush()
        return budget, snap

    def _budget_from_messages(
        self,
        profile: ModelProfile,
        messages: list,
        purpose: str,
        components: list[ContextComponent] | None = None,
    ) -> BudgetResult:
        """Reconstrói um BudgetResult a partir de mensagens já montadas.
        
        Se components forem fornecidos, usa eles para popular selected/categories.
        Caso contrário, reconstrói componentes a partir das mensagens, classificando por papel.
        """
        from agent.context.budget import BudgetResult, ContextComponent
        from agent.providers.base import estimate_text_tokens

        # Estimativa simples: soma dos caracteres / 4 (aproximação)
        total_chars = sum(len(m.content or "") for m in messages)
        estimated_tokens = max(1, total_chars // 4)

        if components:
            selected = components
        else:
            # Reconstrói componentes a partir das mensagens efetivamente enviadas
            # Isso garante que sempre haja composição quando existem mensagens
            selected = []
            for msg in messages:
                role = getattr(msg, 'role', 'unknown')
                content = getattr(msg, 'content', '') or ''
                if not content.strip():
                    continue
                tokens = estimate_text_tokens(content)
                category = _role_to_category(role)
                selected.append(
                    ContextComponent(
                        name=f"Mensagem {role}",
                        text=content,
                        priority=50,
                        required=role == "system",
                        category=category,
                    )
                )

        return BudgetResult(
            messages=messages,
            selected=selected,
            dropped=[],
            estimated_tokens=estimated_tokens,
            strategy_notes=[f"purpose={purpose}", "reconstructed_from_messages"],
        )


def _role_to_category(role: str) -> str:
    """Mapeia papel da mensagem para categoria de composição."""
    mapping = {
        "system": "instructions",
        "user": "objective",
        "assistant": "history",
        "tool": "tool_results",
    }
    return mapping.get(role, "other")


def create_snapshot_for_inference(
    session: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    run_id: uuid.UUID | None,
    profile: ModelProfile,
    messages: list,
    purpose: str,
    task: TaskModel | None = None,
    root_path: str | None = None,
    settings: Any = None,
    compact: bool = False,
    components: list[ContextComponent] | None = None,
) -> tuple[BudgetResult, ContextSnapshotModel]:
    """Factory que escolhe o construtor apropriado baseado na finalidade.
    
    Args:
        session: sessão do banco.
        project_id: projeto da inferência.
        task_id: tarefa da inferência.
        run_id: execução da inferência.
        profile: perfil do modelo.
        messages: mensagens que serão enviadas ao modelo.
        purpose: finalidade da inferência (plan, operation, final_answer, automation, agent_query).
        task: TaskModel completa (necessário para operation).
        root_path: raiz do projeto (necessário para operation).
        settings: configurações do processo (necessário para operation).
        compact: se deve compactar o contexto (operation).
        components: componentes de contexto opcionais (para popular categories_json do snapshot).
    
    Returns:
        Tupla (budget, snapshot) pronta para uso com bind_snapshot.
    """
    builder = SnapshotBuilder(session)
    
    if purpose == "operation":
        if task is None or root_path is None:
            raise ValueError("operation requires task and root_path")
        return builder.build_operation_snapshot(
            project_id=project_id,
            task=task,
            profile=profile,
            run_id=run_id,
            root_path=root_path,
            settings=settings,
            compact=compact,
        )
    elif purpose in ("plan", "decompose", "gap_analysis", "final_review"):
        return builder.build_plan_snapshot(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            profile=profile,
            messages=messages,
            purpose=purpose,
            components=components,
        )
    elif purpose == "final_answer":
        return builder.build_final_answer_snapshot(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            profile=profile,
            messages=messages,
            purpose=purpose,
            components=components,
        )
    elif purpose == "automation":
        return builder.build_automation_snapshot(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            profile=profile,
            messages=messages,
            purpose=purpose,
            components=components,
        )
    elif purpose == "agent_query":
        return builder.build_agent_query_snapshot(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            profile=profile,
            messages=messages,
            purpose=purpose,
            components=components,
        )
    else:
        # Fallback genérico
        return builder.build_plan_snapshot(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            profile=profile,
            messages=messages,
            purpose=purpose,
            components=components,
        )