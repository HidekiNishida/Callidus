"""
Arquivo: tests/test_provider_security.py
Nome: test_provider_security.py
Propósito: verificar que credenciais não vazam, que o TLS segue habilitado e que não há fallback silencioso.
Responsabilidade: camada de testes — comportamento de segurança dos provedores e da seleção de provedor.
Componentes: credencial ausente da mensagem de erro, ausência de vazamento quando o servidor ecoa a chave, catálogo sem expor a credencial, verificação de TLS ativa, provedor desconhecido como erro explícito, fallback apenas com a flag e segredo fora da configuração da run.
Dependências: agent.providers (base, openai_compatible, registry, http), agent.orchestrator.runner._select_provider, agent.config.Settings, pytest.
Observações: chaves fictícias usadas apenas nos testes e HTTP simulado pela fixture mock_http.

credenciais, TLS e ausência de fallback silencioso
"""
from __future__ import annotations
import httpx
import pytest

from agent.config import Settings
from agent.orchestrator.runner import _select_provider
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile, ProviderConfigError
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.registry import ProviderCatalog

SECRET = "sk-super-secreta-1234567890"
REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="m"),
)


@pytest.mark.asyncio
async def test_credential_never_appears_in_the_error_message(mock_http):
    """A credencial configurada não aparece na mensagem de erro devolvida ao chamador."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve uma resposta que ecoa a credencial."""
        return httpx.Response(401, text=f"chave {SECRET} recusada")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key=SECRET)
    with pytest.raises(Exception) as exc:
        await provider.chat(REQUEST)
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_credential_is_not_leaked_when_the_server_echoes_it(mock_http):
    """Quando o servidor repete a credencial na resposta, ela não vaza na exceção."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve uma resposta que ecoa a credencial."""
        return httpx.Response(500, text=f"erro interno com {SECRET}")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key=SECRET)
    with pytest.raises(Exception) as exc:
        await provider.chat(REQUEST)
    assert SECRET not in str(exc.value)


def test_provider_catalog_does_not_expose_the_credential(monkeypatch):
    """O provedor construído pelo catálogo não expõe a credencial nos seus atributos."""
    monkeypatch.setenv("MINHA_CHAVE", SECRET)
    catalog = ProviderCatalog.from_mapping(
        {"providers": {"p": {"type": "openrouter", "api_key_env": "MINHA_CHAVE"}}}
    )
    provider = catalog.build("p", Settings())
    assert SECRET not in repr(provider.__dict__)


def test_tls_verification_stays_on_by_default():
    """A verificação de TLS permanece ligada por padrão nas chamadas e nas configurações."""
    from agent.providers.http import HttpClientConfig, client_kwargs

    assert client_kwargs(HttpClientConfig(base_url="http://x/v1"))["verify"] is True
    assert Settings().provider_verify_tls is True


def test_unknown_provider_is_an_explicit_error_and_does_not_fall_back():
    """Um provedor desconhecido vira erro explícito, sem trocar silenciosamente de provedor."""
    settings = Settings(allow_mock_fallback=False)
    with pytest.raises(ProviderConfigError) as exc:
        _select_provider(settings, {"provider": "provedor-que-nao-existe"})
    assert "provedor-que-nao-existe" in str(exc.value)


def test_mock_fallback_requires_the_explicit_flag():
    """O fallback para o provedor mock só acontece quando a flag é habilitada."""
    settings = Settings(allow_mock_fallback=True)
    provider = _select_provider(settings, {"provider": "provedor-que-nao-existe"})
    assert provider.name == "mock"


def test_secret_is_not_written_into_the_run_configuration():
    """O segredo não é gravado nos atributos do provedor usados na configuração da run."""
    settings = Settings(allow_mock_fallback=False)
    provider = _select_provider(settings, {"provider": "ollama"})
    assert "api_key" not in repr(vars(provider))
