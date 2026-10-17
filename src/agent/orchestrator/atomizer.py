# src/agent/orchestrator/atomizer.py — decisão de atomização recursiva
from __future__ import annotations

from agent.domain.enums import TaskKind
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec


def complexity_score(*, objective: str, metadata: dict | None, kind: str, attempt_count: int) -> int:
    score = 0
    meta = metadata or {}
    score += min(len(objective) // 40, 5)
    score += len(meta.keys())
    if kind == TaskKind.SUBSYSTEM.value:
        score += 2
    if meta.get("model_operation"):
        score += 3
    if attempt_count >= 2:
        score += 2
    return score


def should_decompose_further(
    *,
    objective: str,
    metadata: dict | None,
    kind: str,
    attempt_count: int,
    has_children: bool,
    threshold: int = 4,
) -> bool:
    if has_children:
        return False
    meta = metadata or {}
    if meta.get("tool") or meta.get("verification") or meta.get("atomic"):
        return False
    return complexity_score(
        objective=objective, metadata=metadata, kind=kind, attempt_count=attempt_count
    ) >= threshold


def micro_decompose_operation(objective: str) -> DecompositionResult:
    """Plano determinístico para operações complexas sem LLM."""
    return DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Inspecionar contexto",
                objective=f"Buscar símbolos relacionados: {objective[:120]}",
                metadata={"tool": "search_grep", "tool_args": {"pattern": "def "}, "atomic": True},
            ),
            SubTaskSpec(
                title="Executar alteração",
                objective=objective,
                metadata={"model_operation": True, "atomic": True},
                depends_on_indices=[0],
            ),
            SubTaskSpec(
                title="Verificar alteração",
                objective="Rodar verificação mínima",
                metadata={"verification": {"type": "pytest", "path": "."}, "atomic": True},
                depends_on_indices=[1],
            ),
        ]
    )
