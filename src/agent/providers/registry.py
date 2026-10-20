"""
Arquivo: src/agent/providers/registry.py
Nome: registry.py
Propósito: carregar a configuração declarativa de provedores e fabricar as instâncias correspondentes.
Responsabilidade: camada de aplicação — catálogo de provedores, interpolação de ambiente e construção.
Componentes: ProviderSpec, ProviderCatalog, load_catalog, catalog_for_settings, build_provider, build_provider_by_name, build_builtin_provider, resolve_api_key, interpolate_text, parse_document.
Dependências: agent.config, agent.providers.base e as implementações concretas de provedor.
Observações: nenhuma credencial é impressa ou logada; o catálogo é cacheado por arquivo e mtime.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.config import Settings
from agent.providers.base import ProviderConfigError
from agent.providers.llamacpp import LlamaCppProvider, read_api_key_file
from agent.providers.mock import MockProvider
from agent.providers.ollama import OllamaProvider
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.openrouter import OpenRouterProvider
from agent.providers.anthropic import AnthropicProvider
from agent.providers.gemini import GeminiProvider
from agent.providers.http import validate_base_url

# Tipos aceitos na configuração. `openai` é um caso de `openai_compatible` com URL padrão.
PROVIDER_TYPES = {
    "ollama",
    "llamacpp",
    "llama_cpp",
    "llama.cpp",
    "openai_compatible",
    "openai-compatible",
    "openai",
    "openrouter",
    "anthropic",
    "claude",
    "gemini",
    "google",
    "mock",
}

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ProviderSpec(BaseModel):
    """Descrição de um provedor no arquivo de configuração.

    Atributos:
        type: tipo do provedor (ollama, llamacpp, openai_compatible, openrouter, anthropic, gemini, mock).
        base_url: URL base do serviço.
        model: modelo padrão do provedor.
        api_key_env: nome da variável de ambiente com a credencial.
        api_key: credencial literal na configuração.
        api_key_file: arquivo com a credencial.
        timeout: tempo limite das requisições, em segundos.
        headers: cabeçalhos adicionais enviados em cada requisição.
        generation: parâmetros de geração do modelo.
        stream: indica se o provedor transmite a resposta em fragmentos.
        referer / title: cabeçalhos de identificação do OpenRouter.
        allow_private_hosts: permite endereços privados.
        verify_tls: valida o certificado TLS do servidor.
        max_retries: número de retentativas em falha transitória.
        models_cache_ttl: tempo de vida do cache de modelos, em segundos.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    api_key_file: str | None = None
    timeout: float | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)
    stream: bool | None = None
    referer: str | None = None
    title: str | None = None
    allow_private_hosts: bool | None = None
    verify_tls: bool | None = None
    max_retries: int | None = None
    models_cache_ttl: float | None = None

    @property
    def kind(self) -> str:
        """Tipo do provedor normalizado em minúsculas.

        Returns:
            O tipo declarado na configuração, em minúsculas.
        """
        return (self.type or "").strip().lower()


def interpolate_text(text: str) -> str:
    """Substitui `${VAR}` e `${VAR:-padrão}` pelo valor do ambiente.

    Variável ausente sem padrão é erro de configuração (o nome aparece; o valor, nunca).

    Args:
        text: texto com as referências a variáveis.

    Returns:
        O texto com as variáveis substituídas.

    Raises:
        ProviderConfigError: quando uma variável sem padrão não está definida.
    """
    if not isinstance(text, str) or "${" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        """Substitui a configuração de um provedor, preservando a credencial."""
        name = match.group(1)
        default = match.group(2)
        value = os.environ.get(name)
        if not value:
            if default is None:
                raise ProviderConfigError(f"variável de ambiente '{name}' não está definida")
            return default
        return value

    return _ENV_PATTERN.sub(replace, text)


def _interpolate(value: Any) -> Any:
    """Aplica a interpolação de ambiente em toda a estrutura da configuração.

    Args:
        value: trecho da configuração (texto, mapa ou lista).

    Returns:
        A estrutura com as referências a variáveis substituídas.
    """
    if isinstance(value, str):
        return interpolate_text(value)
    if isinstance(value, dict):
        return {interpolate_text(str(key)): _interpolate(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item) for item in value]
    return value


def parse_document(text: str, path: Path) -> dict[str, Any]:
    """Lê YAML ou JSON conforme a extensão do arquivo.

    Args:
        text: conteúdo do arquivo de configuração.
        path: caminho do arquivo, usado na mensagem de erro e para decidir o formato.

    Returns:
        O mapa de configuração lido.

    Raises:
        ProviderConfigError: quando o arquivo é inválido ou não contém um mapa.
    """
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependência declarada no pyproject
            raise ProviderConfigError(
                "leitura de YAML exige PyYAML; instale a dependência ou use um arquivo JSON"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except Exception as exc:
            raise ProviderConfigError(f"configuração de provedores inválida em {path}: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderConfigError(f"configuração de provedores inválida em {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProviderConfigError(f"configuração de provedores inválida em {path}: esperado um mapa")
    return data


class ProviderCatalog:
    """Provedores nomeados, carregados de um arquivo de configuração.

    Atributos:
        _providers: especificações dos provedores, indexadas pelo nome.
        _default: nome do provedor padrão, quando declarado.
    """

    def __init__(self, providers: dict[str, ProviderSpec], default_provider: str | None = None) -> None:
        """Cria o catálogo a partir de especificações já validadas.

        Args:
            providers: especificações indexadas pelo nome do provedor.
            default_provider: nome do provedor padrão.
        """
        self._providers = dict(providers)
        self._default = default_provider

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ProviderCatalog:
        """Constrói o catálogo a partir do mapa lido do arquivo de configuração.

        Args:
            data: mapa de configuração já interpolado ou a interpolar.

        Returns:
            O catálogo validado.

        Raises:
            ProviderConfigError: quando a estrutura, um provedor ou o padrão informado é inválido.
        """
        raw = _interpolate(data or {})
        if not isinstance(raw, dict):
            raise ProviderConfigError("configuração de provedores inválida: esperado um mapa")
        entries = raw.get("providers") or {}
        if not isinstance(entries, dict):
            raise ProviderConfigError("configuração de provedores inválida: 'providers' deve ser um mapa")
        providers: dict[str, ProviderSpec] = {}
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                raise ProviderConfigError(f"provedor '{name}' inválido: esperado um mapa de opções")
            try:
                spec = ProviderSpec.model_validate(entry)
            except ValidationError as exc:
                raise ProviderConfigError(f"provedor '{name}' inválido: {exc}") from exc
            if spec.kind not in PROVIDER_TYPES:
                raise ProviderConfigError(
                    f"provedor '{name}' inválido: tipo '{spec.type}' desconhecido "
                    f"(aceitos: {', '.join(sorted(PROVIDER_TYPES))})"
                )
            if spec.base_url:
                validate_base_url(spec.base_url)
            providers[name] = spec
        default = raw.get("default_provider")
        if default is not None:
            default = str(default)
            if default not in providers:
                raise ProviderConfigError(
                    f"provedor padrão '{default}' não está definido em 'providers'"
                )
        return cls(providers, default)

    @property
    def default_provider(self) -> str | None:
        """Nome do provedor padrão declarado na configuração.

        Returns:
            O nome do provedor padrão, ou `None` quando não há padrão.
        """
        return self._default

    def names(self) -> list[str]:
        """Nomes dos provedores do catálogo.

        Returns:
            A lista de nomes, na ordem de declaração.
        """
        return list(self._providers)

    def get(self, name: str) -> ProviderSpec | None:
        """Especificação de um provedor, quando existe.

        Args:
            name: nome do provedor.

        Returns:
            A `ProviderSpec`, ou `None` quando o nome não está no catálogo.
        """
        return self._providers.get(name)

    def spec(self, name: str) -> ProviderSpec:
        """Especificação de um provedor, com erro explícito quando o nome não existe.

        Args:
            name: nome do provedor.

        Returns:
            A `ProviderSpec` correspondente.

        Raises:
            ProviderConfigError: quando o provedor não está no catálogo.
        """
        spec = self._providers.get(name)
        if spec is None:
            raise ProviderConfigError(
                f"provedor '{name}' não está na configuração (disponíveis: {', '.join(self.names()) or 'nenhum'})"
            )
        return spec

    def build(self, name: str, settings: Settings) -> Any:
        """Instancia o provedor nomeado.

        Args:
            name: nome do provedor.
            settings: configurações que completam o que a especificação não define.

        Returns:
            A instância do provedor.

        Raises:
            ProviderConfigError: quando o provedor não existe ou a configuração é inválida.
        """
        return build_provider(name, self.spec(name), settings)


def load_catalog(path: Path | str) -> ProviderCatalog:
    """Carrega o catálogo de provedores de um arquivo.

    Args:
        path: caminho do arquivo de configuração.

    Returns:
        O catálogo validado.

    Raises:
        ProviderConfigError: quando o arquivo não existe ou é inválido.
    """
    file = Path(path)
    if not file.is_file():
        raise ProviderConfigError(f"arquivo de configuração de provedores não encontrado: {file}")
    data = parse_document(file.read_text(encoding="utf-8"), file)
    return ProviderCatalog.from_mapping(data)


_CATALOG_CACHE: dict[tuple[str, float], ProviderCatalog] = {}


def config_path_for_settings(settings: Settings) -> Path:
    """Arquivo de provedores em uso: o configurado (`PROVIDERS_CONFIG_PATH`) ou o padrão da
    pasta de dados (`data/providers.yaml`), que a interface web cria quando necessário.

    Args:
        settings: configurações consultadas.

    Returns:
        O caminho do arquivo de configuração de provedores.
    """
    return settings.resolved_provider_config_path()


def catalog_for_settings(settings: Settings) -> ProviderCatalog:
    """Catálogo da configuração apontada nas settings (cacheado por arquivo e mtime).

    Args:
        settings: configurações consultadas.

    Returns:
        O catálogo carregado; vazio quando o arquivo padrão ainda não existe.

    Raises:
        ProviderConfigError: quando o arquivo configurado explicitamente está ausente ou ilegível.
    """
    file = config_path_for_settings(settings)
    explicit = settings.provider_config_path is not None
    if not file.is_file():
        if explicit:
            raise ProviderConfigError(f"arquivo de configuração de provedores não encontrado: {file}")
        return ProviderCatalog({})
    try:
        mtime = file.stat().st_mtime
    except OSError as exc:
        raise ProviderConfigError(f"arquivo de configuração de provedores ilegível: {file} ({exc})") from exc
    key = (str(file.resolve()), mtime)
    cached = _CATALOG_CACHE.get(key)
    if cached is None:
        cached = load_catalog(file)
        _CATALOG_CACHE.clear()
        _CATALOG_CACHE[key] = cached
    return cached


def resolve_api_key(spec: ProviderSpec, name: str) -> str | None:
    """Chave do ambiente, arquivo de chave ou valor literal da configuração.

    Args:
        spec: especificação do provedor.
        name: nome do provedor, usado na mensagem de erro.

    Returns:
        A credencial resolvida, ou `None` quando o provedor não usa credencial.

    Raises:
        ProviderConfigError: quando a variável de ambiente indicada não está definida.
    """
    if spec.api_key_env:
        value = os.environ.get(spec.api_key_env)
        if not value:
            raise ProviderConfigError(
                f"provedor '{name}': variável de ambiente '{spec.api_key_env}' não está definida"
            )
        return value
    if spec.api_key_file:
        return read_api_key_file(spec.api_key_file)
    return spec.api_key


def build_provider(name: str, spec: ProviderSpec, settings: Settings) -> Any:
    """Instancia o provedor descrito pela especificação. Nenhuma credencial é impressa ou logada.

    Args:
        name: nome do provedor.
        spec: especificação lida da configuração.
        settings: configurações que completam o que a especificação não define.

    Returns:
        A instância do provedor.

    Raises:
        ProviderConfigError: quando o tipo é desconhecido ou falta a URL base obrigatória.
    """
    kind = spec.kind
    timeout = spec.timeout if spec.timeout is not None else settings.provider_timeout_sec
    retries = spec.max_retries if spec.max_retries is not None else settings.provider_max_retries
    allow_private = (
        spec.allow_private_hosts
        if spec.allow_private_hosts is not None
        else settings.provider_allow_private_hosts
    )
    verify_tls = spec.verify_tls if spec.verify_tls is not None else settings.provider_verify_tls
    api_key = resolve_api_key(spec, name)
    cache_ttl = spec.models_cache_ttl

    if kind == "mock":
        return MockProvider()
    if kind == "ollama":
        return OllamaProvider(
            spec.base_url or settings.ollama_base_url,
            timeout=timeout,
            api_key=api_key,
            headers=spec.headers,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            default_model=spec.model,
        )
    if kind in {"llamacpp", "llama_cpp", "llama.cpp"}:
        return LlamaCppProvider(
            spec.base_url or settings.llamacpp_base_url,
            timeout=timeout,
            api_key=api_key,
            api_key_file=spec.api_key_file,
            headers=spec.headers,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            default_model=spec.model,
        )
    if kind in {"openai_compatible", "openai-compatible"}:
        if not spec.base_url:
            raise ProviderConfigError(f"provedor '{name}': 'base_url' é obrigatório para openai_compatible")
        return OpenAICompatibleProvider(
            spec.base_url,
            model=spec.model,
            api_key=api_key,
            headers=spec.headers,
            timeout=timeout,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            name=name,
            models_cache_ttl=cache_ttl if cache_ttl is not None else 0.0,
        )
    if kind == "openai":
        return OpenAICompatibleProvider(
            spec.base_url or "https://api.openai.com/v1",
            model=spec.model,
            api_key=api_key,
            headers=spec.headers,
            timeout=timeout,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            name=name,
            models_cache_ttl=cache_ttl if cache_ttl is not None else 0.0,
        )
    if kind == "openrouter":
        return OpenRouterProvider(
            spec.base_url,
            model=spec.model,
            api_key=api_key,
            headers=spec.headers,
            timeout=timeout,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            referer=spec.referer,
            title=spec.title or "Callidus",
            models_cache_ttl=cache_ttl if cache_ttl is not None else 300.0,
        )
    if kind in {"anthropic", "claude"}:
        return AnthropicProvider(
            spec.base_url,
            model=spec.model,
            api_key=api_key,
            headers=spec.headers,
            timeout=timeout,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            models_cache_ttl=cache_ttl if cache_ttl is not None else 0.0,
        )
    if kind in {"gemini", "google"}:
        return GeminiProvider(
            spec.base_url,
            model=spec.model,
            api_key=api_key,
            headers=spec.headers,
            timeout=timeout,
            max_retries=retries,
            allow_private_hosts=allow_private,
            verify_tls=verify_tls,
            models_cache_ttl=cache_ttl if cache_ttl is not None else 300.0,
        )
    raise ProviderConfigError(f"provedor '{name}': tipo '{spec.type}' desconhecido")


def catalog_to_mapping(catalog: ProviderCatalog) -> dict[str, Any]:
    """Catálogo como mapa (o que vai para o arquivo de configuração).

    Args:
        catalog: catálogo a serializar.

    Returns:
        O mapa com o provedor padrão e as especificações de cada provedor.
    """
    return {
        "default_provider": catalog.default_provider,
        "providers": {
            name: catalog.spec(name).model_dump(exclude_none=True) for name in catalog.names()
        },
    }


def save_catalog(catalog: ProviderCatalog, path: Path) -> Path:
    """Grava o catálogo no arquivo (YAML ou JSON conforme a extensão) e invalida o cache.

    Args:
        catalog: catálogo a gravar.
        path: caminho do arquivo de destino.

    Returns:
        O caminho do arquivo gravado.

    Raises:
        ProviderConfigError: quando a escrita em YAML exige PyYAML ausente.
    """
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    data = catalog_to_mapping(catalog)
    if file.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependência declarada no pyproject
            raise ProviderConfigError(
                "gravação em YAML exige PyYAML; instale a dependência ou use um arquivo JSON"
            ) from exc
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    file.write_text(text, encoding="utf-8")
    _CATALOG_CACHE.clear()
    return file


BUILTIN_TYPES = {"ollama", "llamacpp", "llama_cpp", "llama.cpp"}

def build_builtin_provider(name: str, settings: Settings) -> Any:
    """Provedores históricos, configurados por variável de ambiente (sem arquivo de configuração).

    Args:
        name: nome do provedor embutido.
        settings: configurações que fornecem URL e limites.

    Returns:
        A instância do provedor, ou `None` quando o nome não corresponde a um provedor embutido.
    """
    kind = (name or "").strip().lower()
    if kind == "ollama":
        return OllamaProvider(
            settings.ollama_base_url,
            timeout=settings.ollama_timeout_sec,
            max_retries=settings.provider_max_retries,
            allow_private_hosts=settings.provider_allow_private_hosts,
            verify_tls=settings.provider_verify_tls,
        )
    if kind in {"llamacpp", "llama_cpp", "llama.cpp"}:
        return LlamaCppProvider(
            settings.llamacpp_base_url,
            timeout=settings.llamacpp_timeout_sec,
            max_retries=settings.provider_max_retries,
            allow_private_hosts=settings.provider_allow_private_hosts,
            verify_tls=settings.provider_verify_tls,
        )
    return None


def build_provider_by_name(name: str, settings: Settings) -> Any:
    """Resolve um nome de provedor: primeiro o catálogo configurado, depois os provedores
    embutidos (Ollama, llama.cpp) e o mock. `None` quando o nome não existe.

    Args:
        name: nome do provedor pedido.
        settings: configurações consultadas.

    Returns:
        A instância do provedor, ou `None` quando o nome não existe.

    Raises:
        ProviderConfigError: quando a configuração do catálogo é inválida.
    """
    if not name:
        return None
    if name == "mock":
        return MockProvider()
    catalog = catalog_for_settings(settings)
    spec = catalog.get(name)
    if spec is not None:
        return build_provider(name, spec, settings)
    return build_builtin_provider(name, settings)
