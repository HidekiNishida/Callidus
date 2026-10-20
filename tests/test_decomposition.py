"""
Arquivo: tests/test_decomposition.py
Nome: test_decomposition.py
Propósito: Verificar a resolução do plano de decomposição embutido para o cenário de ponta a ponta.
Responsabilidade: camada de testes — origem e conteúdo do plano embutido de e2e.
Componentes: resolução do plano embutido de e2e.
Dependências: agent.orchestrator.decomposition e agent.config.Settings.
Observações: nenhum banco é usado: a resolução acontece com a raiz em memória.
"""

import pytest

from agent.config import Settings
from agent.orchestrator.decomposition import resolve_decomposition_plan


@pytest.mark.asyncio
async def test_resolve_builtin_e2e():
    """O objetivo de e2e resolve para o plano embutido com três subtarefas."""
    settings = Settings(allow_mock_fallback=True)
    plan, source = await resolve_decomposition_plan(
        settings=settings,
        run_config={"provider": "mock"},
        objective="rodar e2e no calc",
        project_root="/tmp/x",
    )
    assert plan is not None
    assert source == "builtin-e2e"
    assert len(plan.subtasks) == 3
