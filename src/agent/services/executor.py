# src/agent/services/executor.py — executor compartilhado de inferência
"""Ponto único de admissão das inferências do processo.

O Callidus foi desenhado para máquinas modestas: manter **um** modelo carregado e, no
máximo, **uma** inferência ativa é o que torna viável uma hierarquia recursiva de
agentes. Sem esse controle, `N` agentes existindo significariam `N` inferências
simultâneas — que é exatamente o que a arquitetura precisa evitar.

Por que aqui, e não por convenção:

- Todos os provedores passam por [`agent.providers.base.LLMProvider`](../providers/base.py),
  que aplica a janela de exclusividade em `chat`/`chat_streaming`. Qualquer rota de
  chamada (runner, ciclo de ferramentas, decomposição, worker autônomo, endpoint de
  depuração, consulta entre agentes) herda a garantia sem conhecer o executor.
- A exclusividade é aplicada no **processo**, não por tarefa nem por laço de eventos:
  duas requisições HTTP simultâneas, o worker em segundo plano e uma tarefa de
  background disputam o mesmo slot.

Escopo real da garantia:

| Recurso | Limitado a 1 inferência? |
|---------|---------------------------|
| Várias sessões do SQLite, no mesmo processo e laço | sim |
| Vários threads com laços de eventos diferentes | sim (o contador é global do processo) |
| Vários processos (várias instâncias da API) | **não** — o controle é em memória |

O limite entre processos exigiria uma trava externa (banco, socket, arquivo), o que
não se justifica para uma instalação local de um usuário só. A garantia é de processo,
e está documentada como tal.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

from agent.config import Settings, get_settings

__all__ = [
    "ExecutionSlot",
    "ExecutorMetrics",
    "InferenceExecutor",
    "get_executor",
    "reset_executor",
]


@dataclass
class ExecutorMetrics:
    """Contadores observáveis. Só mede o que o executor sabe de fato: tempos de espera e
    concorrência de inferências — não tokens nem memória, que dependem do backend."""

    inferences_started: int = 0
    inferences_completed: int = 0
    inferences_failed: int = 0
    inferences_cancelled: int = 0
    waits: int = 0
    wait_seconds: float = 0.0
    active: int = 0
    max_active: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "inferences_started": self.inferences_started,
            "inferences_completed": self.inferences_completed,
            "inferences_failed": self.inferences_failed,
            "inferences_cancelled": self.inferences_cancelled,
            "waits": self.waits,
            "wait_seconds": round(self.wait_seconds, 4),
            "active": self.active,
            "max_active": self.max_active,
        }


@dataclass
class ExecutionSlot:
    """Uma inferência admitida. `waited_seconds` é o tempo parado na fila do executor."""

    purpose: str = ""
    provider: str = ""
    model: str = ""
    waited_seconds: float = 0.0
    released: bool = False


class InferenceExecutor:
    """Serializa as inferências do processo até o limite configurado.

    O controle é um contador global protegido por `threading.Lock` — não um semáforo do
    `asyncio`. A diferença importa: um semáforo pertence ao laço de eventos que o
    criou, então dois threads com laços diferentes infeririam ao mesmo tempo. Com o
    contador global, a exclusividade vale para o processo inteiro.

    A espera é feita com um `asyncio.Event` por laço de eventos, acordado de forma
    segura entre threads (`call_soon_threadsafe`).
    """

    def __init__(self, limit: int = 1) -> None:
        if int(limit) < 1:
            raise ValueError("o limite de inferências simultâneas deve ser >= 1")
        self._limit = int(limit)
        # Conta as inferências ativas do PROCESSO (todos os threads e laços).
        self._active = 0
        self._lock = threading.Lock()
        # Um evento de espera por laço de eventos, para acordar o thread certo.
        self._waiters: dict[int, tuple[Any, asyncio.Event]] = {}
        self._metrics = ExecutorMetrics()
        self._metrics_lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, limit: int) -> None:
        """Muda o limite. A nova valer vale para as próximas aquisições."""
        if int(limit) < 1:
            raise ValueError("o limite de inferências simultâneas deve ser >= 1")
        with self._lock:
            self._limit = int(limit)

    def _waiter(self, loop: Any) -> asyncio.Event:
        key = id(loop)
        entry = self._waiters.get(key)
        if entry is None or entry[0] is not loop:
            entry = (loop, asyncio.Event())
            self._waiters[key] = entry
        return entry[1]

    def _wake_all(self) -> None:
        """Acorda todos os laços em espera (chamado quando um slot é devolvido)."""
        for loop, event in list(self._waiters.values()):
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # pragma: no cover - laço já fechado
                continue

    async def acquire(self, *, purpose: str = "", provider: str = "", model: str = "") -> ExecutionSlot:
        """Toma o slot de inferência. O chamador é responsável por `release()`."""
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        contended = False
        while True:
            with self._lock:
                event = self._waiter(loop)
                # Limpar antes de checar evita perder o aviso de um slot freed: se
                # outro slot foi tomado, o próximo `release` acorda este laço de novo.
                event.clear()
                if self._active < self._limit:
                    self._active += 1
                    break
                contended = True
            await event.wait()
        waited = time.monotonic() - started if contended else 0.0
        with self._metrics_lock:
            metrics = self._metrics
            metrics.inferences_started += 1
            metrics.active = self._active
            metrics.max_active = max(metrics.max_active, self._active)
            metrics.wait_seconds += waited
            if contended:
                metrics.waits += 1
        return ExecutionSlot(
            purpose=purpose,
            provider=provider,
            model=model,
            waited_seconds=waited,
        )

    def release(self, *, error: BaseException | None = None, slot: ExecutionSlot | None = None) -> None:
        """Devolve o slot. `error` distingue falha, cancelamento e sucesso.

        É idempotente quando recebe o mesmo `slot`: um `finally` que libera duas vezes
        não corrompe a contagem.
        """
        if slot is not None and slot.released:
            return
        with self._lock:
            if slot is not None:
                slot.released = True
            self._active = max(0, self._active - 1)
            active = self._active
        with self._metrics_lock:
            metrics = self._metrics
            metrics.active = active
            if isinstance(error, asyncio.CancelledError):
                metrics.inferences_cancelled += 1
            elif error is not None:
                metrics.inferences_failed += 1
            else:
                metrics.inferences_completed += 1
        self._wake_all()

    def metrics(self) -> ExecutorMetrics:
        with self._metrics_lock:
            snapshot = replace(self._metrics)
        snapshot.active = self._active
        return snapshot


_EXECUTOR: InferenceExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()
_SETTINGS: Settings | None = None


def get_executor(settings: Settings | None = None) -> InferenceExecutor:
    """Executor compartilhado do processo. Cria no primeiro uso e ajusta o limite quando
    as configurações mudam (o limite vem de `MAX_CONCURRENT_INFERENCES`)."""
    global _EXECUTOR, _SETTINGS
    if settings is not None:
        _SETTINGS = settings
    elif _SETTINGS is None:
        _SETTINGS = get_settings()
    limit = int(getattr(_SETTINGS, "max_concurrent_inferences", 1) or 1)
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = InferenceExecutor(limit)
        else:
            _EXECUTOR.set_limit(limit)
        return _EXECUTOR


def reset_executor() -> None:
    """Descarta o executor do processo (isolamento de testes)."""
    global _EXECUTOR, _SETTINGS
    with _EXECUTOR_LOCK:
        _EXECUTOR = None
        _SETTINGS = None
