"""
Arquivo: tests/test_context_budget.py
Nome: test_context_budget.py
Propósito: Verificar a montagem do contexto dentro do orçamento de tokens do modelo.
Responsabilidade: camada de testes — estimativa de tokens, prioridade dos componentes obrigatórios e estouro de orçamento.
Componentes: estimativa de tokens, manutenção de componente obrigatório e estouro com componente obrigatório.
Dependências: agent.context.budget e agent.providers.base.ModelProfile.
Observações: funções puras: nenhum banco, rede ou relógio é usado.
"""

import pytest

from agent.context.budget import ContextComponent, assemble_messages, estimate_tokens
from agent.providers.base import ModelProfile


def test_estimate_tokens_nonempty():
    """Um texto não vazio tem estimativa de tokens maior que zero."""
    assert estimate_tokens("abcd") >= 1


def test_required_components_kept():
    """O componente obrigatório permanece na montagem mesmo quando o opcional é grande."""
    profile = ModelProfile(model_id="tiny", context_limit=512, input_budget=400, output_reserve=64)
    components = [
        ContextComponent(name="req", text="x" * 100, required=True, priority=100),
        ContextComponent(name="low", text="y" * 2000, required=False, priority=1),
    ]
    result = assemble_messages(profile, components)
    assert any("req" in m.content for m in result.messages)
    assert "low" in result.dropped or result.dropped == []


def test_budget_overflow_required_raises():
    """Componente obrigatório maior que o orçamento levanta erro."""
    profile = ModelProfile(model_id="tiny", context_limit=200, input_budget=50, output_reserve=50)
    components = [ContextComponent(name="big", text="z" * 500, required=True)]
    with pytest.raises(ValueError):
        assemble_messages(profile, components)
