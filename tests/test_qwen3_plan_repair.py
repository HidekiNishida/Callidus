"""
Arquivo: tests/test_qwen3_plan_repair.py
Nome: test_qwen3_plan_repair.py
Propósito: verificar a recuperação limitada do plano quando o modelo pequeno devolve um JSON inválido.
Responsabilidade: camada de testes — uma única nova tentativa com formato imposto pelo servidor, sem recomeçar a inspeção e sem repetir indefinidamente.
Componentes: plan_with_model, PLAN_SCHEMA.
Dependências: agent.orchestrator.decomposition, agent.providers.base, pytest.
Observações: provedor falso com roteiro de respostas; nenhum modelo real.
"""
from __future__ import annotations

import json

import pytest

from agent.orchestrator.decomposition import PLAN_SCHEMA, plan_with_model
from agent.providers.base import ChatCompletionRequest, ModelProfile, ProviderCapabilities

GOOD_PLAN = json.dumps(
    {
        "subtasks": [
            {"title": "Ler calc.py", "objective": "Ler o arquivo", "metadata": {"tool": "read_file", "tool_args": {"path": "calc.py"}}},
            {"title": "Corrigir", "objective": "Corrigir a soma", "metadata": {"model_operation": True}, "depends_on_indices": [0]},
        ]
    }
)


class _Planner:
    """Modelo falso de plano: responde o roteiro, uma resposta por chamada."""

    name = "fake"
    supports_streaming = False

    def __init__(self, replies: list[str], *, structured: bool = True) -> None:
        """Guarda o roteiro e se o provedor impõe esquema JSON."""
        self.replies = list(replies)
        self.structured = structured
        self.requests: list[ChatCompletionRequest] = []

    def capabilities(self) -> ProviderCapabilities:
        """Sem laço de ferramentas (plano direto); saída estruturada conforme o caso."""
        return ProviderCapabilities(structured_output=self.structured)

    async def chat(self, request: ChatCompletionRequest):
        """Devolve a próxima resposta do roteiro."""
        self.requests.append(request)
        content = self.replies.pop(0) if self.replies else ""
        return type("R", (), {"content": content, "tool_calls": None, "reasoning": None})()


def _profile() -> ModelProfile:
    """Perfil do qwen3:8b."""
    return ModelProfile(model_id="qwen3:8b", context_limit=8192, input_budget=6000, output_reserve=1024)


@pytest.mark.asyncio
async def test_invalid_plan_gets_one_constrained_repair():
    """Prosa no lugar do JSON: uma segunda chamada com o esquema do plano devolve o plano válido."""
    provider = _Planner(["Claro! Primeiro vou ler o arquivo, depois corrigir.", GOOD_PLAN])
    plan = await plan_with_model(provider, _profile(), "corrigir calc.py", "")
    assert plan is not None
    assert [s.title for s in plan.subtasks] == ["Ler calc.py", "Corrigir"]
    assert len(provider.requests) == 2
    repair = provider.requests[1]
    assert repair.response_format == {"schema": PLAN_SCHEMA}
    assert repair.messages[-2].role == "assistant"
    assert repair.messages[-2].content.startswith("Claro!")
    # O pedido original continua no começo: a recuperação não perde o contexto.
    assert repair.messages[0].content == provider.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_truncated_plan_is_repaired_too():
    """JSON cortado no meio (resposta truncada) também recebe a recuperação única."""
    provider = _Planner([GOOD_PLAN[:60], GOOD_PLAN])
    plan = await plan_with_model(provider, _profile(), "corrigir calc.py", "")
    assert plan is not None and len(provider.requests) == 2


@pytest.mark.asyncio
async def test_repair_is_attempted_once_only():
    """Se a recuperação também falhar, não há terceira chamada: o caminho de sempre (template) assume."""
    provider = _Planner(["nada", "ainda nada", GOOD_PLAN])
    assert await plan_with_model(provider, _profile(), "corrigir calc.py", "") is None
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_valid_plan_costs_a_single_call():
    """Plano válido de primeira: nenhuma chamada extra."""
    provider = _Planner([GOOD_PLAN])
    assert await plan_with_model(provider, _profile(), "corrigir calc.py", "") is not None
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_provider_without_structured_output_is_not_retried():
    """Sem decodificação restrita, repetir o mesmo pedido não traz informação nova: não há reparo."""
    provider = _Planner(["prosa", GOOD_PLAN], structured=False)
    assert await plan_with_model(provider, _profile(), "corrigir calc.py", "") is None
    assert len(provider.requests) == 1
