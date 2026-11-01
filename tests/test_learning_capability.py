"""
Arquivo: tests/test_learning_capability.py
Nome: test_learning_capability.py
Propósito: testar a descoberta automática de capacidades do provedor e do ambiente.
Responsabilidade: camada de testes — estrutura do `ProviderCapability`, reportagem
honesta de campos não verificáveis e serialização `to_dict`.
Componentes: ProviderCapability, CapabilityDiscovery, discover_capabilities,
_ollama_context_length, _read_ram_mb.
Dependências: agent.learning.capability_discovery, agent.config, pytest.
Observações: não requer Ollama em execução; campos não verificáveis são
relatados como `desconhecido`/`None`.
"""

from agent.config import Settings
from agent.learning.capability_discovery import (
    CapabilityDiscovery,
    ProviderCapability,
    discover_capabilities,
)


def test_discover_capabilities_retorna_estrutura_completa():
    """A descoberta devolve um ProviderCapability com todos os campos preenchidos."""
    cap = CapabilityDiscovery(Settings()).discover()
    assert isinstance(cap, ProviderCapability)
    assert cap.provider == "ollama"
    assert cap.model_id == "llama3.2"
    assert cap.provider_type == "ollama"
    assert cap.base_url == "http://127.0.0.1:11434"
    assert cap.os is not None
    assert isinstance(cap.cpu_count, int) or cap.cpu_count is None
    assert isinstance(cap.measurement_quality, str)
    assert cap.discovered_at is not None


def test_desconhecido_quando_nao_verificavel():
    """Sem Ollama acessível, streaming/tools/estrutura/visão são False e GPU/VRAM desconhecidos."""
    cap = discover_capabilities(Settings())
    assert cap.supports_streaming is False
    assert cap.supports_tools is False
    assert cap.supports_structured_output is False
    assert cap.supports_vision is False
    assert cap.gpu == "desconhecido"
    assert cap.vram_mb is None
    assert cap.measurement_quality == "estimated"


def test_to_dict_serializa_sem_perder_campos():
    """O dicionário serializado preserva todos os campos do ProviderCapability."""
    cap = CapabilityDiscovery(Settings()).discover()
    d = cap.to_dict()
    esperado = [
        "provider",
        "model_id",
        "provider_type",
        "base_url",
        "os",
        "cpu_count",
        "ram_mb",
        "gpu",
        "vram_mb",
        "context_limit",
        "output_limit",
        "supports_streaming",
        "supports_tools",
        "supports_structured_output",
        "supports_vision",
        "max_concurrent_inferences",
        "latency_observed_ms",
        "measurement_quality",
        "discovered_at",
    ]
    assert list(d.keys()) == esperado
    assert d["provider"] == cap.provider
    assert d["measurement_quality"] == cap.measurement_quality


def test_read_ram_mb_retorna_int_ou_none():
    """A leitura de RAM devolve um inteiro positivo ou None sem levantar exceção."""
    from agent.learning.capability_discovery import _read_ram_mb

    valor = _read_ram_mb()
    assert valor is None or isinstance(valor, int)
    if valor is not None:
        assert valor > 0


def test_ollama_context_length_sem_servidor_retorna_none():
    """Sem servidor Ollama, o contexto real não é verificável (None)."""
    from agent.learning.capability_discovery import _ollama_context_length

    assert _ollama_context_length("http://127.0.0.1:1", "qualquer", timeout=1.0) is None
