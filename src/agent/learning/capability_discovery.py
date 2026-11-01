"""
Arquivo: src/agent/learning/capability_discovery.py
Nome: capability_discovery.py
Propósito: descoberta automática de capacidades do provedor e do ambiente.
Responsabilidade: camada de aplicação — identifica SO, CPU, RAM, GPU, VRAM,
provedor conectado, modelo, limite de contexto, suporte a streaming, ferramentas,
saída estruturada e visão, limites de concorrência e latência observada. Marca como
desconhecido quando não é verificável, nunca presumindo que a configuração declarada
pelo modelo corresponde às capacidades reais do servidor.
Componentes: ProviderCapability, CapabilitySource, CapabilityDiscovery,
discover_capabilities.
Dependências: platform, os, subprocess, datetime, typing, httpx,
agent.config (Settings), agent.providers.registry (catalog_for_settings).
Observações: consulta /api/tags do Ollama para obter o contexto real do modelo
(details.context_length) em vez de confiar no valor declarado. Sem psutil: RAM/GPU
são lidas quando disponíveis via stdlib e marcadas como desconhecido caso contrário.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from agent.config import Settings
from agent.providers.registry import catalog_for_settings

UNKNOWN: str = "desconhecido"


@dataclass(frozen=True)
class ProviderCapability:
    """Capacidade observada de um provedor/modelo.

    Atributos:
        provider: nome do provedor (ollama, openrouter, openai_compatible...).
        model_id: identificador do modelo.
        provider_type: tipo do provedor (ollama, llamacpp...).
        base_url: URL base do provedor.
        os: sistema operacional do host.
        cpu_count: quantidade de CPUs lógicas.
        ram_mb: memória RAM total em MB.
        gpu: GPU detectada (desconhecido quando não verificável).
        vram_mb: VRAM em MB (desconhecido quando não verificável).
        context_limit: limite de janela de contexto em tokens.
        output_limit: limite de tokens de saída.
        supports_streaming: se o provedor suporta streaming.
        supports_tools: se o provedor suporta chamada de ferramentas.
        supports_structured_output: se o provedor suporta saída estruturada (JSON schema).
        supports_vision: se o provedor suporta visão.
        max_concurrent_inferences: limite de inferências simultâneas.
        latency_observed_ms: latência observada da última medição (ms).
        measurement_quality: origem dos dados (provider_reported, locally_counted, estimated, unavailable).
        discovered_at: instante da descoberta.
    """

    provider: str
    model_id: str
    provider_type: str
    base_url: str
    os: str | None = None
    cpu_count: int | None = None
    ram_mb: int | None = None
    gpu: str | None = None
    vram_mb: int | None = None
    context_limit: int | None = None
    output_limit: int | None = None
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    max_concurrent_inferences: int = 1
    latency_observed_ms: int | None = None
    measurement_quality: str = "unavailable"
    discovered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário serializável."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "os": self.os,
            "cpu_count": self.cpu_count,
            "ram_mb": self.ram_mb,
            "gpu": self.gpu,
            "vram_mb": self.vram_mb,
            "context_limit": self.context_limit,
            "output_limit": self.output_limit,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "supports_structured_output": self.supports_structured_output,
            "supports_vision": self.supports_vision,
            "max_concurrent_inferences": self.max_concurrent_inferences,
            "latency_observed_ms": self.latency_observed_ms,
            "measurement_quality": self.measurement_quality,
            "discovered_at": self.discovered_at,
        }


def _read_ram_mb() -> int | None:
    """Lê a memória RAM total em MB usando stdlib; retorna None quando indisponível."""
    try:
        system = platform.system()
        if system == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return int(out.stdout.strip()) // (1024 * 1024)
        elif system == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb // 1024
    except Exception:
        return None
    return None


def _ollama_context_length(base_url: str, model_id: str, timeout: float = 5.0) -> int | None:
    """Consulta /api/tags do Ollama para o contexto real do modelo.

    Args:
        base_url: URL base do Ollama.
        model_id: identificador do modelo.
        timeout: tempo limite da requisição.

    Returns:
        O contexto (details.context_length) do modelo, ou None quando não verificável.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/tags")
            if resp.status_code != 200:
                return None
            for m in (resp.json() or {}).get("models") or []:
                if m.get("name") == model_id:
                    details = m.get("details") or {}
                    ctx = details.get("context_length")
                    if isinstance(ctx, int):
                        return ctx
    except Exception:
        return None
    return None


class CapabilityDiscovery:
    """Descobre capacidades do provedor conectado e do ambiente."""

    def __init__(self, settings: Settings) -> None:
        """Cria a descoberta ligada às configurações do processo.

        Args:
            settings: configurações do processo.
        """
        self._settings = settings

    def discover(self) -> ProviderCapability:
        """Executa a descoberta de capacidades.

        Returns:
            As capacidades observadas; campos não verificáveis são None/'desconhecido'.
        """
        s = self._settings
        provider_name = s.default_provider
        model_id = s.default_model_id
        base_url = s.ollama_base_url
        provider_type = "ollama"

        # Capacidades declaradas pelo provedor (via catálogo/registro).
        supports_streaming = False
        supports_tools = False
        supports_structured_output = False
        supports_vision = False
        measurement_quality = "unavailable"

        try:
            catalog = catalog_for_settings(s)
            provider = catalog.build(provider_name, s)
            caps = provider.capabilities()
            supports_streaming = bool(caps.streaming)
            supports_tools = bool(caps.tools)
            supports_structured_output = bool(caps.structured_output)
            supports_vision = bool(caps.vision)
            measurement_quality = "provider_reported"
        except Exception:
            # Provedor não instanciável: mantém valores default (falsos) e
            # measurement_quality = unavailable.
            pass

        # Contexto real do modelo via /api/tags (Ollama), quando disponível.
        context_limit = s.default_context_limit
        ctx_quality = "estimated"
        try:
            real_ctx = _ollama_context_length(base_url, model_id)
            if real_ctx is not None:
                context_limit = real_ctx
                ctx_quality = "provider_reported"
        except Exception:
            real_ctx = None
        if measurement_quality == "provider_reported":
            measurement_quality = ctx_quality
        else:
            measurement_quality = "estimated"

        # Ambiente (somente o que é verificável com stdlib).
        os_name = platform.system() or UNKNOWN
        os_release = platform.release() or ""
        os_full = f"{os_name} {os_release}".strip() or UNKNOWN
        cpu_count = os.cpu_count()
        ram_mb = _read_ram_mb()

        return ProviderCapability(
            provider=provider_name,
            model_id=model_id,
            provider_type=provider_type,
            base_url=base_url,
            os=os_full,
            cpu_count=cpu_count,
            ram_mb=ram_mb,
            gpu=UNKNOWN,
            vram_mb=None,
            context_limit=context_limit,
            output_limit=s.default_output_reserve,
            supports_streaming=supports_streaming,
            supports_tools=supports_tools,
            supports_structured_output=supports_structured_output,
            supports_vision=supports_vision,
            max_concurrent_inferences=s.max_concurrent_inferences,
            latency_observed_ms=None,
            measurement_quality=measurement_quality,
        )


def discover_capabilities(settings: Settings) -> ProviderCapability:
    """Função de conveniência para descobrir capacidades do provedor.

    Args:
        settings: configurações do processo.

    Returns:
        As capacidades observadas.
    """
    return CapabilityDiscovery(settings).discover()
