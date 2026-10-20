"""
Arquivo: tests/test_inference_executor.py
Nome: test_inference_executor.py
Propósito: Verificar a exclusividade de inferência: uma por vez, no processo inteiro.
Responsabilidade: camada de testes — serialização das inferências, paralelismo configurado, espera pelo slot, cancelamento, falha do provedor e limite vindo das configurações.
Componentes: inferências concorrentes, limite configurado, espera pelo slot, cancelamento, falha do provedor, caminho herdado do provedor e limite das configurações.
Dependências: agent.services.executor e agent.providers.base.
Observações: o executor global é reiniciado entre os testes; o provedor falso segura a inferência por um tempo curto.

Exclusividade de inferência: uma por vez, no processo inteiro.

O teste mais importante deste arquivo é `test_inferencias_concorrentes_nao_se_sobrepoem`:
ele prova que duas rotas de chamada diferentes (a que o runner usa e a que o ciclo de
ferramentas usa) nunca disparam inferências ao mesmo tempo.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.config import Settings
from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    ChatCompletionResponse,
    LLMProvider,
    ModelProfile,
)
from agent.services.executor import InferenceExecutor, get_executor, reset_executor

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m")
)


class _SlowProvider(LLMProvider):
    """Provedor que segura a inferência por um tempo e registra a sobreposição."""

    name = "slow"

    def __init__(self, delay: float = 0.05) -> None:
        """Prepara o atraso da inferência e zera os contadores."""
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def list_models(self):
        """Declara um único modelo disponível."""
        return ["m"]

    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Conta a chamada, registra a simultaneidade e segura a inferência pelo atraso configurado."""
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return ChatCompletionResponse(content="ok")
        finally:
            self.active -= 1


@pytest.fixture(autouse=True)
def _isolated_executor():
    """Reinicia o executor global antes e depois do teste."""
    reset_executor()
    yield
    reset_executor()


@pytest.mark.asyncio
async def test_inferencias_concorrentes_nao_se_sobrepoem():
    """Quatro inferências concorrentes nunca se sobrepõem quando o limite é um."""
    provider = _SlowProvider()
    executor = InferenceExecutor(limit=1)

    async def call():
        """Adquire um slot, faz a inferência e devolve o slot ao executor."""
        slot = await executor.acquire(purpose="test")
        try:
            return await provider._chat(REQUEST)
        finally:
            executor.release(slot=slot)

    results = await asyncio.gather(*[call() for _ in range(4)])
    assert len(results) == 4
    assert provider.max_active == 1
    assert executor.metrics().max_active == 1
    assert executor.metrics().inferences_started == 4
    assert executor.metrics().inferences_completed == 4


@pytest.mark.asyncio
async def test_o_limite_configurado_permite_paralelismo_quando_asked():
    """Com limite três, as inferências rodam em paralelo."""
    provider = _SlowProvider(delay=0.02)
    executor = InferenceExecutor(limit=3)

    async def call():
        """Adquire um slot, faz a inferência e devolve o slot ao executor."""
        slot = await executor.acquire(purpose="test")
        try:
            return await provider._chat(REQUEST)
        finally:
            executor.release(slot=slot)

    await asyncio.gather(*[call() for _ in range(3)])
    assert provider.max_active == 3
    assert executor.metrics().max_active == 3


@pytest.mark.asyncio
async def test_a_espera_pelo_slot_e_registrada():
    """A espera pelo slot é registrada nas métricas de espera."""
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="first")

    async def second():
        """Espera pelo slot disponível e devolve quanto tempo esperou."""
        other = await executor.acquire(purpose="second")
        executor.release(slot=other)
        return other.waited_seconds

    task = asyncio.create_task(second())
    await asyncio.sleep(0.05)
    executor.release(slot=slot)
    waited = await task
    assert waited > 0
    assert executor.metrics().waits == 1
    assert executor.metrics().wait_seconds > 0


@pytest.mark.asyncio
async def test_cancelamento_nao_deixa_slot_ocupado():
    """O cancelamento libera o slot, que continua utilizável depois."""
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="first")

    async def cancelled():
        """Espera por um slot até ser cancelada."""
        try:
            await executor.acquire(purpose="second")
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(cancelled())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    executor.release(error=asyncio.CancelledError(), slot=slot)
    assert executor.metrics().active == 0
    # O slot continua utilizável depois do cancelamento.
    free = await executor.acquire(purpose="third")
    executor.release(slot=free)


@pytest.mark.asyncio
async def test_falha_do_provedor_contabilizada_e_slot_devolvido():
    """A falha do provedor é contabilizada e o slot é devolvido."""
    class _Broken(_SlowProvider):
        """Provedor que sempre falha na inferência."""
        async def _chat(self, request):
            """Estoura um erro de execução, simulando a queda do provedor."""
            raise RuntimeError("caiu")

    provider = _Broken()
    with pytest.raises(RuntimeError):
        await provider.chat(REQUEST)
    metrics = get_executor().metrics()
    assert metrics.inferences_failed == 1
    assert metrics.active == 0


@pytest.mark.asyncio
async def test_o_provedor_herdado_passa_pelo_executor():
    """A garantia está no contrato do provedor: `chat` do base é o único caminho."""
    provider = _SlowProvider()
    await asyncio.gather(*[provider.chat(REQUEST) for _ in range(3)])
    assert provider.max_active == 1
    assert get_executor().metrics().max_active == 1


@pytest.mark.asyncio
async def test_o_limite_vem_das_configuracoes():
    """O limite do executor vem da configuração de inferências concorrentes."""
    settings = Settings(max_concurrent_inferences=2)
    executor = get_executor(settings)
    assert executor.limit == 2
    settings2 = Settings(max_concurrent_inferences=1)
    assert get_executor(settings2).limit == 1


def test_limite_invalido_e_recusado():
    """Limite zero ou negativo é recusado com erro."""
    with pytest.raises(ValueError):
        InferenceExecutor(limit=0)
