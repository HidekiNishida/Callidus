# tests/test_executor_scope.py — escopo real da exclusividade de inferência
"""A exclusividade vale para o processo, não apenas para o laço de eventos.

Este arquivo existe porque a primeira implementação usava um semáforo do `asyncio`,
que pertence ao laço de eventos que o criou: dois threads com laços diferentes
inferiam ao mesmo tempo. O teste `test_o_limite_e_respeitado_entre_threads_com_lacos_distintos`
é a trava contra essa regressão.

O que **não** é coberto (e está documentado como limitação): dois processos
independentes. O controle vive na memória do processo; serializar entre processos
exigiria uma trava externa, que não se justifica para a instalação local.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from agent.services.executor import InferenceExecutor, get_executor, reset_executor


@pytest.fixture(autouse=True)
def _isolated_executor():
    reset_executor()
    yield
    reset_executor()


class _Contador:
    """Conta inferências simultâneas de forma segura entre threads."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)

    def leave(self) -> None:
        with self._lock:
            self.active -= 1


async def _inferir(executor: InferenceExecutor, contador: _Contador, delay: float = 0.2) -> None:
    slot = await executor.acquire(purpose="teste")
    try:
        contador.enter()
        await asyncio.sleep(delay)
        contador.leave()
    finally:
        executor.release(slot=slot)


@pytest.mark.asyncio
async def test_o_limite_e_respeitado_no_mesmo_laco():
    executor = InferenceExecutor(limit=1)
    contador = _Contador()
    await asyncio.gather(*[_inferir(executor, contador, 0.05) for _ in range(4)])
    assert contador.max_active == 1
    assert contador.calls == 4


@pytest.mark.asyncio
async def test_o_limite_e_respeitado_entre_threads_com_lacos_distintos():
    """Regressão do semáforo por laço: threads separadas, laços separados, uma só inferência."""
    executor = InferenceExecutor(limit=1)
    contador = _Contador()

    def worker() -> None:
        asyncio.run(_inferir(executor, contador, 0.15))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert contador.calls == 3
    assert contador.max_active == 1
    assert executor.metrics().max_active == 1
    # As demais inferências esperaram o slot.
    assert executor.metrics().waits >= 1


@pytest.mark.asyncio
async def test_o_limite_e_respeitado_entre_threads_e_laco_unico():
    """Threads que entregam trabalho ao mesmo laço: o laço continua responsivo."""
    executor = InferenceExecutor(limit=1)
    contador = _Contador()
    loop = asyncio.get_running_loop()

    futures = [
        asyncio.run_coroutine_threadsafe(_inferir(executor, contador, 0.1), loop)
        for _ in range(3)
    ]
    threads = [threading.Thread(target=future.result) for future in futures]
    for thread in threads:
        thread.start()
    # A thread principal não pode bloquear o laço: ele é quem executa as corrotinas.
    await asyncio.gather(*[asyncio.wrap_future(future) for future in futures])
    for thread in threads:
        thread.join()

    assert contador.calls == 3
    assert contador.max_active == 1


@pytest.mark.asyncio
async def test_o_limite_permite_paralelismo_quando_configurado():
    executor = InferenceExecutor(limit=2)
    contador = _Contador()
    await asyncio.gather(*[_inferir(executor, contador, 0.1) for _ in range(4)])
    assert contador.max_active == 2


@pytest.mark.asyncio
async def test_sessoes_distintas_do_banco_compartilham_o_executor():
    """Várias sessões do SQLite, no mesmo processo, disputam o mesmo slot."""
    executor = get_executor()
    contador = _Contador()
    await asyncio.gather(*[_inferir(executor, contador, 0.05) for _ in range(3)])
    assert contador.max_active == 1


@pytest.mark.asyncio
async def test_a_devolucao_duplicada_do_slot_nao_corrompe_a_contagem():
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="teste")
    executor.release(slot=slot)
    executor.release(slot=slot)  # um `finally` que libera duas vezes
    assert executor.metrics().active == 0
    livre = await executor.acquire(purpose="teste")
    executor.release(slot=livre)


@pytest.mark.asyncio
async def test_cancelamento_durante_a_espera_nao_ocupa_slot():
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="primeiro")

    async def esperando() -> None:
        await executor.acquire(purpose="segundo")

    task = asyncio.create_task(esperando())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    executor.release(slot=slot)

    assert executor.metrics().active == 0
    livre = await executor.acquire(purpose="terceiro")
    executor.release(slot=livre)
    assert executor.metrics().active == 0


@pytest.mark.asyncio
async def test_falha_do_provedor_nao_prende_o_slot():
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="teste")
    executor.release(error=RuntimeError("caiu"), slot=slot)
    assert executor.metrics().inferences_failed == 1
    livre = await executor.acquire(purpose="teste")
    executor.release(slot=livre)


# ------------------------------------------------------- rotas de chamada


class _StreamingFake:
    """Provedor com streaming real, para verificar a rota de streaming."""

    def __init__(self, delay: float = 0.1) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def _chat(self, request):
        raise AssertionError("não deveria chamar chat")

    async def _chat_streaming(self, request, on_delta):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            for parte in ("a", "b", "c"):
                on_delta(parte)
                await asyncio.sleep(self.delay)
            return "conteúdo"
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_o_streaming_tambem_passa_pelo_executor():
    """A rota de streaming é uma rota de inferência: precisa do mesmo slot."""
    from agent.providers.base import (
        ChatCompletionRequest,
        ChatMessage,
        ChatCompletionResponse,
        LLMProvider,
        ModelProfile,
    )

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m")
    )

    class _P(LLMProvider):
        name = "fake-stream"

        def __init__(self) -> None:
            self.inner = _StreamingFake()

        async def list_models(self):
            return []

        async def _chat(self, request):
            return await self.inner._chat(request)

        async def _chat_streaming(self, request, on_delta):
            return await self.inner._chat_streaming(request, on_delta)

    provider = _P()
    executor = get_executor()
    inicio = executor.metrics().inferences_started
    respostas = await asyncio.gather(
        *[
            provider.chat_streaming(request, lambda parte: None)
            for _ in range(3)
        ]
    )
    assert len(respostas) == 3
    assert provider.inner.max_active == 1
    assert executor.metrics().inferences_started - inicio == 3
    assert executor.metrics().max_active == 1


@pytest.mark.asyncio
async def test_excecao_no_consumidor_do_streaming_libera_o_slot():
    """Se o consumidor do stream falha (SSE desconectado), o slot não fica preso."""
    from agent.providers.base import (
        ChatCompletionRequest,
        ChatMessage,
        LLMProvider,
        ModelProfile,
    )

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m")
    )

    class _P(LLMProvider):
        name = "fake-stream"

        async def list_models(self):
            return []

        async def _chat(self, request):
            raise AssertionError("não deveria chamar chat")

        async def _chat_streaming(self, request, on_delta):
            on_delta("primeiro")
            raise ConnectionResetError("consumidor caiu")

    executor = get_executor()
    with pytest.raises(ConnectionResetError):
        await _P().chat_streaming(request, lambda parte: None)
    assert executor.metrics().active == 0
    livre = await executor.acquire(purpose="depois")
    executor.release(slot=livre)


@pytest.mark.asyncio
async def test_cancelamento_no_streaming_libera_o_slot():
    from agent.providers.base import (
        ChatCompletionRequest,
        ChatMessage,
        LLMProvider,
        ModelProfile,
    )

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m")
    )

    class _P(LLMProvider):
        name = "fake-stream"

        async def list_models(self):
            return []

        async def _chat(self, request):
            raise AssertionError("não deveria chamar chat")

        async def _chat_streaming(self, request, on_delta):
            await asyncio.sleep(10)
            return "nunca"

    executor = get_executor()
    task = asyncio.create_task(_P().chat_streaming(request, lambda parte: None))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert executor.metrics().active == 0
    assert executor.metrics().inferences_cancelled == 1


@pytest.mark.asyncio
async def test_a_rota_indireta_observada_tambem_e_limitada(tmp_path):
    """`observed_chat` é a rota usada pelo runner: ela também tem de passar pelo slot."""
    from agent.persistence.database import build_session_factory, init_db
    from agent.providers.base import (
        ChatCompletionRequest,
        ChatMessage,
        ChatCompletionResponse,
        LLMProvider,
        ModelProfile,
    )
    from agent.providers.observed import observed_chat
    from agent.config import Settings

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m")
    )

    class _P(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def list_models(self):
            return []

        async def _chat(self, request):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.05)
                return ChatCompletionResponse(content="ok")
            finally:
                self.active -= 1

    settings = Settings(data_dir=tmp_path)
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    try:
        provider = _P()
        executor = get_executor()
        # Fora de um run: `observed_chat` chama `provider.chat` direto.
        await asyncio.gather(
            *[observed_chat(provider, request, purpose="operação") for _ in range(3)]
        )
        assert provider.max_active == 1
        assert executor.metrics().max_active == 1
    finally:
        session.close()
