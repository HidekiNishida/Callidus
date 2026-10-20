"""
Arquivo: tests/test_llamacpp_provider.py
Nome: test_llamacpp_provider.py
Propósito: Verificar o adaptador do provedor llama.cpp e sua seleção pelo orquestrador.
Responsabilidade: camada de testes — contrato do provedor local, escolha do provedor pelo runner e decomposição com llama.cpp.
Componentes: listagem de modelos e chat, seleção do provedor e decomposição servida pelo llama.cpp.
Dependências: agent.providers.llamacpp, agent.orchestrator.runner e agent.orchestrator.decomposition.
Observações: nenhuma chamada de rede: o cliente HTTP é substituído por um transporte simulado.
"""

import json

import httpx
import pytest

from agent.config import Settings
from agent.orchestrator.decomposition import resolve_decomposition_plan
from agent.orchestrator.runner import _select_provider
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.mock import MockProvider, decomposition_json


@pytest.mark.asyncio
async def test_llamacpp_lists_and_chats(monkeypatch):
    """O provedor lista os modelos e envia o chat no formato esperado."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Handler que responde à listagem de modelos e ao chat, validando o corpo enviado."""
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-local"}]})
        payload = json.loads(request.content)
        assert payload["model"] == "qwen-local"
        assert payload["messages"][0]["content"] == "oi"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pronto"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
        )

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        """Fabrica um cliente httpx que usa o transporte simulado no lugar da rede."""
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("agent.providers.llamacpp.httpx.AsyncClient", factory)
    provider = LlamaCppProvider("http://127.0.0.1:8080")
    assert await provider.list_models() == ["qwen-local"]
    reply = await provider.chat(
        ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="oi")],
            profile=ModelProfile(model_id="qwen-local"),
        )
    )
    assert reply.content == "pronto"
    assert reply.prompt_tokens_estimate == 3


def test_runner_selects_llamacpp():
    """Com a base do llama.cpp configurada, o runner escolhe esse provedor."""
    settings = Settings(llamacpp_base_url="http://127.0.0.1:8080")
    provider = _select_provider(settings, {"provider": "llamacpp"})
    assert isinstance(provider, LlamaCppProvider)


@pytest.mark.asyncio
async def test_decomposition_uses_llamacpp_provider():
    """A decomposição usa o llama.cpp e devolve um plano com a ferramenta pedida e a resposta final."""
    mock = MockProvider(
        responses=[
            decomposition_json(
                [{"title": "Listar", "objective": "ver a pasta", "metadata": {"tool": "list_dir", "tool_args": {}}}]
            )
        ]
    )
    plan, source = await resolve_decomposition_plan(
        settings=Settings(allow_mock_fallback=False, use_generic_decomposition_template=False),
        run_config={"provider": "llamacpp", "model_id": "qwen-local"},
        objective="organizar o código",
        project_root=".",
        provider=mock,
    )
    assert source == "llamacpp"
    assert plan is not None
    assert plan.subtasks[0].metadata["tool"] == "list_dir"
    assert plan.subtasks[-1].metadata.get("final_answer") is True
