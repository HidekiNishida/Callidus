# tests/test_agent_scheduler.py — escalonador por eventos
"""O escalonador escolhe a próxima operação e a executa uma por vez.

O que importa aqui: nada trava, nada duplica, nada espera gastando token.
"""
from __future__ import annotations

import asyncio

import pytest

from agent.config import Settings
from agent.services.agent_scheduler import AgentScheduler, SchedulerOperation


@pytest.fixture
def scheduler() -> AgentScheduler:
    return AgentScheduler(Settings(data_dir="/tmp/agent-scheduler-tests"))


@pytest.mark.asyncio
async def test_a_fila_esvazia_nao_faz_nada(scheduler: AgentScheduler):
    assert await scheduler.run_once() is None
    assert scheduler.stats()["executed"] == 0


@pytest.mark.asyncio
async def test_a_mesma_chave_nao_entra_duas_vezes(scheduler: AgentScheduler):
    assert scheduler.submit("run_step", "run:1") is True
    assert scheduler.submit("run_step", "run:1") is False
    assert scheduler.stats()["duplicates"] == 1
    assert scheduler.stats()["pending"] == 1


@pytest.mark.asyncio
async def test_a_operacao_e_executada_e_registrada(scheduler: AgentScheduler):
    seen: list[str] = []

    async def handler(operation: SchedulerOperation):
        seen.append(operation.key)
        return {"action": "done"}

    scheduler.register("run_step", handler)
    scheduler.submit("run_step", "run:1")
    result = await scheduler.run_once()
    assert result is not None and result.ok and result.action == "done"
    assert seen == ["run:1"]
    assert scheduler.stats()["executed"] == 1
    assert scheduler.history()[0]["key"] == "run:1"


@pytest.mark.asyncio
async def test_uma_operacao_que_falha_nao_derruba_a_fila(scheduler: AgentScheduler):
    async def handler(operation: SchedulerOperation):
        if operation.key == "ruim":
            raise RuntimeError("falhou")
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    scheduler.submit("run_step", "ruim")
    scheduler.submit("run_step", "bom")
    first = await scheduler.run_once()
    assert first is not None and not first.ok and "falhou" in (first.error or "")
    second = await scheduler.run_once()
    assert second is not None and second.ok


@pytest.mark.asyncio
async def test_uma_operacao_bloqueada_nao_impede_as_outras(scheduler: AgentScheduler):
    async def handler(operation: SchedulerOperation):
        if operation.key == "bloqueada":
            return {"action": "blocked", "error": "aguardando dependência"}
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    scheduler.submit("run_step", "bloqueada")
    scheduler.submit("run_step", "independente")
    first = await scheduler.run_once()
    assert first is not None and not first.ok
    second = await scheduler.run_once()
    assert second is not None and second.ok


@pytest.mark.asyncio
async def test_o_tempo_limite_da_operacao_e_respeitado():
    scheduler = AgentScheduler(Settings(data_dir="/tmp/x"), operation_timeout_sec=0.05)

    async def handler(operation: SchedulerOperation):
        await asyncio.sleep(5)
        return {"action": "nunca"}

    scheduler.register("run_step", handler)
    scheduler.submit("run_step", "lenta")
    result = await scheduler.run_once()
    assert result is not None and not result.ok
    assert "tempo limite" in (result.error or "")
    assert scheduler.stats()["timeouts"] == 1


@pytest.mark.asyncio
async def test_a_prioridade_organiza_a_fila_sem_fome(scheduler: AgentScheduler):
    order: list[str] = []

    async def handler(operation: SchedulerOperation):
        order.append(operation.key)
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    scheduler.submit("run_step", "comum-1", priority=0)
    scheduler.submit("run_step", "urgente", priority=10)
    scheduler.submit("run_step", "comum-2", priority=0)
    await scheduler.run_once()
    await scheduler.run_once()
    await scheduler.run_once()
    assert order[0] == "urgente"
    # Entre operações de mesma prioridade, a mais antiga vai primeiro (não há fome).
    assert order[1] == "comum-1"


@pytest.mark.asyncio
async def test_esperar_ocioso_nao_consome_inferencia(scheduler: AgentScheduler):
    """Sem trabalho pendente, esperar não chama o modelo — só dorme."""
    calls = 0

    async def handler(operation: SchedulerOperation):
        nonlocal calls
        calls += 1
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    assert await scheduler.wait_idle(timeout=0.2) is True
    assert calls == 0


@pytest.mark.asyncio
async def test_o_laco_principal_dorme_e_acorda_com_notificacao(scheduler: AgentScheduler):
    done: list[str] = []

    async def handler(operation: SchedulerOperation):
        done.append(operation.key)
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    task = asyncio.create_task(scheduler.run_forever())
    await asyncio.sleep(0.05)
    assert done == []
    scheduler.submit("run_step", "run:1")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if done:
            break
    assert done == ["run:1"]
    scheduler.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_o_tratador_auscente_e_um_erro_controlado(scheduler: AgentScheduler):
    scheduler.submit("desconhecido", "x")
    result = await scheduler.run_once()
    assert result is not None and not result.ok
    assert "tratador" in (result.error or "")
