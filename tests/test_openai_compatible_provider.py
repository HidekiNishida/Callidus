"""
Arquivo: tests/test_openai_compatible_provider.py
Nome: test_openai_compatible_provider.py
Propósito: verificar o adaptador reutilizável de API compatível com OpenAI, do corpo da requisição ao tratamento de erros.
Responsabilidade: camada de testes — comportamento observável do adaptador OpenAI-compatible (parâmetros, ferramentas, streaming e falhas).
Componentes: parâmetros de geração e uso, autenticação, cabeçalhos extras, chamadas de ferramenta, saída estruturada, streaming, cache de modelos, erros e health check.
Dependências: agent.providers.openai_compatible.OpenAICompatibleProvider, agent.providers.base, fixture mock_http do conftest, httpx, pytest.
Observações: todo o HTTP é simulado pela fixture mock_http; nenhum gateway real é contatado.

adaptador reutilizável de API compatível com OpenAI
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
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from agent.providers.openai_compatible import OpenAICompatibleProvider

REQUEST = ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="oi")],
    profile=ModelProfile(model_id="meu-modelo", generation={"temperature": 0.4, "think": False, "num_predict": 128}),
)


def _body(request: httpx.Request) -> dict:
    """Decodifica o corpo JSON enviado na requisição."""
    return json.loads(request.content)


@pytest.mark.asyncio
async def test_chat_sends_model_and_parameters_and_parses_usage(mock_http):
    """A requisição envia modelo, mensagens e parâmetros traduzidos, e a resposta devolve conteúdo, tokens e o motivo de término."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["body"] = _body(request)
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pronto"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "model": "meu-modelo",
            },
        )

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", model="meu-modelo")
    response = await provider.chat(REQUEST)

    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["model"] == "meu-modelo"
    assert seen["body"]["messages"] == [{"role": "user", "content": "oi"}]
    assert seen["body"]["temperature"] == 0.4
    # `think` é exclusivo do Ollama e `num_predict` vira `max_tokens`.
    assert "think" not in seen["body"]
    assert seen["body"]["max_tokens"] == 128
    assert seen["auth"] is None
    assert response.content == "pronto"
    assert response.prompt_tokens_estimate == 5
    assert response.completion_tokens_estimate == 2
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_api_key_is_sent_as_bearer(mock_http):
    """A chave configurada é enviada como token Bearer."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key="sk-secreta-123456")
    await provider.chat(REQUEST)
    assert seen["auth"] == "Bearer sk-secreta-123456"


@pytest.mark.asyncio
async def test_extra_headers_are_sent(mock_http):
    """Os cabeçalhos extras configurados acompanham a requisição."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", headers={"X-Trace": "abc"})
    await provider.chat(REQUEST)
    assert seen["headers"]["x-trace"] == "abc"


@pytest.mark.asyncio
async def test_tool_calls_are_returned(mock_http):
    """As chamadas de ferramenta da resposta são convertidas em chamadas tipadas, com os argumentos já decodificados."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["body"] = _body(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "buscar", "arguments": '{"termo": "x"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="m"),
        tools=[{"type": "function", "function": {"name": "buscar", "parameters": {"type": "object"}}}],
    )
    response = await provider.chat(request)

    assert seen["body"]["tools"][0]["function"]["name"] == "buscar"
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "buscar"
    assert response.tool_calls[0].arguments == {"termo": "x"}


@pytest.mark.asyncio
async def test_structured_output_is_translated_to_json_schema(mock_http):
    """O formato de saída estruturada é traduzido para o esquema JSON esperado pela API."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        seen["body"] = _body(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="oi")],
        profile=ModelProfile(model_id="m"),
        response_format={"schema": {"type": "object", "properties": {"a": {"type": "string"}}}},
    )
    await provider.chat(request)
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["response_format"]["json_schema"]["schema"]["properties"]["a"]["type"] == "string"


@pytest.mark.asyncio
async def test_streaming_delivers_fragments_and_final_usage(mock_http):
    """O streaming entrega os fragmentos e registra o uso final informado pelo servidor."""
    body = (
        'data: {"choices":[{"delta":{"content":"Ol"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"á"},"finish_reason":"stop"}]}\n\n'
        'data: {"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        assert _body(request)["stream"] is True
        return httpx.Response(200, content=body)

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    pieces: list[str] = []
    response = await provider.chat_streaming(REQUEST, pieces.append)

    assert pieces == ["Ol", "á"]
    assert response.content == "Olá"
    assert response.prompt_tokens_estimate == 4
    assert response.completion_tokens_estimate == 2


@pytest.mark.asyncio
async def test_streaming_cut_in_the_middle_fails_with_clear_error(mock_http):
    """Um stream interrompido antes do fim falha com mensagem explícita."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"parcial"}}]}\n\n')

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    with pytest.raises(ProviderError) as exc:
        await provider.chat_streaming(REQUEST, lambda _p: None)
    assert "terminou antes do fim" in str(exc.value)


@pytest.mark.asyncio
async def test_models_are_listed_and_cached(mock_http):
    """A listagem de modelos é cacheada e consultada na API uma única vez dentro do prazo."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        calls["n"] += 1
        return httpx.Response(200, json={"data": [{"id": "modelo-a"}, {"id": "modelo-b"}]})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", models_cache_ttl=60)
    assert await provider.list_models() == ["modelo-a", "modelo-b"]
    assert await provider.list_models() == ["modelo-a", "modelo-b"]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_authentication_failure_is_reported(mock_http):
    """Uma resposta 401 é reportada como erro de autenticação."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(401, json={"error": "invalid api key"})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key="k")
    with pytest.raises(ProviderAuthError):
        await provider.chat(REQUEST)


@pytest.mark.asyncio
async def test_rate_limit_is_reported(mock_http):
    """Uma resposta 429 é reportada como limite de requisições."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(429, json={"error": "slow down"})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key="k")
    with pytest.raises(ProviderRateLimitError):
        await provider.chat(REQUEST)


@pytest.mark.asyncio
async def test_timeout_is_reported(mock_http):
    """Um tempo esgotado é reportado como timeout de provedor."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        raise httpx.ReadTimeout("demorou")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1", api_key="k")
    with pytest.raises(ProviderTimeoutError):
        await provider.chat(REQUEST)


@pytest.mark.asyncio
async def test_health_check_reports_failure_instead_of_raising(mock_http):
    """Servidor fora do ar: o diagnóstico vira `ok=False`, nunca exceção (evita 500 na API)."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        raise httpx.ConnectError("recusado")

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    health = await provider.health_check()
    assert health.ok is False
    assert "indisponível" in health.detail
    assert health.latency_ms is not None


@pytest.mark.asyncio
async def test_health_check_lists_models(mock_http):
    """O health check informa o provedor como disponível e lista os modelos atendidos."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler HTTP falso: devolve a resposta programada e registra a requisição."""
        return httpx.Response(200, json={"data": [{"id": "modelo-a"}]})

    mock_http("openai_compatible", handler)
    provider = OpenAICompatibleProvider("http://gateway.local/v1")
    health = await provider.health_check()
    assert health.ok is True
    assert health.models == ["modelo-a"]
    assert health.provider == "openai_compatible"
