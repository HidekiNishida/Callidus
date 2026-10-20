"""
Arquivo: tests/test_executor_scope.py
Nome: test_executor_scope.py
Propósito: Verificar que a exclusividade da inferência vale para o processo, e não apenas para o laço de eventos.
Responsabilidade: camada de testes — limite de inferências simultâneas no mesmo laço, entre threads e na rota de streaming.
Componentes: limite no mesmo laço, threads com laços distintos, threads com laço único, paralelismo configurado, sessões compartilhando executor, devolução duplicada, cancelamento, falha do provedor e streaming.
Dependências: agent.services.executor e agent.providers.base.
Observações: o executor global é reiniciado entre os testes; contadores de concorrência são seguros entre threads.

A exclusividade vale para o processo, não apenas para o laço de eventos.

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
    """Reinicia o executor global antes e depois do teste."""
    reset_executor()
    yield
    reset_executor()


class _Contador:
    """Conta inferências simultâneas de forma segura entre threads."""

    def __init__(self) -> None:
        """Zera os contadores de inferência ativa, chamadas e pico."""
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        """Registra o início de uma inferência e atualiza o pico de simultaneidade."""
        with self._lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)

    def leave(self) -> None:
        """Registra o fim de uma inferência ativa."""
        with self._lock:
            self.active -= 1


async def _inferir(executor: InferenceExecutor, contador: _Contador, delay: float = 0.2) -> None:
    """Adquire um slot do executor, marca a inferência como ativa e devolve o slot ao final."""
    slot = await executor.acquire(purpose="teste")
    try:
        contador.enter()
        await asyncio.sleep(delay)
        contador.leave()
    finally:
        executor.release(slot=slot)


@pytest.mark.asyncio
async def test_o_limite_e_respeitado_no_mesmo_laco():
    """No mesmo laço, apenas uma inferência por vez, mesmo com quatro chamadas."""
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
        """Executa uma inferência em laço de eventos próprio, simulando uma thread separada."""
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
    """Com limite maior, as inferências correm em paralelo."""
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
    """Devolver o mesmo slot duas vezes não corrompe a contagem de slots ativos."""
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="teste")
    executor.release(slot=slot)
    executor.release(slot=slot)  # um `finally` que libera duas vezes
    assert executor.metrics().active == 0
    livre = await executor.acquire(purpose="teste")
    executor.release(slot=livre)


@pytest.mark.asyncio
async def test_cancelamento_durante_a_espera_nao_ocupa_slot():
    """Cancelar uma espera não ocupa slot e o slot segue utilizável."""
    executor = InferenceExecutor(limit=1)
    slot = await executor.acquire(purpose="primeiro")

    async def esperando() -> None:
        """Fica esperando um slot e é cancelada antes de obtê-lo."""
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
    """A falha do provedor libera o slot e fica contabilizada."""
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
        """Prepara o atraso de cada fragmento e zera os contadores."""
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def _chat(self, request):
        """Falha de propósito: o streaming não pode passar por aqui."""
        raise AssertionError("não deveria chamar chat")

    async def _chat_streaming(self, request, on_delta):
        """Emite três fragmentos com atraso e registra a simultaneidade."""
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
        """Provedor falso que encaminha o streaming para o provedor interno de streaming."""
        name = "fake-stream"

        def __init__(self) -> None:
            """Guarda o provedor interno que emite os fragmentos com atraso."""
            self.inner = _StreamingFake()

        async def list_models(self):
            """Provedor falso: não anuncia nenhum modelo."""
            return []

        async def _chat(self, request):
            """Encaminha a chamada de chat ao provedor interno de streaming."""
            return await self.inner._chat(request)

        async def _chat_streaming(self, request, on_delta):
            """Encaminha o streaming ao provedor interno, que emite fragmentos com atraso."""
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
        """Provedor falso cujo streaming falha depois do primeiro fragmento."""
        name = "fake-stream"

        async def list_models(self):
            """Provedor falso: não anuncia nenhum modelo."""
            return []

        async def _chat(self, request):
            """Falha de propósito: o chat não pode ser usado nesta rota."""
            raise AssertionError("não deveria chamar chat")

        async def _chat_streaming(self, request, on_delta):
            """Emite um fragmento e falha, simulando o consumidor do stream que cai."""
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
    """Cancelar o streaming no meio não deixa slot ocupado."""
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
        """Provedor falso cujo streaming nunca termina, para permitir o cancelamento."""
        name = "fake-stream"

        async def list_models(self):
            """Provedor falso: não anuncia nenhum modelo."""
            return []

        async def _chat(self, request):
            """Falha de propósito: o chat não pode ser usado nesta rota."""
            raise AssertionError("não deveria chamar chat")

        async def _chat_streaming(self, request, on_delta):
            """Dorme para sempre, para que o streaming possa ser cancelado no meio."""
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
        """Provedor falso que registra a simultaneidade das chamadas de chat."""
        name = "fake"

        def __init__(self) -> None:
            """Zera os contadores de chamada ativa e de máximo simultâneo."""
            self.active = 0
            self.max_active = 0

        async def list_models(self):
            """Provedor falso: não anuncia nenhum modelo."""
            return []

        async def _chat(self, request):
            """Conta a chamada ativa e devolve uma resposta após o atraso."""
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
