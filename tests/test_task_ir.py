"""
Arquivo: tests/test_task_ir.py
Nome: test_task_ir.py
Propósito: verificar a representação intermediária (IR) de tarefas — serialização, conversão para/do modelo, requisitos rastreáveis e orçamento de contexto.
Responsabilidade: camada de teste — verifica que o TaskIR é um contrato estável e versionado independente do modelo.
Componentes: test_ir_serialization, test_ir_to_from_model, test_ir_requirement_traceability, test_ir_context_budget.
Dependências: agent.orchestrator.task_ir, agent.persistence.models, agent.domain.enums, pydantic, uuid.
Observações: não usa rede nem credenciais; banco temporário por teste.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import TypeAdapter

from agent.domain.enums import TaskKind, TaskStatus
from agent.orchestrator.task_ir import (
    ArtifactRef,
    ContextBudget,
    ExecutionConstraint,
    IRSchema,
    RequirementLink,
    TaskIR,
    to_ir,
)


def _make_ir() -> TaskIR:
    """Cria um TaskIR de exemplo para testes."""
    return TaskIR(
        task_id=uuid.uuid4(),
        parent_id=None,
        objective="Implementar validação de estoque",
        requirements=[
            {"id": "R1", "description": "Não permitir saldo negativo", "origin": "objetivo", "applicability": "obrigatório", "evidence": "change", "refs": []}
        ],
        constraints=[
            ExecutionConstraint(kind="read_only", value=False, description="Permite escrita"),
            ExecutionConstraint(kind="max_attempts", value=5, description="Limite de tentativas"),
        ],
        acceptance_criteria=["Saldo insuficiente deve ser rejeitado", "Operações válidas devem continuar funcionando"],
        complexity={"score": 6, "factors": ["acoplamento", "arquivos_afetados"]},
        context_budget=ContextBudget(max_input_tokens=6000, max_output_tokens=1024, estimated_tokens=1200),
        dependencies=[],
        affected_components=["services/inventory.py"],
        allowed_tools=["read_file", "write_file", "edit_file"],
        allowed_files=["services/inventory.py", "tests/test_inventory.py"],
        expected_artifacts=[
            ArtifactRef(uri="artifact://inventory_model", kind="contract", description="Modelo de inventário", hash="abc123")
        ],
        inputs=[
            ArtifactRef(uri="artifact://repository_contract", kind="contract", description="Contrato do repositório")
        ],
        outputs=[
            ArtifactRef(uri="artifact://inventory_validation_impl", kind="implementation", description="Implementação da validação")
        ],
        status=TaskStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        depth=0,
        max_depth=16,
        trace_links=[
            RequirementLink(
                req_id="R1",
                task_ids=[],
                evidence_ids=[],
                test_ids=[],
                status="pending",
            )
        ],
    )


def test_ir_serialization() -> None:
    """O TaskIR deve serializar e desserializar corretamente via JSON."""
    ir = _make_ir()
    adapter = TypeAdapter(TaskIR)
    data = adapter.dump_python(ir)
    restored = adapter.validate_python(data)
    assert restored.task_id == ir.task_id
    assert restored.objective == ir.objective
    assert len(restored.requirements) == 1
    assert restored.requirements[0]["id"] == "R1"
    assert restored.context_budget is not None
    assert restored.context_budget.max_input_tokens == 6000
    assert restored.status == TaskStatus.PENDING.value


def test_ir_schema_version() -> None:
    """O esquema do IR deve ser versionado."""
    ir = _make_ir()
    assert ir.schema_version == IRSchema.V1


def test_ir_requirement_traceability() -> None:
    """As ligações de rastreabilidade devem conectar requisitos a tarefas, evidências e testes."""
    ir = _make_ir()
    assert len(ir.trace_links) == 1
    link = ir.trace_links[0]
    assert link.req_id == "R1"
    assert link.status == "pending"

    # Atualizar status de rastreamento
    link.status = "implemented"
    link.task_ids.append(ir.task_id)
    assert link.status == "implemented"
    assert ir.task_id in link.task_ids


def test_ir_context_budget() -> None:
    """O orçamento de contexto deve controlar tokens de entrada e saída."""
    ir = _make_ir()
    budget = ir.context_budget
    assert budget is not None
    assert budget.max_input_tokens == 6000
    assert budget.max_output_tokens == 1024
    assert budget.estimated_tokens == 1200
    assert budget.dropped == []


def test_ir_allowed_tools_and_files() -> None:
    """A tarefa deve declarar ferramentas e arquivos autorizados."""
    ir = _make_ir()
    assert "read_file" in ir.allowed_tools
    assert "write_file" in ir.allowed_tools
    assert "services/inventory.py" in ir.allowed_files


def test_ir_expected_artifacts() -> None:
    """Os artefatos esperados devem ser referências, não conteúdo embutido."""
    ir = _make_ir()
    assert len(ir.expected_artifacts) == 1
    artifact = ir.expected_artifacts[0]
    assert artifact.uri == "artifact://inventory_model"
    assert artifact.kind == "contract"
    assert artifact.hash == "abc123"


def test_ir_inputs_outputs() -> None:
    """Entradas e saídas devem ser referências a artefatos."""
    ir = _make_ir()
    assert len(ir.inputs) == 1
    assert ir.inputs[0].uri == "artifact://repository_contract"
    assert len(ir.outputs) == 1
    assert ir.outputs[0].uri == "artifact://inventory_validation_impl"


def test_ir_hierarchy_and_dependencies() -> None:
    """A tarefa deve suportar hierarquia e dependências."""
    ir = _make_ir()
    assert ir.parent_id is None
    assert ir.depth == 0

    # Criar uma subtarefa com dependência
    child_ir = TaskIR(
        task_id=uuid.uuid4(),
        parent_id=ir.task_id,
        objective="Implementar função de validação",
        dependencies=[ir.task_id],
        depth=1,
        max_depth=16,
        status=TaskStatus.PENDING.value,
    )
    assert child_ir.parent_id == ir.task_id
    assert ir.task_id in child_ir.dependencies
    assert child_ir.depth == 1


def test_ir_to_ir_roundtrip() -> None:
    """to_ir deve produzir um IR válido a partir de campos mínimos."""
    ir = _make_ir()
    # Recriar a partir dos dados serializados
    adapter = TypeAdapter(TaskIR)
    data = adapter.dump_python(ir)
    restored = adapter.validate_python(data)
    assert restored.schema_version == ir.schema_version
    assert restored.task_id == ir.task_id
    assert restored.objective == ir.objective
    assert restored.created_at.tzinfo is not None
    assert restored.updated_at.tzinfo is not None
