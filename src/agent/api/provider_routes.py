"""
Arquivo: src/agent/api/provider_routes.py
Nome: provider_routes.py
Propósito: configuração de provedores pela interface.
Responsabilidade: camada de apresentação/transport.
Componentes: ProviderEntry, ProviderConfigIn, SecretIn, read_provider_config, write_provider_config, delete_provider….
Dependências: agent.api.deps, agent.config, agent.providers.base, agent.providers.registry, agent.providers.secrets, __future__….
Observações: a rota valida, delega e serializa — a regra de negócio vive no serviço.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.api.deps import read_settings
from agent.config import Settings
from agent.providers.base import ProviderConfigError
from agent.providers.registry import (
    ProviderCatalog,
    build_provider_by_name,
    catalog_for_settings,
    config_path_for_settings,
    save_catalog,
)
from agent.providers.secrets import delete_secret, secret_state, write_secret

router = APIRouter()


class ProviderEntry(BaseModel):
    """Descrição de um provedor editável pela interface."""

    type: str
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    api_key_file: str | None = None
    timeout: float | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)
    allow_private_hosts: bool | None = None
    verify_tls: bool | None = None
    max_retries: int | None = None
    models_cache_ttl: float | None = None
    referer: str | None = None
    title: str | None = None
    stream: bool | None = None


class ProviderConfigIn(BaseModel):
    """Configuração de provedores enviada pela interface.

    Atributos:
        default_provider: nome do provedor padrão, quando houver.
        providers: provedores editáveis, indexados pelo nome.
    """
    default_provider: str | None = None
    providers: dict[str, ProviderEntry] = Field(default_factory=dict)


class SecretIn(BaseModel):
    """Credencial de um provedor enviada pela interface.

    Atributos:
        secret: valor da credencial; nunca é devolvido na resposta.
    """
    secret: str


def _catalog(settings: Settings) -> ProviderCatalog:
    """Carrega o catálogo de provedores das configurações.

    Args:
            settings: configurações do processo.

    Returns:
            O catálogo de provedores configurado.

    Raises:
            HTTPException: com status 400 quando a configuração dos provedores é inválida.
    """
    try:
        return catalog_for_settings(settings)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _config_payload(settings: Settings) -> dict[str, Any]:
    """Monta o payload da configuração de provedores, sem credenciais.

    Args:
            settings: configurações do processo.

    Returns:
            O caminho da configuração, o provedor padrão e a descrição de cada provedor com o estado da sua credencial.

    Observações:
        A chave da API nunca é incluída; apenas o estado do segredo é informado.
    """
    catalog = _catalog(settings)
    path = config_path_for_settings(settings)
    providers: dict[str, Any] = {}
    for name in catalog.names():
        spec = catalog.spec(name)
        entry = spec.model_dump(exclude_none=True)
        entry.pop("api_key", None)
        entry["secret"] = secret_state(settings, name)
        providers[name] = entry
    return {
        "path": str(path),
        "exists": path.is_file(),
        "default_provider": catalog.default_provider,
        "providers": providers,
    }


@router.get("/providers/config")
async def read_provider_config(settings: Settings = Depends(read_settings)) -> dict:
    """Configuração de provedores em uso (sem credenciais) e onde ela vive."""
    return _config_payload(settings)


@router.put("/providers/config")
async def write_provider_config(payload: ProviderConfigIn, settings: Settings = Depends(read_settings)) -> dict:
    """Grava a configuração de provedores. Valida tipos, URLs e nomes antes de escrever."""
    entries: dict[str, Any] = {}
    for name, entry in payload.providers.items():
        data = entry.model_dump(exclude_none=True)
        entries[name] = data
    try:
        catalog = ProviderCatalog.from_mapping(
            {"default_provider": payload.default_provider, "providers": entries}
        )
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = config_path_for_settings(settings)
    try:
        save_catalog(catalog, path)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"não foi possível gravar {path}: {exc}") from exc
    return _config_payload(settings)


@router.delete("/providers/config/{name}")
async def delete_provider(name: str, settings: Settings = Depends(read_settings)) -> dict:
    """Remove um provedor da configuração (a credencial gravada vai junto)."""
    catalog = _catalog(settings)
    if catalog.get(name) is None:
        raise HTTPException(status_code=404, detail=f"provedor '{name}' não está na configuração")
    remaining = {
        other: catalog.spec(other).model_dump(exclude_none=True)
        for other in catalog.names()
        if other != name
    }
    default = catalog.default_provider
    if default == name:
        default = None
    try:
        new_catalog = ProviderCatalog.from_mapping(
            {"default_provider": default, "providers": remaining}
        )
        save_catalog(new_catalog, config_path_for_settings(settings))
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    delete_secret(settings, name)
    return _config_payload(settings)


@router.put("/providers/config/{name}/secret")
async def set_provider_secret(name: str, payload: SecretIn, settings: Settings = Depends(read_settings)) -> dict:
    """Grava a credencial do provedor em arquivo com permissão restrita e aponta a configuração
    para ele. O valor nunca volta na resposta."""
    catalog = _catalog(settings)
    if catalog.get(name) is None:
        raise HTTPException(status_code=404, detail=f"provedor '{name}' não está na configuração")
    try:
        path = write_secret(settings, name, payload.secret)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    spec = catalog.spec(name)
    updated = spec.model_copy(update={"api_key_file": str(path), "api_key_env": None})
    try:
        entries = {
            other: catalog.spec(other).model_dump(exclude_none=True)
            for other in catalog.names()
            if other != name
        }
        entries[name] = updated.model_dump(exclude_none=True)
        new_catalog = ProviderCatalog.from_mapping(
            {"default_provider": catalog.default_provider, "providers": entries}
        )
        save_catalog(new_catalog, config_path_for_settings(settings))
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**_config_payload(settings), "secret_path": str(path)}


@router.delete("/providers/config/{name}/secret")
async def clear_provider_secret(name: str, settings: Settings = Depends(read_settings)) -> dict:
    """Apaga a credencial gravada e limpa a referência no arquivo de configuração."""
    catalog = _catalog(settings)
    if catalog.get(name) is None:
        raise HTTPException(status_code=404, detail=f"provedor '{name}' não está na configuração")
    delete_secret(settings, name)
    spec = catalog.spec(name)
    if spec.api_key_file:
        updated = spec.model_copy(update={"api_key_file": None})
        try:
            entries = {
                other: catalog.spec(other).model_dump(exclude_none=True)
                for other in catalog.names()
                if other != name
            }
            entries[name] = updated.model_dump(exclude_none=True)
            save_catalog(
                ProviderCatalog.from_mapping(
                    {"default_provider": catalog.default_provider, "providers": entries}
                ),
                config_path_for_settings(settings),
            )
        except ProviderConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _config_payload(settings)


@router.post("/providers/{name}/test")
async def test_provider(name: str, settings: Settings = Depends(read_settings)) -> dict:
    """Testa a conexão com o provedor: lista os modelos, sem gastar inferência.

    Falha de conexão vira `ok: false` com o motivo — não um 500 com traceback.
    """
    try:
        provider = build_provider_by_name(name, settings)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provedor '{name}' não encontrado")
    health = await provider.health_check()
    return health.model_dump()
