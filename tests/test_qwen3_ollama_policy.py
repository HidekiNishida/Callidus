"""
Arquivo: tests/test_qwen3_ollama_policy.py
Nome: test_qwen3_ollama_policy.py
Propósito: verificar a política por família de modelo do adaptador Ollama (qwen3:8b e companhia).
Responsabilidade: camada de testes — janela e saída explícitas, amostragem por finalidade, raciocínio vazado, chamada de ferramenta escrita como texto e metadados da inferência.
Componentes: apply_request_policy, family_for, split_reasoning, tool_calls_from_text, context_saturated, OllamaProvider (chat e streaming), observed_chat.
Dependências: agent.providers.ollama_policy, agent.providers.ollama, agent.providers.observed, fixture mock_http do conftest, httpx, pytest.
Observações: nenhum servidor real; o HTTP é simulado pela fixture mock_http.
"""
from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile, estimate_text_tokens
from agent.providers.ollama import OllamaProvider, chat_body
from agent.providers.ollama_policy import (
    apply_request_policy,
    context_saturated,
    family_for,
    split_reasoning,
    tool_calls_from_text,
)

TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]


def _request(model: str = "qwen3:8b", *, text: str = "oi", purpose: str | None = None, **profile) -> ChatCompletionRequest:
    """Requisição mínima com o perfil pedido."""
    return ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=text)],
        profile=ModelProfile(model_id=model, **profile),
        purpose=purpose,
    )


def test_qwen3_gets_explicit_window_and_output_budget():
    """Sem configuração: `num_ctx` = janela do perfil; saída curta para resposta, o resto da janela para código."""
    answer = chat_body(_request(purpose="final_answer", context_limit=8192, output_reserve=1024))
    assert answer["options"]["num_ctx"] == 8192
    assert answer["options"]["num_predict"] == 2048
    assert answer["think"] is False
    code = chat_body(_request(text="x" * 3000, purpose="operation", context_limit=8192, output_reserve=1024))
    # 8192 − 1000 tokens de prompt − 256 de margem: a resposta nunca passa da janela.
    assert code["options"]["num_predict"] == 8192 - 1000 - 256


def test_output_never_exceeds_the_window():
    """Prompt quase do tamanho da janela: a saída fica no que sobra, mas nunca abaixo da reserva."""
    body = chat_body(_request(text="x" * 3 * 7000, purpose="final_answer", context_limit=8192, output_reserve=512))
    options = body["options"]
    assert options["num_predict"] + 7000 <= options["num_ctx"]
    assert options["num_predict"] >= 512


def test_configuration_always_wins_over_the_policy():
    """O que vem de `generation` não é trocado: janela, saída e temperatura configuradas valem."""
    request = _request(
        purpose="plan",
        generation={"num_ctx": 16384, "num_predict": 300, "temperature": 0.9},
    )
    options = chat_body(request)["options"]
    assert options["num_ctx"] == 16384
    assert options["num_predict"] == 300
    assert options["temperature"] == 0.9
    # O que a configuração não disse continua vindo da família.
    assert options["top_k"] == 20


def test_window_grows_in_stable_steps_when_the_prompt_does_not_fit():
    """Prompt maior que a janela do perfil: a janela sobe para o próximo degrau de 4096, até o teto."""
    text = "x" * (3 * 10_000)  # ~10 000 tokens estimados
    body = {"model": "qwen3:8b", "messages": [], "options": {}}
    meta = apply_request_policy(body, _request(text=text, context_limit=8192, output_reserve=1024))
    assert meta["window_grown"] is True
    assert body["options"]["num_ctx"] == 12288
    assert body["options"]["num_ctx"] % 4096 == 0

    huge = "x" * (3 * 60_000)
    body = {"model": "qwen3:8b", "messages": [], "options": {}}
    apply_request_policy(body, _request(text=huge, context_limit=8192))
    assert body["options"]["num_ctx"] == 32768


def test_same_size_requests_keep_the_same_window():
    """Chamadas que cabem no perfil pedem sempre a mesma janela: o Ollama não recarrega o modelo."""
    windows = {
        chat_body(_request(text="a" * size, context_limit=8192))["options"]["num_ctx"]
        for size in (10, 3_000, 12_000, 18_000)
    }
    assert windows == {8192}


def test_always_reasoning_models_keep_their_previous_behaviour():
    """gpt-oss (modelo de referência da avaliação) não recebe janela, saída nem amostragem novas."""
    body = chat_body(_request("gpt-oss:20b", purpose="plan"))
    assert "options" not in body
    assert family_for("gpt-oss:20b").manage_window is False
    assert family_for("deepseek-r1:8b").manage_window is False


def test_sampling_depends_on_the_purpose():
    """Plano/JSON com temperatura baixa, código no meio, resposta ao usuário com a recomendação do modo direto."""
    plan = chat_body(_request(purpose="plan"))["options"]
    code = chat_body(_request(purpose="operation"))["options"]
    prose = chat_body(_request(purpose="final_answer"))["options"]
    assert plan["temperature"] < code["temperature"] < prose["temperature"]
    assert prose["temperature"] == 0.7 and prose["top_p"] == 0.8 and prose["top_k"] == 20
    structured = _request(purpose="final_answer").model_copy(update={"response_format": {"schema": {}}})
    assert chat_body(structured)["options"]["temperature"] == plan["temperature"]


def test_unknown_purpose_and_generic_models_keep_server_sampling():
    """Sem finalidade conhecida ou fora do qwen3, a amostragem fica com o Modelfile do servidor."""
    assert "temperature" not in chat_body(_request(purpose=None))["options"]
    generic = chat_body(_request("llama3.2", purpose="plan"))["options"]
    assert "temperature" not in generic
    assert generic["num_ctx"] == 8192


def test_thinking_mode_uses_thinking_sampling_and_more_output():
    """Raciocínio ligado: amostragem do modo de raciocínio e espaço extra de saída para o pensamento."""
    request = _request(purpose="plan", output_reserve=1024, generation={"think": True})
    body = chat_body(request)
    assert body["think"] is True
    assert body["options"]["temperature"] == 0.6 and body["options"]["top_p"] == 0.95
    assert body["options"]["num_predict"] == 2048 + 4096


def test_split_reasoning_handles_closed_open_and_absent_blocks():
    """`<think>` fechado sai do texto; aberto (corte no meio) esvazia a resposta; sem bloco, nada muda."""
    assert split_reasoning('<think>\nvou ler\n</think>\n\n{"a": 1}') == ('{"a": 1}', "vou ler")
    assert split_reasoning("<think>\n\n</think>\n\nOlá") == ("Olá", "")
    assert split_reasoning("<think>pensando sem fim") == ("", "pensando sem fim")
    assert split_reasoning("resposta limpa") == ("resposta limpa", "")


def test_tool_calls_written_as_text_are_recovered_only_for_offered_tools():
    """O bloco `<tool_call>` vira chamada; ferramenta não oferecida e JSON inválido ficam no texto."""
    text = 'Vou ler.\n<tool_call>\n{"name": "read_file", "arguments": {"path": "app.py"}}\n</tool_call>'
    calls, rest = tool_calls_from_text(text, {"read_file"})
    assert [(c.name, c.arguments) for c in calls] == [("read_file", {"path": "app.py"})]
    assert rest == "Vou ler."
    assert tool_calls_from_text(text, {"write_file"}) == ([], text)
    broken = "<tool_call>{name: read_file}</tool_call>"
    assert tool_calls_from_text(broken, {"read_file"}) == ([], broken)


def test_context_saturation_signal():
    """Entrada + saída chegando à janela é sinal de corte pelo servidor; abaixo disso, não."""
    assert context_saturated(4000, 96, 4096) is True
    assert context_saturated(2000, 100, 4096) is False
    assert context_saturated(None, 10, 4096) is False


def test_estimate_is_calibrated_and_rounds_up():
    """3 caracteres por token, arredondado para cima; vazio vale zero."""
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abc") == 1
    assert estimate_text_tokens("abcd") == 2
    assert estimate_text_tokens("x" * 300) == 100


@pytest.mark.asyncio
async def test_provider_strips_leaked_thinking_and_records_adapter_meta(mock_http):
    """Resposta com `<think>` no texto chega limpa, com o raciocínio separado e a correção registrada."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Servidor falso: devolve o raciocínio misturado ao conteúdo, como um Ollama antigo faria."""
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {"content": '<think>analisando</think>\n{"path": "a.py"}'},
                "prompt_eval_count": 8100,
                "eval_count": 60,
                "done_reason": "stop",
            },
        )

    mock_http("ollama", handler)
    provider = OllamaProvider("http://127.0.0.1:11434")
    response = await provider.chat(_request(purpose="operation", context_limit=8192))
    assert response.content == '{"path": "a.py"}'
    assert response.reasoning == "analisando"
    meta = response.raw["callidus"]
    assert meta["normalized"] == ["think_in_content"]
    assert meta["num_ctx"] == 8192
    assert meta["context_saturated"] is True
    assert "_policy" not in seen["body"] and seen["body"]["options"]["num_ctx"] == 8192


@pytest.mark.asyncio
async def test_streaming_recovers_tool_call_written_as_text(mock_http):
    """No streaming, uma chamada de ferramenta que veio como texto vira chamada de verdade."""
    call = '<tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>'
    lines = (
        json.dumps({"message": {"content": call[:20]}, "done": False})
        + "\n"
        + json.dumps({"message": {"content": call[20:]}, "done": True, "eval_count": 9, "done_reason": "stop"})
        + "\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        """Servidor falso em streaming."""
        return httpx.Response(200, content=lines)

    mock_http("ollama", handler)
    provider = OllamaProvider("http://127.0.0.1:11434")
    request = _request(purpose="operation").model_copy(update={"tools": TOOLS})
    response = await provider.chat_streaming(request, lambda _piece: None)
    assert response.content == ""
    assert [(c.name, c.arguments) for c in response.tool_calls] == [("read_file", {"path": "x.py"})]
    assert response.raw["callidus"]["normalized"] == ["tool_call_in_content"]


@pytest.mark.asyncio
async def test_observed_chat_tells_the_provider_the_purpose():
    """A finalidade do `observed_chat` chega ao provedor na requisição (base da amostragem por finalidade)."""
    from agent.providers.observed import observed_chat

    seen = {}

    class _Provider:
        """Provedor falso que só registra a requisição."""

        name = "fake"

        async def chat(self, request):
            """Guarda a finalidade recebida e responde vazio."""
            seen["purpose"] = request.purpose

            class _R:
                """Resposta mínima."""

                content = ""

            return _R()

    await observed_chat(_Provider(), _request(), purpose="plan")
    assert seen["purpose"] == "plan"
