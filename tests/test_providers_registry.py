"""
Arquivo: tests/test_providers_registry.py
Nome: test_providers_registry.py
Propósito: verificar a configuração declarativa de provedores, da leitura do arquivo à construção de cada tipo.
Responsabilidade: camada de testes — comportamento do catálogo de provedores (carga, validação e construção).
Componentes: carga de YAML e JSON com interpolação de ambiente, valor padrão de variável, recusa de tipo, opção e URL inválidos, provedor padrão inexistente, arquivo ausente, construção por tipo e por ambiente, exemplo versionado e sigilo da credencial.
Dependências: agent.providers.registry (ProviderCatalog, build_provider, catalog_for_settings, load_catalog, interpolate_text), agent.config.Settings, pytest.
Observações: arquivos de configuração temporários e variáveis de ambiente definidas por monkeypatch; nenhuma credencial real é usada.

configuração declarativa de provedores
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from agent.config import Settings
from agent.providers.base import ProviderConfigError
from agent.providers.registry import (
    ProviderCatalog,
    build_provider,
    catalog_for_settings,
    interpolate_text,
    load_catalog,
)
from agent.providers.anthropic import AnthropicProvider
from agent.providers.gemini import GeminiProvider
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.mock import MockProvider
from agent.providers.ollama import OllamaProvider
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.openrouter import OpenRouterProvider

YAML_CONFIG = """
default_provider: ollama_remote

providers:
  ollama_local:
    type: ollama
    base_url: http://localhost:11434
    model: llama3.2

  ollama_remote:
    type: ollama
    base_url: ${CALLIDUS_OLLAMA_URL}
    model: qwen3:8b
    api_key_env: CALLIDUS_OLLAMA_API_KEY
    timeout: 30

  openrouter:
    type: openrouter
    base_url: https://openrouter.ai/api/v1
    model: autor/modelo
    api_key_env: OPENROUTER_API_KEY
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Grava o conteúdo no arquivo indicado e devolve o caminho."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_yaml_config_is_loaded_with_env_interpolation(tmp_path, monkeypatch):
    """O arquivo YAML é carregado com as variáveis de ambiente interpoladas na URL e nos demais campos."""
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "https://vps.exemplo:11434")
    path = _write(tmp_path, "providers.yaml", YAML_CONFIG)
    catalog = load_catalog(path)

    assert catalog.default_provider == "ollama_remote"
    assert set(catalog.names()) == {"ollama_local", "ollama_remote", "openrouter"}

    spec = catalog.spec("ollama_remote")
    assert spec.base_url == "https://vps.exemplo:11434"
    assert spec.api_key_env == "CALLIDUS_OLLAMA_API_KEY"
    assert spec.timeout == 30


def test_json_config_is_supported(tmp_path):
    """Um arquivo de configuração em JSON também é carregado."""
    path = _write(
        tmp_path,
        "providers.json",
        json.dumps({"providers": {"local": {"type": "ollama", "base_url": "http://127.0.0.1:11434"}}}),
    )
    catalog = load_catalog(path)
    assert catalog.spec("local").kind == "ollama"


def test_missing_env_variable_is_a_configuration_error(tmp_path):
    """Uma variável de ambiente ausente é reportada como erro de configuração, com o nome da variável."""
    path = _write(
        tmp_path,
        "providers.yaml",
        "providers:\n  remoto:\n    type: ollama\n    base_url: ${CALLIDUS_NAO_EXISTE}\n",
    )
    with pytest.raises(ProviderConfigError) as exc:
        load_catalog(path)
    assert "CALLIDUS_NAO_EXISTE" in str(exc.value)


def test_env_variable_with_default_value(tmp_path, monkeypatch):
    """Uma variável opcional sem valor usa o valor padrão declarado na configuração."""
    monkeypatch.delenv("CALLIDUS_OPCIONAL", raising=False)
    path = _write(
        tmp_path,
        "providers.yaml",
        "providers:\n  local:\n    type: ollama\n    base_url: ${CALLIDUS_OPCIONAL:-http://127.0.0.1:11434}\n",
    )
    catalog = load_catalog(path)
    assert catalog.spec("local").base_url == "http://127.0.0.1:11434"


def test_interpolation_keeps_value_when_variable_is_set(monkeypatch):
    """A interpolação substitui a variável pelo valor definido no ambiente."""
    monkeypatch.setenv("X_TOKEN", "abc123")
    assert interpolate_text("Bearer ${X_TOKEN}") == "Bearer abc123"


def test_unknown_provider_type_is_rejected(tmp_path):
    """Um tipo de provedor desconhecido é recusado na carga do catálogo."""
    path = _write(tmp_path, "providers.yaml", "providers:\n  x:\n    type: inexistente\n")
    with pytest.raises(ProviderConfigError) as exc:
        load_catalog(path)
    assert "inexistente" in str(exc.value)


def test_unknown_option_is_rejected(tmp_path):
    """Uma opção não suportada na especificação do provedor é recusada."""
    path = _write(tmp_path, "providers.yaml", "providers:\n  x:\n    type: ollama\n    cor: azul\n")
    with pytest.raises(ProviderConfigError):
        load_catalog(path)


def test_default_provider_must_exist(tmp_path):
    """O provedor padrão declarado precisa existir no catálogo."""
    path = _write(tmp_path, "providers.yaml", "default_provider: ausente\nproviders: {}\n")
    with pytest.raises(ProviderConfigError) as exc:
        load_catalog(path)
    assert "ausente" in str(exc.value)


def test_invalid_url_scheme_is_rejected(tmp_path):
    """Uma URL com esquema inválido é recusada na carga do catálogo."""
    path = _write(tmp_path, "providers.yaml", "providers:\n  x:\n    type: ollama\n    base_url: ftp://host\n")
    with pytest.raises(ProviderConfigError):
        load_catalog(path)


def test_missing_file_is_reported(tmp_path):
    """Um arquivo de configuração inexistente é reportado como erro de configuração."""
    with pytest.raises(ProviderConfigError):
        load_catalog(tmp_path / "nao-existe.yaml")


def test_catalog_is_built_from_settings(tmp_path, monkeypatch):
    """O catálogo é montado a partir das configurações que apontam para o arquivo de configuração."""
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "http://10.0.0.5:11434")
    path = _write(tmp_path, "providers.yaml", YAML_CONFIG)
    settings = Settings(provider_config_path=path)
    catalog = catalog_for_settings(settings)
    assert "openrouter" in catalog.names()


def test_build_provider_creates_each_type(tmp_path, monkeypatch):
    """O catálogo constrói o provedor pedido, com o nome e o modelo declarados."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("CALLIDUS_OLLAMA_API_KEY", "ol-key")
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "http://10.0.0.5:11434")
    path = _write(tmp_path, "providers.yaml", YAML_CONFIG)
    catalog = load_catalog(path)
    settings = Settings()

    ollama = catalog.build("ollama_remote", settings)
    assert isinstance(ollama, OllamaProvider)
    assert ollama.default_model == "qwen3:8b"

    router = catalog.build("openrouter", settings)
    assert isinstance(router, OpenRouterProvider)
    assert router.name == "openrouter"


def test_build_provider_requires_api_key_env(monkeypatch):
    """Construir um provedor sem a variável de ambiente da chave é erro de configuração."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    catalog = ProviderCatalog.from_mapping(
        {"providers": {"r": {"type": "openrouter", "api_key_env": "OPENROUTER_API_KEY"}}}
    )
    with pytest.raises(ProviderConfigError) as exc:
        catalog.build("r", Settings())
    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_build_provider_for_every_supported_type(monkeypatch):
    """Cada tipo suportado de provedor é construído pela mesma fábrica."""
    monkeypatch.setenv("K", "v")
    settings = Settings()
    cases = {
        "ollama": OllamaProvider,
        "llamacpp": LlamaCppProvider,
        "openai_compatible": OpenAICompatibleProvider,
        "openrouter": OpenRouterProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "mock": MockProvider,
    }
    for kind, expected in cases.items():
        spec = {
            "type": kind,
            "base_url": "http://127.0.0.1:9999/v1",
            "api_key_env": "K",
        }
        provider = build_provider("p", ProviderCatalog.from_mapping({"providers": {"p": spec}}).spec("p"), settings)
        assert isinstance(provider, expected), kind


def test_openai_compatible_requires_base_url():
    """Um provedor compatível com OpenAI sem `base_url` é recusado na construção."""
    catalog = ProviderCatalog.from_mapping({"providers": {"p": {"type": "openai_compatible"}}})
    with pytest.raises(ProviderConfigError) as exc:
        catalog.build("p", Settings())
    assert "base_url" in str(exc.value)


def test_provider_spec_forbids_unknown_keys():
    """A especificação do provedor recusa chaves desconhecidas."""
    with pytest.raises(Exception):
        ProviderCatalog.from_mapping({"providers": {"p": {"type": "ollama", "chave": "x"}}})


def test_shipped_example_configuration_is_valid(monkeypatch):
    """O exemplo versionado precisa carregar: tipo conhecido, URL válida, sem credencial embutida."""
    for name in (
        "CALLIDUS_OLLAMA_URL",
        "CALLIDUS_OLLAMA_API_KEY",
        "CALLIDUS_LLAMA_CPP_URL",
        "CALLIDUS_LLAMA_CPP_KEY",
        "OPENROUTER_API_KEY",
        "GATEWAY_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.setenv(name, "http://exemplo.local:1234" if "URL" in name else "chave-de-teste-123456")

    example = Path(__file__).resolve().parents[1] / "providers.example.yaml"
    catalog = load_catalog(example)

    assert "ollama_local" in catalog.names()
    assert catalog.spec("ollama_local").kind == "ollama"
    assert catalog.spec("openrouter").kind == "openrouter"
    # Nenhuma credencial literal no arquivo de exemplo.
    raw = example.read_text(encoding="utf-8")
    assert "api_key:" not in raw


def test_secret_is_not_written_into_the_spec_dump(tmp_path, monkeypatch):
    """A credencial não aparece na representação da especificação do provedor."""
    monkeypatch.setenv("CALLIDUS_OLLAMA_API_KEY", "sk-super-secreta")
    monkeypatch.setenv("CALLIDUS_OLLAMA_URL", "http://10.0.0.5:11434")
    path = _write(tmp_path, "providers.yaml", YAML_CONFIG)
    catalog = load_catalog(path)
    dump = catalog.spec("ollama_remote").model_dump()
    assert "sk-super-secreta" not in json.dumps(dump)
    assert dump["api_key_env"] == "CALLIDUS_OLLAMA_API_KEY"
