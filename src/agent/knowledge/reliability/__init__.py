"""
Arquivo: src/agent/knowledge/reliability/__init__.py
Nome: __init__.py
Propósito: exporta a API de confiabilidade, segurança e recuperação.
Responsabilidade: camada de infraestrutura — circuit breaker, retry, limits, recovery, security.
"""
from agent.knowledge.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    circuit_breaker_registry,
)
from agent.knowledge.reliability.retry import (
    RetryPolicy,
    retry_async,
    retry_sync,
    TimeoutManager,
    SEARCH_PROVIDER_POLICY,
    BROWSER_POLICY,
    AI_SERVICE_POLICY,
    GITHUB_API_POLICY,
)
from agent.knowledge.reliability.limits import (
    ResourceLimits,
    ConcurrencyLimiter,
    StorageQuota,
    OperationBudget,
    ResourceLimiter,
    default_limits,
    default_resource_limiter,
)
from agent.knowledge.reliability.recovery import (
    Checkpoint,
    CheckpointManager,
    RecoveryManager,
    auto_recover_on_startup,
)
from agent.knowledge.reliability.security import (
    InputSanitizer,
    CredentialManager,
    AccessControl,
    AuditLogger,
    input_sanitizer,
    access_control,
    audit_logger,
)

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerState",
    "CircuitBreakerOpenError",
    "CircuitBreakerRegistry",
    "circuit_breaker_registry",
    # Retry
    "RetryPolicy",
    "retry_async",
    "retry_sync",
    "TimeoutManager",
    "SEARCH_PROVIDER_POLICY",
    "BROWSER_POLICY",
    "AI_SERVICE_POLICY",
    "GITHUB_API_POLICY",
    # Limits
    "ResourceLimits",
    "ConcurrencyLimiter",
    "StorageQuota",
    "OperationBudget",
    "ResourceLimiter",
    "default_limits",
    "default_resource_limiter",
    # Recovery
    "Checkpoint",
    "CheckpointManager",
    "RecoveryManager",
    "auto_recover_on_startup",
    # Security
    "InputSanitizer",
    "CredentialManager",
    "AccessControl",
    "AuditLogger",
    "input_sanitizer",
    "access_control",
    "audit_logger",
]