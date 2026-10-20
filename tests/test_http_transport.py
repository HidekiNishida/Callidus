"""
Arquivo: tests/test_http_transport.py
Nome: test_http_transport.py
Propósito: Verificar o transporte HTTP compartilhado pelos provedores.
Responsabilidade: camada de testes — redação de segredos, validação de URL, opções do cliente, classificação de erro e política de repetição.
Componentes: redação de segredo explícito, redação de formatos conhecidos, validação de URL, hosts privados, opções do cliente, classificação de erro, redação no erro e repetição só em falha transitória.
Dependências: agent.providers.http e agent.providers.base.
Observações: nenhuma chamada de rede: o transporte é substituído pelo fixture mock_http.
"""

from __future__ import annotations

import httpx
import pytest

from agent.providers.base import (
    ProviderAuthError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from agent.providers.http import (
    HttpClientConfig,
    client_kwargs,
    get_json,
    map_http_error,
    redact,
    validate_base_url,
)


def test_redact_removes_explicit_secret():
    """O segredo informado é removido do texto redigido."""
    assert "sk-secreta-123456" not in redact("chave sk-secreta-123456", ["sk-secreta-123456"])


def test_redact_removes_known_key_formats():
    """Chaves com formatos conhecidos são removidas sem apagar o restante da linha."""
    text = "Authorization: Bearer sk-abcdefghijklmnop e AIzaQWERTYUIOPASDFGHJK"
    redacted = redact(text)
    assert "sk-abcdefghijklmnop" not in redacted
    assert "AIzaQWERTYUIOPASDFGHJK" not in redacted
    assert "Bearer" in redacted


def test_validate_base_url_accepts_http_and_https():
    """URLs http e https são aceitas e normalizadas."""
    assert validate_base_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert validate_base_url("https://api.example.com/v1") == "https://api.example.com/v1"


@pytest.mark.parametrize("url", ["", "ftp://host", "não é url", "http://", "http://user:pass@host"])
def test_validate_base_url_rejects_invalid_urls(url):
    """URLs inválidas são recusadas com erro de configuração."""
    with pytest.raises(ProviderConfigError):
        validate_base_url(url)


def test_private_hosts_are_allowed_by_default_and_blocked_on_demand():
    # Ollama e llama.cpp locais rodam em 127.0.0.1 — permitido por padrão.
    """Hosts privados são permitidos por padrão e recusados quando a opção é desligada."""
    assert validate_base_url("http://localhost:11434")
    with pytest.raises(ProviderConfigError):
        validate_base_url("http://localhost:11434", allow_private_hosts=False)


def test_client_kwargs_disable_redirects_and_keep_tls():
    """As opções do cliente desativam redirecionamento, mantêm a verificação TLS e enviam a credencial."""
    config = HttpClientConfig(base_url="http://127.0.0.1:11434", timeout=7.5, api_key="k")
    kwargs = client_kwargs(config)
    assert kwargs["timeout"] == 7.5
    assert kwargs["follow_redirects"] is False
    assert kwargs["verify"] is True
    assert kwargs["headers"]["Authorization"] == "Bearer k"


def test_map_http_error_classifies_causes():
    """Timeout, conexão recusada, 401, 429 e 500 viram erros distintos do provedor."""
    timeout = map_http_error(httpx.ReadTimeout("demorou"), label="Ollama")
    assert isinstance(timeout, ProviderTimeoutError)
    assert "tempo esgotado" in str(timeout)

    connection = map_http_error(httpx.ConnectError("recusado"), label="Ollama")
    assert isinstance(connection, ProviderConnectionError)
    assert "indisponível" in str(connection)

    def status(code: int) -> httpx.HTTPStatusError:
        """Monta um erro HTTP com o código informado, para a classificação por status."""
        request = httpx.Request("POST", "http://host/v1/chat/completions")
        response = httpx.Response(code, json={"error": "x"}, request=request)
        return httpx.HTTPStatusError("erro", request=request, response=response)

    assert isinstance(map_http_error(status(401), label="X"), ProviderAuthError)
    assert isinstance(map_http_error(status(429), label="X"), ProviderRateLimitError)
    assert isinstance(map_http_error(status(500), label="X"), ProviderError)


def test_map_http_error_redacts_the_credential():
    """A credencial não aparece na mensagem de erro do provedor."""
    request = httpx.Request("GET", "http://host/models")
    response = httpx.Response(401, text="chave sk-secreta-123456 recusada", request=request)
    error = map_http_error(
        httpx.HTTPStatusError("erro", request=request, response=response),
        label="OpenRouter",
        secrets=["sk-secreta-123456"],
    )
    assert "sk-secreta-123456" not in str(error)
    assert isinstance(error, ProviderAuthError)


@pytest.mark.asyncio
async def test_get_json_retries_transient_connection_failure(mock_http):
    """Uma falha de conexão transitória é repetida e a segunda tentativa tem sucesso."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler que falha na primeira chamada e devolve JSON na segunda."""
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("recusado")
        return httpx.Response(200, json={"ok": True})

    mock_http("openai_compatible", handler)
    config = HttpClientConfig(base_url="http://host/v1", timeout=1.0, max_retries=1, backoff=0.0)
    async with httpx.AsyncClient(**client_kwargs(config)) as client:
        data = await get_json(client, "http://host/v1/models", label="X", max_retries=1, backoff=0.0)
    assert data == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_get_json_does_not_retry_server_errors(mock_http):
    """Erro de servidor não é repetido: a requisição é feita uma única vez."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler que conta as chamadas e devolve erro 500 do servidor."""
        calls["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    mock_http("openai_compatible", handler)
    config = HttpClientConfig(base_url="http://host/v1", timeout=1.0, max_retries=2, backoff=0.0)
    async with httpx.AsyncClient(**client_kwargs(config)) as client:
        with pytest.raises(ProviderError):
            await get_json(client, "http://host/v1/models", label="X", max_retries=2, backoff=0.0)
    assert calls["n"] == 1
