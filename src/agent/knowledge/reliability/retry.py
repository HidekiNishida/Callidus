"""
Arquivo: src/agent/knowledge/reliability/retry.py
Nome: retry.py
Propósito: retry com backoff exponencial e timeout para operações externas.
Responsabilidade: camada de infraestrutura — resiliência para chamadas de rede.
Componentes: RetryPolicy, retry_async, retry_sync, TimeoutManager.
Dependências: asyncio, random, time, typing.
Observações: jitter para evitar thundering herd; configuração por provedor.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Política de retry configurável."""

    max_attempts: int = 3
    base_delay: float = 1.0          # Delay inicial em segundos
    max_delay: float = 60.0          # Delay máximo
    exponential_base: float = 2.0    # Base para backoff exponencial
    jitter: float = 0.1              # Jitter fraction (0-1)
    timeout: float | None = None     # Timeout total da operação
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        IOError,
    )

    def calculate_delay(self, attempt: int) -> float:
        """Calcula delay com backoff exponencial e jitter."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay,
        )
        # Adicionar jitter
        jitter_range = delay * self.jitter
        return delay + random.uniform(-jitter_range, jitter_range)


async def retry_async(
    func: Callable[..., T],
    *args,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
    **kwargs,
) -> T:
    """
    Executa função assíncrona com retry policy.

    Args:
        func: Função async para executar
        *args: Argumentos posicionais
        policy: RetryPolicy (usa padrão se None)
        on_retry: Callback chamado em cada retry (exception, attempt)
        **kwargs: Argumentos nomeados

    Returns:
        Resultado da função

    Raises:
        Última exceção se todas as tentativas falharem
    """
    policy = policy or RetryPolicy()
    last_exception = None

    start_time = time.time()

    for attempt in range(policy.max_attempts):
        # Verificar timeout total
        if policy.timeout and (time.time() - start_time) >= policy.timeout:
            raise TimeoutError(f"Timeout total excedido ({policy.timeout}s)")

        try:
            return await func(*args, **kwargs)
        except policy.retryable_exceptions as e:
            last_exception = e

            if attempt == policy.max_attempts - 1:
                # Última tentativa - não retry
                break

            delay = policy.calculate_delay(attempt)

            if on_retry:
                try:
                    on_retry(e, attempt + 1)
                except Exception:
                    pass

            await asyncio.sleep(delay)

    # Todas as tentativas falharam
    raise last_exception or RuntimeError("Retry falhou sem exceção")


def retry_sync(
    func: Callable[..., T],
    *args,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
    **kwargs,
) -> T:
    """
    Executa função síncrona com retry policy.

    Args:
        func: Função sync para executar
        *args: Argumentos posicionais
        policy: RetryPolicy (usa padrão se None)
        on_retry: Callback chamado em cada retry (exception, attempt)
        **kwargs: Argumentos nomeados

    Returns:
        Resultado da função

    Raises:
        Última exceção se todas as tentativas falharem
    """
    policy = policy or RetryPolicy()
    last_exception = None

    start_time = time.time()

    for attempt in range(policy.max_attempts):
        # Verificar timeout total
        if policy.timeout and (time.time() - start_time) >= policy.timeout:
            raise TimeoutError(f"Timeout total excedido ({policy.timeout}s)")

        try:
            return func(*args, **kwargs)
        except policy.retryable_exceptions as e:
            last_exception = e

            if attempt == policy.max_attempts - 1:
                break

            delay = policy.calculate_delay(attempt)

            if on_retry:
                try:
                    on_retry(e, attempt + 1)
                except Exception:
                    pass

            time.sleep(delay)

    raise last_exception or RuntimeError("Retry falhou sem exceção")


class TimeoutManager:
    """Gerenciador de timeouts para operações concorrentes."""

    def __init__(self, default_timeout: float = 30.0) -> None:
        self.default_timeout = default_timeout
        self._timeouts: dict[str, float] = {}

    def set_timeout(self, operation: str, timeout: float) -> None:
        """Define timeout para operação específica."""
        self._timeouts[operation] = timeout

    def get_timeout(self, operation: str) -> float:
        """Obtém timeout para operação."""
        return self._timeouts.get(operation, self.default_timeout)

    async def run_with_timeout(
        self,
        operation: str,
        coro: Any,
        timeout: float | None = None,
    ) -> Any:
        """Executa corrotina com timeout."""
        actual_timeout = timeout or self.get_timeout(operation)
        try:
            return await asyncio.wait_for(coro, timeout=actual_timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Operação '{operation}' excedeu timeout de {actual_timeout}s")


# Políticas pré-definidas para provedores conhecidos
SEARCH_PROVIDER_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    exponential_base=2.0,
    jitter=0.2,
    timeout=30.0,
)

BROWSER_POLICY = RetryPolicy(
    max_attempts=2,
    base_delay=2.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=0.1,
    timeout=120.0,
)

AI_SERVICE_POLICY = RetryPolicy(
    max_attempts=2,
    base_delay=5.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=0.1,
    timeout=180.0,
)

GITHUB_API_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exponential_base=2.0,
    jitter=0.1,
    timeout=30.0,
)