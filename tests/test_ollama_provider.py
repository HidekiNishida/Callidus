"""
Arquivo: tests/test_ollama_provider.py
Nome: test_ollama_provider.py
Propósito: verificar o adaptador do Ollama local e remoto contra a API nativa, incluindo streaming e diagnóstico.
Responsabilidade: camada de testes — comportamento observável do provedor Ollama (requisição, resposta, erros e saúde).
Componentes: API nativa de chat, envio da chave, listagem de modelos, ferramentas, streaming, timeout, autenticação, health check e URL inválida.
Dependências: agent.providers.ollama.OllamaProvider, agent.providers.base, fixture mock_http do conftest, httpx, pytest.
Observações: todo o HTTP é simulado pela fixture mock_http; nenhum servidor Ollama real é contatado.

Ollama local e remoto (API nativa)
"""
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    ModelProfile,
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
)
from agent.providers.ollama import OllamaProvider

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="qwen3:8b", generation={"temperature": 0.5, "think": False}),
)


def _body(request: httpx.Request) -> dict:
    """Decodifica o corpo JSON enviado na requisição."""
    return json.loads(request.content)


@pytest.mark.asyncio
async def test_remote_ollama_uses_native_api(mock_http):
    """A chamada usa a API nativa `/api/chat` com o modelo e a temperatura configurados, e devolve o conteúdo e os tokens estimados."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["path"] = request.url.path
        seen["body"] = _body(request)
        return httpx.Response(200, json={"message": {"content": "pronto"}, "eval_count": 3})

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    response = await provider.chat(REQUEST)

    assert seen["path"] == "/api/chat"
    assert seen["body"]["model"] == "qwen3:8b"
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["temperature"] == 0.5
    assert response.content == "pronto"
    assert response.completion_tokens_estimate == 3


@pytest.mark.asyncio
async def test_api_key_is_sent_when_configured(mock_http):
    """A chave configurada é enviada no cabeçalho de autorização."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"message": {"content": "ok"}})

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434", api_key="ollama-secreta-123")
    await provider.chat(REQUEST)
    assert seen["auth"] == "Bearer ollama-secreta-123"


@pytest.mark.asyncio
async def test_models_are_listed_from_api_tags(mock_http):
    """Os modelos disponíveis vêm da listagem `/api/tags` do servidor."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2"}]})

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    assert await provider.list_models() == ["qwen3:8b", "llama3.2"]


@pytest.mark.asyncio
async def test_tools_are_sent_and_tool_calls_are_returned(mock_http):
    """As ferramentas enviadas ao Ollama chegam de volta como chamadas de ferramenta tipadas."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["body"] = _body(request)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "buscar", "arguments": {"termo": "x"}}}],
                }
            },
        )

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="qwen3:8b"),
        tools=[{"type": "function", "function": {"name": "buscar", "parameters": {"type": "object"}}}],
    )
    response = await provider.chat(request)
    assert seen["body"]["tools"][0]["function"]["name"] == "buscar"
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "buscar"
    assert response.tool_calls[0].arguments == {"termo": "x"}


@pytest.mark.asyncio
async def test_streaming_collects_fragments_and_usage(mock_http):
    """O streaming entrega os fragmentos recebidos e contabiliza o uso reported pelo servidor."""
    body = (
        '{"message":{"content":"Ol"},"done":false}\n'
        '{"message":{"content":"á"},"done":true,"eval_count":2}\n'
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        assert _body(request)["stream"] is True
        return httpx.Response(200, content=body)

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    pieces: list[str] = []
    response = await provider.chat_streaming(REQUEST, pieces.append)
    assert pieces == ["Ol", "á"]
    assert response.content == "Olá"
    assert response.completion_tokens_estimate == 2


@pytest.mark.asyncio
async def test_streaming_without_final_message_fails(mock_http):
    """Um stream que termina sem a mensagem final é recusado com erro explícito."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(200, content=b'{"message":{"content":"parcial"},"done":false}\n')

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    with pytest.raises(ProviderError) as exc:
        await provider.chat_streaming(REQUEST, lambda _p: None)
    assert "sem a mensagem final" in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_is_reported_as_provider_timeout(mock_http):
    """Um tempo esgotado é reportado como timeout de provedor."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        raise httpx.ReadTimeout("demorou")

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    with pytest.raises(ProviderTimeoutError) as exc:
        await provider.chat(REQUEST)
    assert "tempo esgotado" in str(exc.value)


@pytest.mark.asyncio
async def test_authentication_failure_is_reported(mock_http):
    """Uma resposta 401 é reportada como erro de autenticação."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(401, text="unauthorized")

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434", api_key="k")
    with pytest.raises(ProviderAuthError):
        await provider.chat(REQUEST)


@pytest.mark.asyncio
async def test_health_check_reports_the_server(mock_http):
    """O health check informa o servidor como disponível e lista os modelos encontrados."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    mock_http("ollama", handler)
    provider = OllamaProvider("https://vps.exemplo:11434")
    health = await provider.health_check()
    assert health.ok is True
    assert health.models == ["qwen3:8b"]


def test_invalid_base_url_is_rejected():
    """Uma URL de base com esquema não suportado é recusada na construção do provedor."""
    from agent.providers.base import ProviderConfigError

    with pytest.raises(ProviderConfigError):
        OllamaProvider("ftp://host")
