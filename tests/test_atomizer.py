"""
Arquivo: tests/test_atomizer.py
Nome: test_atomizer.py
Propósito: Verificar as decisões do atomizador sobre quando decompor e como montar o plano mínimo.
Responsabilidade: camada de testes — critérios de decomposição de operação atômica e o conteúdo do micro plano.
Componentes: operação atômica que não decompõe, micro plano com três passos e decomposição após tentativas.
Dependências: agent.orchestrator.atomizer e agent.domain.enums.TaskKind.
Observações: funções puras: nenhum banco, rede ou relógio é usado.
"""

from agent.domain.enums import TaskKind
from agent.orchestrator.atomizer import micro_decompose_operation, should_decompose_further


def test_atomic_tool_skips_decompose():
    """Uma operação atômica já existente não é decomposta de novo."""
    assert not should_decompose_further(
        objective="long objective " * 20,
        metadata={"tool": "read_file"},
        kind=TaskKind.OPERATION.value,
        attempt_count=0,
        has_children=False,
    )


def test_micro_plan_has_three_steps():
    """O micro plano tem três passos e o passo do meio é uma operação de modelo."""
    plan = micro_decompose_operation("Implementar serviço X")
    assert len(plan.subtasks) == 3
    assert plan.subtasks[1].metadata.get("model_operation")


def test_decompose_after_retries():
    """Uma tarefa que já falhou várias vezes passa a ser decomposta."""
    assert should_decompose_further(
        objective="x" * 200,
        metadata={},
        kind=TaskKind.OBJECTIVE.value,
        attempt_count=3,
        has_children=False,
    )
