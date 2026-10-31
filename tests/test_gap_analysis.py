"""
Arquivo: tests/test_gap_analysis.py
Nome: test_gap_analysis.py
Propósito: verificar a análise de lacunas — pedido vago de conclusão ("termine a calculadora") vira requisitos concretos antes do plano.
Responsabilidade: camada de testes — detecção da intenção, lacunas do modelo nos requisitos do plano e no contrato da raiz, falha do modelo sem efeito.
Componentes: wants_completion, analyze_gaps, gap_requirements, resolve_decomposition_plan, apply_decomposition.
Dependências: agent.orchestrator (gap_analysis, decomposition, requirements), agent.services, agent.persistence, pytest.
Observações: provedor falso com roteiro; projeto e banco temporários.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.decomposition import (
    apply_decomposition,
    resolve_decomposition_plan,
)
from agent.orchestrator.gap_analysis import (
    analyze_gaps,
    gap_requirements,
    wants_completion,
)
from agent.orchestrator.requirements import ensure_requirements, load_requirements
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import (
    ChatCompletionRequest,
    ModelProfile,
    ProviderCapabilities,
)
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService

PEDIDO = "sua missão é terminar essa calculadora e abrir ela para mim ver"
LACUNAS = json.dumps(
    {
        "lacunas": [
            "em main.py, troque os dois campos por um visor e um teclado numérico",
            "em main.py, trate divisão por zero no visor",
            "ok",
            "em tests/test_calculator.py, adicione testes de divisão por zero",
        ]
    }
)
PLANO = json.dumps(
    {"subtasks": [{"title": "Teclado", "objective": "Fazer o teclado", "metadata": {"model_operation": True, "covers": ["R2", "R3"]}}]}
)


class _Modelo:
    """Modelo falso: devolve o roteiro, uma resposta por chamada."""

    name = "fake"
    supports_streaming = False

    def __init__(self, replies: list[str]) -> None:
        """Guarda o roteiro."""
        self.replies = list(replies)
        self.requests: list[ChatCompletionRequest] = []

    def capabilities(self) -> ProviderCapabilities:
        """Sem laço de ferramentas."""
        return ProviderCapabilities()

    async def chat(self, request: ChatCompletionRequest):
        """Próxima resposta do roteiro."""
        self.requests.append(request)
        content = self.replies.pop(0) if self.replies else ""
        return type("R", (), {"content": content, "tool_calls": None, "reasoning": None})()


def _projeto(tmp_path: Path) -> Path:
    """Calculadora mínima com interface de dois campos."""
    ws = tmp_path / "calc"
    ws.mkdir()
    (ws / "main.py").write_text("import tkinter as tk\nfrom calculator import add\n", encoding="utf-8")
    (ws / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return ws


def test_completion_intent():
    """Terminar, finalizar e melhorar sem itens enumerados contam; pedido enumerado ou de criação, não."""
    assert wants_completion(PEDIDO)
    assert wants_completion("Melhore a UI da calculadora")
    assert not wants_completion("Crie uma calculadora em Python")
    assert not wants_completion("Termine:\n- a soma\n- a subtração")


@pytest.mark.asyncio
async def test_analyze_gaps_reads_the_project_and_keeps_useful_items(tmp_path):
    """O modelo vê o código; itens curtos demais ficam de fora."""
    modelo = _Modelo([LACUNAS])
    gaps = await analyze_gaps(modelo, ModelProfile(model_id="qwen3-vl:8b"), PEDIDO, str(_projeto(tmp_path)))
    assert len(gaps) == 2 and gaps[0].startswith("em main.py")
    assert "main.py" in modelo.requests[0].messages[0].content
    reqs = gap_requirements(gaps, start=2)
    assert [r["id"] for r in reqs] == ["R2", "R3"] and all(r["evidence"] == "change" for r in reqs)
    assert await analyze_gaps(_Modelo(["não sei"]), ModelProfile(model_id="x"), PEDIDO, str(tmp_path / "calc")) == []


@pytest.mark.asyncio
async def test_root_plan_gets_the_gaps_as_requirements_and_the_contract_keeps_them(tmp_path, monkeypatch):
    """Regressão (qwen3-vl:8b): "terminar" era um requisito só; o plano conferia arquivos e concluía sem melhorar nada."""
    import agent.orchestrator.gap_analysis as gap_module

    monkeypatch.setattr(gap_module, "environment_note", lambda root: "")
    ws = _projeto(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="Calculadora", root_path=str(ws)))
    root = TaskService(session).create_task(project.id, TaskCreate(title=PEDIDO, objective=PEDIDO))
    reqs = ensure_requirements(session, root)
    modelo = _Modelo([LACUNAS, PLANO])

    plan, source = await resolve_decomposition_plan(
        settings=settings,
        run_config={"provider": "meu_ollama", "model_id": "qwen3-vl:8b"},
        objective=PEDIDO,
        project_root=str(ws),
        provider=modelo,
        requirements=reqs,
    )

    assert source == "meu_ollama"
    assert "R2: em main.py" in "\n".join(m.content for m in modelo.requests[1].messages)
    assert [r["id"] for r in plan.added_requirements] == ["R2", "R3"]
    # Regressão: o saneamento do plano (feito pelo orquestrador antes de aplicar) recriava o
    # objeto sem as lacunas, e elas nunca chegavam ao contrato.
    from agent.orchestrator.plan_validation import sanitize_spec

    plan, _issues = sanitize_spec(plan)
    apply_decomposition(session, project.id, root.id, plan)
    stored = load_requirements(session, root)
    assert [r["id"] for r in stored] == ["R1", "R2", "R3"]
    assert stored[1]["origin"] == "lacuna do pedido"
    session.close()


def test_operations_on_the_same_file_are_merged_into_one_step():
    """Regressão (qwen3-vl:8b): seis lacunas de main.py viravam seis etapas que se desfaziam."""
    from agent.orchestrator.decomposition import (
        DecompositionResult,
        SubTaskSpec,
        merge_same_file_operations,
    )

    op = {"model_operation": True}
    plan = DecompositionResult(
        subtasks=[
            SubTaskSpec(title="Ler main.py", objective="ler", metadata={"tool": "read_file", "tool_args": {"path": "main.py"}}),
            SubTaskSpec(title="Cores em main.py", objective="cores no visor", metadata={**op, "covers": ["R2"]}, depends_on_indices=[0]),
            SubTaskSpec(title="Limpar em main.py", objective="botão C", metadata={**op, "covers": ["R3"]}, depends_on_indices=[1]),
            SubTaskSpec(title="Soma em calculator.py", objective="soma", metadata={**op, "covers": ["R4"]}),
            SubTaskSpec(title="Erro em main.py", objective="entrada inválida", metadata={**op, "covers": ["R5"]}, depends_on_indices=[3]),
            SubTaskSpec(title="Abrir", objective="abrir", metadata={"tool": "run_app", "tool_args": {"path": "main.py"}}, depends_on_indices=[2, 4]),
        ]
    )
    merged = merge_same_file_operations(plan)
    titles = [s.title for s in merged.subtasks]
    assert titles == ["Ler main.py", "Alterar main.py", "Soma em calculator.py", "Abrir"]
    main_step = merged.subtasks[1]
    assert main_step.metadata["covers"] == ["R2", "R3", "R5"]
    assert "botão C" in main_step.objective and "entrada inválida" in main_step.objective
    assert main_step.depends_on_indices == [0, 2]
    assert merged.subtasks[3].depends_on_indices == [1]
    assert merge_same_file_operations(DecompositionResult(subtasks=plan.subtasks[:2])).subtasks == plan.subtasks[:2]
