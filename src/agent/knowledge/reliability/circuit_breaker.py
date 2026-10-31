"""
Arquivo: src/agent/knowledge/reliability/circuit_breaker.py
Nome: circuit_breaker.py
Propósito: circuit breaker pattern para provedores externos.
Responsabilidade: camada de infraestrutura — previne cascata de falhas.
Componentes: CircuitBreaker, CircuitBreakerState.
Dependências: asyncio, time, enum.
Observações: thread-safe; integra com provedores de busca e browser.
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Estados do circuit breaker."""

    CLOSED = "closed"      # Normal - requisições passam
    OPEN = "open"          # Falhando - bloqueia requisições
    HALF_OPEN = "half_open"  # Testando - permite algumas requisições


class CircuitBreaker:
    """
    Circuit Breaker para provedores externos.

    Previne cascata de falhas:
    - CLOSED: operação normal, conta falhas
    - OPEN: muitas falhas, bloqueia chamadas por timeout
    - HALF_OPEN: após timeout, permite teste para ver se recuperou
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        """Verifica estado atual (pode transicionar automaticamente)."""
        if self._state == CircuitBreakerState.OPEN:
            # Verificar se timeout expirou para HALF_OPEN
            if self._last_failure_time and (time.time() - self._last_failure_time) >= self.timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                self._success_count = 0
        return self._state

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Executa função com proteção do circuit breaker."""
        async with self._lock:
            current_state = self.state

            if current_state == CircuitBreakerState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' está OPEN. Tentativa bloqueada."
                )

        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            await self._on_success()
            return result
        except self.excluded_exceptions:
            raise
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        """Registra sucesso."""
        async with self._lock:
            self._failure_count = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitBreakerState.CLOSED
                    self._success_count = 0

    async def _on_failure(self) -> None:
        """Registra falha."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            self._success_count = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitBreakerState.OPEN

    def get_stats(self) -> dict[str, Any]:
        """Estatísticas do circuit breaker."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
            "timeout": self.timeout,
        }

    def reset(self) -> None:
        """Reseta para estado inicial."""
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None


class CircuitBreakerOpenError(Exception):
    """Erro quando circuit breaker está aberto."""
    pass


class CircuitBreakerRegistry:
    """Registro global de circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                success_threshold=success_threshold,
                timeout=timeout,
            )
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        return self._breakers.get(name)

    def get_all_stats(self) -> dict[str, dict]:
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()


# Instância global
circuit_breaker_registry = CircuitBreakerRegistry()