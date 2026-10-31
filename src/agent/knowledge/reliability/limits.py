"""
Arquivo: src/agent/knowledge/reliability/limits.py
Nome: limits.py
Propósito: limites de recursos e isolamento para operações do Knowledge Engine.
Responsabilidade: camada de infraestrutura — previne exaustão de recursos.
Componentes: ResourceLimiter, ConcurrencyLimiter, StorageQuota, OperationBudget.
Dependências: asyncio, threading, psutil (opcional), pathlib.
Observações: integra com circuit breaker e retry; configuração por projeto.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class ResourceLimits:
    """Limites de recursos configuráveis."""

    # Concurrency
    max_concurrent_searches: int = 3
    max_concurrent_browser_sessions: int = 1
    max_concurrent_ai_queries: int = 2
    max_concurrent_acquisitions: int = 2

    # Timeouts (segundos)
    search_timeout: float = 30.0
    browser_timeout: float = 120.0
    ai_query_timeout: float = 180.0
    acquisition_timeout: float = 300.0

    # Storage
    max_storage_mb: int = 500          # Limite total de armazenamento
    max_item_size_mb: int = 10         # Limite por item
    max_sources_per_item: int = 20     # Fontes por item
    max_knowledge_items: int = 10000   # Itens totais por projeto

    # Memory
    max_memory_mb: int = 1024          # Limite de memória do processo
    max_context_tokens: int = 4000     # Tokens para injeção no contexto

    # Rate limiting
    requests_per_minute: int = 30      # Requisições por minuto por provedor
    requests_per_hour: int = 500       # Requisições por hora por provedor

    # Cleanup
    cleanup_interval_hours: int = 24   # Intervalo de limpeza
    max_item_age_days: int = 365       # Idade máxima de itens não validados
    failed_item_retention_days: int = 7  # Retenção de itens falhados


class ConcurrencyLimiter:
    """Controla concorrência de operações usando semáforos."""

    def __init__(self, limits: ResourceLimits) -> None:
        self.limits = limits
        self._semaphores: dict[str, asyncio.Semaphore] = {
            "search": asyncio.Semaphore(limits.max_concurrent_searches),
            "browser": asyncio.Semaphore(limits.max_concurrent_browser_sessions),
            "ai_query": asyncio.Semaphore(limits.max_concurrent_ai_queries),
            "acquisition": asyncio.Semaphore(limits.max_concurrent_acquisitions),
        }
        self._active_counts: dict[str, int] = {k: 0 for k in self._semaphores}
        self._lock = asyncio.Lock()

    async def acquire(self, operation: str) -> bool:
        """Tenta adquirir slot para operação."""
        semaphore = self._semaphores.get(operation)
        if not semaphore:
            return True  # Operação desconhecida = sem limite

        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
            async with self._lock:
                self._active_counts[operation] += 1
            return True
        except asyncio.TimeoutError:
            return False

    def release(self, operation: str) -> None:
        """Libera slot."""
        semaphore = self._semaphores.get(operation)
        if semaphore:
            semaphore.release()
            # Contador decrementado automaticamente pelo semáforo

    def get_active_count(self, operation: str) -> int:
        """Contagem atual de operações ativas."""
        return self._active_counts.get(operation, 0)

    def get_stats(self) -> dict[str, Any]:
        return {
            "limits": {k: v._value for k, v in self._semaphores.items()},
            "active": self._active_counts.copy(),
        }


class StorageQuota:
    """Gerencia quota de armazenamento em disco."""

    def __init__(self, limits: ResourceLimits, storage_root: Path) -> None:
        self.limits = limits
        self.storage_root = storage_root
        self._lock = threading.Lock()
        self._cached_size_mb: float | None = None
        self._cache_time: float = 0
        self._cache_ttl = 60  # Cache por 60 segundos

    def get_current_usage_mb(self) -> float:
        """Obtém uso atual em MB (com cache)."""
        now = time.time()
        with self._lock:
            if self._cached_size_mb is not None and (now - self._cache_time) < self._cache_ttl:
                return self._cached_size_mb

            # Calcular tamanho
            total_bytes = 0
            if self.storage_root.exists():
                for file_path in self.storage_root.rglob("*"):
                    if file_path.is_file():
                        try:
                            total_bytes += file_path.stat().st_size
                        except OSError:
                            pass

            self._cached_size_mb = total_bytes / (1024 * 1024)
            self._cache_time = now
            return self._cached_size_mb

    def check_quota(self, additional_mb: float = 0) -> tuple[bool, str]:
        """Verifica se há espaço para additional_mb."""
        current = self.get_current_usage_mb()
        projected = current + additional_mb

        if projected > self.limits.max_storage_mb:
            return False, (
                f"Quota excedida: {current:.1f}MB usado + {additional_mb:.1f}MB = "
                f"{projected:.1f}MB > limite {self.limits.max_storage_mb}MB"
            )

        return True, ""

    def get_available_mb(self) -> float:
        """Espaço disponível em MB."""
        current = self.get_current_usage_mb()
        return max(0, self.limits.max_storage_mb - current)


class OperationBudget:
    """Orçamento por operação (tokens, tempo, chamadas)."""

    def __init__(self, limits: ResourceLimits) -> None:
        self.limits = limits
        self._budgets: dict[str, dict[str, float]] = {}
        self._lock = asyncio.Lock()

    async def check_budget(
        self,
        operation: str,
        estimated_tokens: int = 0,
        estimated_time: float = 0,
        estimated_calls: int = 1,
    ) -> tuple[bool, str]:
        """Verifica se operação cabe no orçamento."""
        async with self._lock:
            budget = self._budgets.setdefault(operation, {
                "tokens_used": 0,
                "time_used": 0.0,
                "calls_used": 0,
                "reset_time": time.time() + 60,  # Reset por minuto
            })

            # Reset se minuto mudou
            if time.time() >= budget["reset_time"]:
                budget["tokens_used"] = 0
                budget["time_used"] = 0.0
                budget["calls_used"] = 0
                budget["reset_time"] = time.time() + 60

            # Verificar limites
            if budget["tokens_used"] + estimated_tokens > self.limits.max_context_tokens:
                return False, f"Orçamento de tokens excedido para {operation}"

            if budget["calls_used"] + estimated_calls > self.limits.requests_per_minute:
                return False, f"Rate limit excedido para {operation}"

            return True, ""

    async def consume(
        self,
        operation: str,
        tokens: int = 0,
        time_sec: float = 0,
        calls: int = 1,
    ) -> None:
        """Consome orçamento."""
        async with self._lock:
            budget = self._budgets.setdefault(operation, {
                "tokens_used": 0,
                "time_used": 0.0,
                "calls_used": 0,
                "reset_time": time.time() + 60,
            })
            budget["tokens_used"] += tokens
            budget["time_used"] += time_sec
            budget["calls_used"] += calls

    def get_budget_status(self, operation: str) -> dict[str, Any]:
        """Status do orçamento."""
        budget = self._budgets.get(operation, {})
        return {
            "tokens_used": budget.get("tokens_used", 0),
            "time_used": budget.get("time_used", 0.0),
            "calls_used": budget.get("calls_used", 0),
            "tokens_limit": self.limits.max_context_tokens,
            "calls_limit": self.limits.requests_per_minute,
        }


class ResourceLimiter:
    """Orquestrador principal de limites de recursos."""

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.limits = limits or ResourceLimits()
        self.storage_root = storage_root or Path("data/knowledge")

        self.concurrency = ConcurrencyLimiter(self.limits)
        self.storage = StorageQuota(self.limits, self.storage_root)
        self.budget = OperationBudget(self.limits)

    async def check_all(
        self,
        operation: str,
        estimated_tokens: int = 0,
        estimated_time: float = 0,
        estimated_storage_mb: float = 0,
    ) -> tuple[bool, str]:
        """Verifica todos os limites antes de operação."""
        # Concorrência
        can_acquire = await self.concurrency.acquire(operation)
        if not can_acquire:
            return False, f"Limite de concorrência atingido para {operation}"

        # Storage
        ok, msg = self.storage.check_quota(estimated_storage_mb)
        if not ok:
            await self.concurrency.release(operation)
            return False, msg

        # Orçamento
        ok, msg = await self.budget.check_budget(operation, estimated_tokens, estimated_time)
        if not ok:
            await self.concurrency.release(operation)
            return False, msg

        return True, ""

    async def release(self, operation: str, tokens: int = 0, time_sec: float = 0) -> None:
        """Libera recursos após operação."""
        self.concurrency.release(operation)
        await self.budget.consume(operation, tokens, time_sec)

    def get_system_stats(self) -> dict[str, Any]:
        """Estatísticas do sistema."""
        stats = {
            "concurrency": self.concurrency.get_stats(),
            "storage_mb": self.storage.get_current_usage_mb(),
            "storage_available_mb": self.storage.get_available_mb(),
            "budgets": {op: self.budget.get_budget_status(op) for op in self.budget._budgets},
        }

        # Memória do processo
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process(os.getpid())
                mem = process.memory_info()
                stats["process_memory_mb"] = mem.rss / (1024 * 1024)
            except Exception:
                pass

        return stats


# Instância padrão
default_limits = ResourceLimits()
default_resource_limiter = ResourceLimiter(default_limits)