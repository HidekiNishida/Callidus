"""
Arquivo: src/agent/services/agent_scheduler.py
Nome: agent_scheduler.py
Propósito: escolher a próxima operação elegível e executá-la, uma por vez.
Responsabilidade: camada de aplicação — fila ordenada de operações do processo.
Componentes: AgentScheduler, SchedulerOperation, OperationResult.
Dependências: agent.config.
Observações: nenhuma inferência é feita para descobrir se existe trabalho; a fila dorme até ser notificada.

Escolhe a próxima operação elegível e a executa — uma por vez.

O escalonador existe porque a hierarquia de agentes precisa de três garantias que
não vêm de convenção:

- **Exclusividade.** Só uma operação de inferência por vez. A garantia é do executor
  compartilhado ([`agent.services.executor`][agent.services.executor]); o escalonador
  só garante que não duas operações ficam pendentes ao mesmo tempo.
- **Sem espera que gasta token.** O escalonador dorme numa fila de eventos. Nenhuma
  inferência é feita para "descobrir se existe trabalho": quem produz trabalho
  (o fim de uma tarefa, uma consulta criada, um run novo) **notifica**.
- **Sem bloqueio coletivo.** Uma operação bloqueada ou com erro não impede as outras:
  ela é registrada, o erro fica no estado e a fila segue.

Ordenação: prioridade, e empate resolvido pelo tempo de espera — assim uma operação
urgente não passa à frente de tudo, e uma operação antiga não é adiada para sempre.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent.config import Settings, get_settings

__all__ = ["AgentScheduler", "SchedulerOperation", "OperationResult"]


@dataclass
class SchedulerOperation:
    """Uma operação elegível (executar uma etapa, responder uma consulta, retomar um agente)."""

    kind: str
    key: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    enqueued_at: float = field(default_factory=time.monotonic)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def age(self) -> float:
        """Tempo que a operação espera na fila, em segundos.

        Returns:
            Os segundos decorridos desde a entrada na fila.
        """
        return time.monotonic() - self.enqueued_at


@dataclass
class OperationResult:
    """Desfecho de uma operação. `ok=False` não interrompe a fila."""

    operation_id: str
    kind: str
    key: str
    ok: bool
    action: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Desfecho como dicionário serializável.

        Returns:
            Um dicionário com os campos do desfecho.
        """
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "key": self.key,
            "ok": self.ok,
            "action": self.action,
            "detail": self.detail,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


Handler = Callable[[SchedulerOperation], Awaitable[dict[str, Any] | None]]


class AgentScheduler:
    """Fila de operações elegíveis, executadas uma a uma.

    O escalonador não conhece inferência: conhece *operações*. Quem sabe inferir
    (o orquestrador, o serviço de consultas) registra o tratador.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        operation_timeout_sec: float | None = None,
    ) -> None:
        """Monta o escalonador com a sessão e a política de agentes."""
        self._settings = settings or get_settings()
        self._timeout = operation_timeout_sec or float(
            getattr(self._settings, "agent_operation_timeout_sec", 300.0)
        )
        self._queue: asyncio.Queue[SchedulerOperation] = asyncio.Queue()
        self._pending: dict[str, SchedulerOperation] = {}
        self._handlers: dict[str, Handler] = {}
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._wakeup = asyncio.Event()
        self._stopped = False
        self._history: list[OperationResult] = []
        self._stats = {
            "submitted": 0,
            "executed": 0,
            "failed": 0,
            "duplicates": 0,
            "timeouts": 0,
        }

    # ------------------------------------------------------------- handlers

    def register(self, kind: str, handler: Handler) -> None:
        """Registra quem executa um tipo de operação.

        Args:
            kind: tipo de operação.
            handler: tratador assíncrono da operação.
        """
        self._handlers[kind] = handler

    # ------------------------------------------------------------- submissão

    def submit(
        self,
        kind: str,
        key: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
    ) -> bool:
        """Enfileira uma operação. `False` quando a mesma chave já está pendente.

        A chave é o que evita duplicidade: a mesma etapa do mesmo run não entra duas
        vezes na fila.

        Args:
            kind: tipo de operação.
            key: chave de identidade, usada para evitar duplicidade.
            payload: dados da operação.
            priority: prioridade; maior significa mais urgente.

        Returns:
            `True` quando a operação foi enfileirada.
        """
        if self._stopped:
            return False
        if key in self._pending:
            self._stats["duplicates"] += 1
            return False
        operation = SchedulerOperation(
            kind=kind, key=key, payload=dict(payload or {}), priority=priority
        )
        self._pending[key] = operation
        self._queue.put_nowait(operation)
        self._idle.clear()
        self._wakeup.set()
        self._stats["submitted"] += 1
        return True

    def pending_keys(self) -> list[str]:
        """Chaves das operações pendentes.

        Returns:
            A lista de chaves ainda na fila.
        """
        return list(self._pending)

    def stats(self) -> dict[str, Any]:
        """Contadores da fila.

        Returns:
            Um dicionário com as estatísticas de submissão, execução e pendência.
        """
        return {**self._stats, "pending": len(self._pending), "inflight": self._inflight}

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Desfechos recentes das operações executadas.

        Args:
            limit: quantidade máxima de desfechos devolvidos.

        Returns:
            A lista de desfechos, do mais antigo ao mais recente.
        """
        return [result.as_dict() for result in self._history[-limit:]]

    # ------------------------------------------------------------ execução

    async def _pick(self) -> SchedulerOperation | None:
        """Retira a próxima operação, respeitando prioridade e tempo de espera.

        Among the operations already queued, the most urgent wins; ties go to the one
        that has waited longer. Nothing is delayed indefinitely.

        Returns:
            A operação escolhida, ou `None` quando a fila está vazia.
        """
        try:
            first = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        candidates = [first]
        while len(candidates) < 50:
            try:
                candidates.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        best = min(candidates, key=lambda op: (-op.priority, op.enqueued_at))
        for other in candidates:
            if other is not best:
                self._queue.put_nowait(other)
        return best

    async def execute(self, operation: SchedulerOperation) -> OperationResult:
        """Executa uma operação com tempo limite; erro não derruba a fila.

        Args:
            operation: operação a executar.

        Returns:
            O desfecho da operação, com sucesso, erro ou estouro de tempo.
        """
        handler = self._handlers.get(operation.kind)
        started = time.monotonic()
        if handler is None:
            result = OperationResult(
                operation_id=operation.id,
                kind=operation.kind,
                key=operation.key,
                ok=False,
                error=f"nenhum tratador registrado para '{operation.kind}'",
            )
            self._history.append(result)
            return result
        try:
            outcome = await asyncio.wait_for(handler(operation), timeout=self._timeout)
        except asyncio.TimeoutError:
            self._stats["timeouts"] += 1
            result = OperationResult(
                operation_id=operation.id,
                kind=operation.kind,
                key=operation.key,
                ok=False,
                error=f"tempo limite de {self._timeout:.0f}s excedido",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a fila não pode morrer por causa de uma operação
            self._stats["failed"] += 1
            result = OperationResult(
                operation_id=operation.id,
                kind=operation.kind,
                key=operation.key,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        else:
            self._stats["executed"] += 1
            detail = dict(outcome or {})
            action = str(detail.pop("action", ""))
            result = OperationResult(
                operation_id=operation.id,
                kind=operation.kind,
                key=operation.key,
                ok=not detail.pop("error", None),
                action=action,
                detail=detail,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        self._history.append(result)
        return result

    async def run_once(self) -> OperationResult | None:
        """Executa a próxima operação elegível. `None` quando não há nada pendente.

        Returns:
            O desfecho da operação executada, ou `None` quando a fila estava vazia.
        """
        operation = await self._pick()
        if operation is None:
            self._sync_idle()
            return None
        self._pending.pop(operation.key, None)
        self._inflight += 1
        self._idle.clear()
        try:
            return await self.execute(operation)
        finally:
            self._inflight -= 1
            self._sync_idle()

    def _sync_idle(self) -> None:
        """Marca o escalonador como ocioso quando não há pendências nem operação em curso."""
        if not self._pending and self._inflight == 0:
            self._idle.set()

    async def run_forever(self) -> None:
        """Laço principal. Dorme na fila — nenhuma inferência para procurar trabalho.

        Observações:
            O laço só acorda quando há operação pendente ou quando alguém notifica a fila.
        """
        while not self._stopped:
            self._wakeup.clear()
            result = await self.run_once()
            if result is not None:
                continue
            if self._pending:
                continue
            await self._wakeup.wait()

    async def wait_idle(self, timeout: float | None = None) -> bool:
        """Espera a fila esvaziar — sem consumir token. `True` se esvaziou no prazo.

        Args:
            timeout: tempo de espera, em segundos; `None` espera indefinidamente.

        Returns:
            `True` quando a fila esvaziou dentro do prazo.
        """
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def stop(self) -> None:
        """Interrompe o laço do escalonador.

        Observações:
            As operações já enfileiradas deixam de ser aceitas para nova submissão.
        """
        self._stopped = True
