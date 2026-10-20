"""
Arquivo: tests/test_agent_scheduler.py
Nome: test_agent_scheduler.py
Propósito: Verificar o escalonador que escolhe a próxima operação e a executa uma por vez.
Responsabilidade: camada de testes — fila, deduplicação, prioridade, tempo limite, espera ociosa e laço principal do escalonador.
Componentes: fila vazia, chave repetida, operação registrada, falha e bloqueio de operação, tempo limite, prioridade sem fome, espera ociosa, laço principal e tratador ausente.
Dependências: agent.services.agent_scheduler e agent.config.Settings.
Observações: nenhum banco é usado: o escalonador é criado com um data_dir temporário e handlers em memória.

O escalonador escolhe a próxima operação e a executa uma por vez.

O que importa aqui: nada trava, nada duplica, nada espera gastando token.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.config import Settings
from agent.services.agent_scheduler import AgentScheduler, SchedulerOperation


@pytest.fixture
def scheduler() -> AgentScheduler:
    """Escalonador novo, com fila vazia, apontando para um diretório de dados temporário."""
    return AgentScheduler(Settings(data_dir="/tmp/agent-scheduler-tests"))


@pytest.mark.asyncio
async def test_a_fila_esvazia_nao_faz_nada(scheduler: AgentScheduler):
    """Com a fila vazia, nada é executado e nenhuma execução é registrada."""
    assert await scheduler.run_once() is None
    assert scheduler.stats()["executed"] == 0


@pytest.mark.asyncio
async def test_a_mesma_chave_nao_entra_duas_vezes(scheduler: AgentScheduler):
    """A mesma chave é recusada na segunda submissão e contada como duplicata."""
    assert scheduler.submit("run_step", "run:1") is True
    assert scheduler.submit("run_step", "run:1") is False
    assert scheduler.stats()["duplicates"] == 1
    assert scheduler.stats()["pending"] == 1


@pytest.mark.asyncio
async def test_a_operacao_e_executada_e_registrada(scheduler: AgentScheduler):
    """A operação submetida é executada pelo handler e registrada no histórico."""
    seen: list[str] = []

    async def handler(operation: SchedulerOperation):
        """Handler que registra a chave recebida e devolve a ação concluída."""
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
    """A operação que falha é reportada como erro e a seguinte ainda é executada."""
    async def handler(operation: SchedulerOperation):
        """Handler que falha somente na operação de chave ruim."""
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
    """A operação bloqueada é reportada e não impede a execução das demais."""
    async def handler(operation: SchedulerOperation):
        """Handler que devolve operação bloqueada para a chave bloqueada."""
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
    """A operação que excede o tempo limite é interrompida e contada como timeout."""
    scheduler = AgentScheduler(Settings(data_dir="/tmp/x"), operation_timeout_sec=0.05)

    async def handler(operation: SchedulerOperation):
        """Handler que dorme além do tempo limite, para forçar o timeout."""
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
    """A prioridade mais alta vai primeiro e, dentro da mesma prioridade, a mais antiga não passa fome."""
    order: list[str] = []

    async def handler(operation: SchedulerOperation):
        """Handler que registra a ordem de execução das operações."""
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
        """Handler que conta as chamadas, para provar que a espera ociosa não as gera."""
        nonlocal calls
        calls += 1
        return {"action": "ok"}

    scheduler.register("run_step", handler)
    assert await scheduler.wait_idle(timeout=0.2) is True
    assert calls == 0


@pytest.mark.asyncio
async def test_o_laco_principal_dorme_e_acorda_com_notificacao(scheduler: AgentScheduler):
    """O laço principal dorme sem trabalho e acorda assim que uma operação é submetida."""
    done: list[str] = []

    async def handler(operation: SchedulerOperation):
        """Handler que registra a chave executada pelo laço principal."""
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
    """Submeter uma operação sem tratador registrado devolve erro controlado."""
    scheduler.submit("desconhecido", "x")
    result = await scheduler.run_once()
    assert result is not None and not result.ok
    assert "tratador" in (result.error or "")
