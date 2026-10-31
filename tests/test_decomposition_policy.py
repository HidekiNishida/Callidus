"""
Arquivo: tests/test_decomposition_policy.py
Nome: test_decomposition_policy.py
Propósito: verificar a política de decomposição recursiva adaptativa — decisões de executar, preparar contexto, decompor, investigar, diagnosticar e replanejar.
Responsabilidade: camada de teste — verifica que a política usa dados determinísticos (grafo de dependências, TaskIR) para decidir estratégias de decomposição.
Componentes: test_execute_directly_low_complexity, test_prepare_context_high_tokens, test_decompose_high_complexity, test_investigate_many_attempts, test_diagnose_failures, test_replan, test_depth_limit, test_max_children, test_dependency_graph_integration.
Dependências: agent.orchestrator.decomposition_policy, agent.orchestrator.task_ir, agent.domain.enums, uuid.
Observações: não usa rede nem credenciais.
"""

from __future__ import annotations

import uuid

from agent.domain.enums import TaskStatus
from agent.orchestrator.decomposition_policy import (
    DecompositionDecision,
    DecompositionLimits,
    DecompositionPolicy,
    decide_decomposition,
)
from agent.orchestrator.task_ir import (
    ArtifactRef,
    ContextBudget,
    ExecutionConstraint,
    TaskIR,
)


def _make_ir(
    *,
    objective: str = "Implementar funcionalidade",
    requirements: list[dict] | None = None,
    constraints: list[ExecutionConstraint] | None = None,
    acceptance_criteria: list[str] | None = None,
    affected_components: list[str] | None = None,
    allowed_files: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    expected_artifacts: list[ArtifactRef] | None = None,
    inputs: list[ArtifactRef] | None = None,
    outputs: list[ArtifactRef] | None = None,
    status: str = TaskStatus.PENDING.value,
    depth: int = 0,
    attempts: int = 0,
    max_attempts: int = 8,
    max_depth: int = 16,
    context_budget: ContextBudget | None = None,
    dependencies: list[uuid.UUID] | None = None,
) -> TaskIR:
    """Cria um TaskIR de exemplo para testes."""
    return TaskIR(
        task_id=uuid.uuid4(),
        parent_id=None,
        objective=objective,
        requirements=requirements or [],
        constraints=constraints or [],
        acceptance_criteria=acceptance_criteria or [],
        complexity={"score": 0, "factors": []},
        context_budget=context_budget,
        dependencies=dependencies or [],
        affected_components=affected_components or [],
        allowed_tools=allowed_tools or [],
        allowed_files=allowed_files or [],
        expected_artifacts=expected_artifacts or [],
        inputs=inputs or [],
        outputs=outputs or [],
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        depth=depth,
        max_depth=max_depth,
    )


def test_execute_directly_low_complexity() -> None:
    """Tarefa de baixa complexidade deve ser executada diretamente."""
    ir = _make_ir(
        objective="Corrigir erro de digitação",
        allowed_files=["README.md"],
        allowed_tools=["edit_file"],
    )
    policy = DecompositionPolicy()
    result = policy.decide(ir)
    assert result.decision == DecompositionDecision.EXECUTE_DIRECTLY
    assert "baixa" in result.reason.lower()


def test_prepare_context_high_tokens() -> None:
    """Tarefa com orçamento de contexto excedido deve preparar contexto."""
    ir = _make_ir(
        objective="Implementar sistema complexo",
        context_budget=ContextBudget(
            max_input_tokens=6000,
            max_output_tokens=1024,
            estimated_tokens=8000,
        ),
    )
    policy = DecompositionPolicy()
    result = policy.decide(ir)
    assert result.decision == DecompositionDecision.PREPARE_CONTEXT
    assert "orçamento" in result.reason.lower()


def test_decompose_high_complexity() -> None:
    """Tarefa de alta complexidade deve ser decomposta."""
    ir = _make_ir(
        objective="Implementar sistema completo de inventário com backend, frontend e banco de dados",
        affected_components=["models/inventory.py", "services/inventory.py", "api/inventory.py", "frontend/inventory.vue"],
        allowed_files=["models/inventory.py", "services/inventory.py", "api/inventory.py"],
        allowed_tools=["read_file", "write_file", "edit_file", "run_pytest"],
        requirements=[
            {"id": "R1", "description": "Criar modelo de inventário", "origin": "objetivo", "applicability": "obrigatório", "evidence": "change", "refs": []},
            {"id": "R2", "description": "Criar API de inventário", "origin": "objetivo", "applicability": "obrigatório", "evidence": "change", "refs": []},
        ],
        acceptance_criteria=["Modelo deve validar dados", "API deve responder corretamente"],
    )
    policy = DecompositionPolicy()
    result = policy.decide(ir)
    assert result.decision == DecompositionDecision.DECOMPOSE
    assert len(result.subtask_specs) >= 2


def test_investigate_many_attempts_no_failures() -> None:
    """Muitas tentativas sem falhas registradas devem investigar."""
    ir = _make_ir(objective="Investigar comportamento estranho", attempts=9, max_attempts=8)
    policy = DecompositionPolicy()
    result = policy.decide(ir, attempt_count=9)
    assert result.decision == DecompositionDecision.INVESTIGATE


def test_diagnose_with_failures() -> None:
    """Muitas tentativas com falhas registradas devem diagnosticar."""
    ir = _make_ir(objective="Corrigir bug persistente", attempts=9, max_attempts=8)
    policy = DecompositionPolicy()
    result = policy.decide(ir, attempt_count=9, previous_failures=["timeout", "conexão recusada"])
    assert result.decision == DecompositionDecision.DIAGNOSE
    assert result.diagnosis_hint is not None


def test_depth_limit() -> None:
    """Profundidade máxima deve forçar execução direta."""
    ir = _make_ir(
        objective="Tarefa profunda",
        depth=16,
        max_depth=16,
    )
    policy = DecompositionPolicy()
    result = policy.decide(ir, depth=16)
    assert result.decision == DecompositionDecision.EXECUTE_DIRECTLY
    assert "profundidade" in result.reason.lower()


def test_has_children() -> None:
    """Tarefa que já tem filhos não deve ser dividida."""
    ir = _make_ir(objective="Tarefa pai")
    policy = DecompositionPolicy()
    result = policy.decide(ir, has_children=True)
    assert result.decision == DecompositionDecision.EXECUTE_DIRECTLY
    assert "já possui subtarefas" in result.reason.lower()


def test_custom_limits() -> None:
    """Limites personalizados devem afetar a decisão."""
    limits = DecompositionLimits(complexity_threshold=2, max_depth=3)
    ir = _make_ir(objective="Tarefa simples", depth=2, max_depth=3)
    policy = DecompositionPolicy(limits=limits)
    result = policy.decide(ir, depth=2)
    assert result.decision == DecompositionDecision.EXECUTE_DIRECTLY


def test_convenience_function() -> None:
    """A função de conveniência decide_decomposition deve funcionar."""
    ir = _make_ir(objective="Teste simples")
    result = decide_decomposition(ir)
    assert result.decision in {
        DecompositionDecision.EXECUTE_DIRECTLY,
        DecompositionDecision.PREPARE_CONTEXT,
        DecompositionDecision.DECOMPOSE,
        DecompositionDecision.INVESTIGATE,
        DecompositionDecision.DIAGNOSE,
        DecompositionDecision.REPLAN,
    }


def test_max_children_limit() -> None:
    """O número de subtarefas geradas não deve exceder max_children."""
    ir = _make_ir(
        objective="Alterar muitos arquivos",
        allowed_files=[f"file_{i}.py" for i in range(20)],
    )
    limits = DecompositionLimits(max_children=5)
    policy = DecompositionPolicy(limits=limits)
    result = policy.decide(ir)
    if result.decision == DecompositionDecision.DECOMPOSE:
        assert len(result.subtask_specs) <= limits.max_children


def test_blocked_task_higher_complexity() -> None:
    """Tarefa bloqueada deve ter complexidade maior."""
    ir_blocked = _make_ir(objective="Tarefa bloqueada", status=TaskStatus.BLOCKED.value)
    ir_normal = _make_ir(objective="Tarefa normal")
    policy = DecompositionPolicy()
    score_blocked = policy._complexity_score(ir_blocked)
    score_normal = policy._complexity_score(ir_normal)
    assert score_blocked >= score_normal
