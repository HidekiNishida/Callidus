"""
Arquivo: tests/test_narration_stream.py
Nome: test_narration_stream.py
Propósito: verificar a narração do agente em tempo real, do fragmento do provedor ao evento entregue ao navegador.
Responsabilidade: camada de testes — filtro do texto público, eventos `agent.narration.*`, persistência,
reconexão, isolamento entre runs, conteúdo privado e chamadas de ferramenta nos streams dos provedores.
Componentes: filtro (raciocínio, ferramenta, carga JSON), streaming antes do fim (A), resposta longa (C),
ordem narração → ferramenta → narração (D), interrupção (E), reconexão pela foto ao vivo (F), runs
simultâneas (G), conteúdo privado (H), provedor sem streaming e finalidade silenciosa (I).
Dependências: agent.observability, agent.providers (observed, ollama, openai_compatible, anthropic, gemini, mock),
agent.orchestrator.tool_loop, agent.persistence, httpx, pytest.
Observações: transporte HTTP simulado (httpx.MockTransport), banco temporário por teste; nenhum serviço
externo nem relógio real decide o resultado (o intervalo de lote é zerado onde a ordem importa).
"""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.observability import get_bus, observe
from agent.observability.narration import NARRATION_PERSIST_CHARS, NarrationFilter
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel
from agent.providers.anthropic import AnthropicProvider
from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    LLMProvider,
    ModelProfile,
    ProviderCapabilities,
    ToolCall,
)
from agent.providers.gemini import GeminiProvider
from agent.providers.mock import MockProvider
from agent.providers.observed import observed_chat
from agent.providers.ollama import OllamaProvider
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

REQUEST = ChatCompletionRequest(messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m"))


@pytest.fixture(autouse=True)
def _immediate_batches(monkeypatch):
    """Lote sem espera: cada fragmento sai na hora, e a ordem não depende do relógio."""
    monkeypatch.setattr("agent.observability.batching._defaults", lambda: (0, 2_000))


def _run(tmp_path: Path, name: str = "p"):
    """Cria projeto, tarefa raiz e run em um banco temporário."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name=name, root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="o"))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id))
    session.commit()
    return session, project, root, run


def _rows(session, run_id):
    """Eventos gravados de uma run, na ordem da sequência."""
    return list(session.scalars(select(EventLogModel).where(EventLogModel.run_id == run_id).order_by(EventLogModel.seq)))


class _Scripted(LLMProvider):
    """Provedor com streaming real simulado: entrega os fragmentos do roteiro um a um."""

    name = "scripted"
    supports_streaming = True

    def __init__(self, pieces, *, calls=None, gate: asyncio.Event | None = None, hang: bool = False):
        """Guarda os fragmentos, as chamadas de ferramenta e o ponto de espera opcional."""
        self.pieces = list(pieces)
        self.calls = calls
        self.gate = gate
        self.hang = hang
        self.sent_before_gate = 0

    def capabilities(self):
        """Declara streaming e ferramentas."""
        return ProviderCapabilities(streaming=True, tools=True, tool_loop=True)

    async def list_models(self):
        """Sem modelos anunciados."""
        return []

    async def _chat(self, request):
        """Não deve ser usado: o caminho é o streaming."""
        raise AssertionError("o caminho esperado é o streaming")

    async def _chat_streaming(self, request, on_delta):
        """Entrega os fragmentos; pode parar no meio (portão) ou ficar pendurado."""
        half = len(self.pieces) // 2
        for index, piece in enumerate(self.pieces):
            if self.gate is not None and index == half:
                self.sent_before_gate = index
                await self.gate.wait()
            on_delta(piece)
            await asyncio.sleep(0)
        if self.hang:
            await asyncio.sleep(3600)
        return ChatCompletionResponse(content="".join(self.pieces), tool_calls=self.calls)


# ── Filtro do texto público ────────────────────────────────────────────────


def _filtered(pieces):
    """Passa os fragmentos pelo filtro e devolve o texto público e se a resposta virou carga."""
    f = NarrationFilter()
    return "".join(f.feed(p) for p in pieces), f.closed


def test_filter_keeps_fragments_in_order_even_mid_word():
    """Fragmentos com palavras partidas saem na mesma ordem, sem alteração."""
    text, closed = _filtered(["Vou ver", "ificar o ", "arqu", "ivo `app.py`.\n", "Depois ", "testo."])
    assert text == "Vou verificar o arquivo `app.py`.\nDepois testo."
    assert closed is False


def test_filter_drops_reasoning_even_when_the_tag_is_split():
    """`<think>` partido entre fragmentos continua fora da narração."""
    text, _ = _filtered(["<th", "ink>segredo interno</th", "ink>\n\nVou ler o código."])
    assert text == "Vou ler o código."
    assert "segredo" not in text


def test_filter_stops_at_tool_call_and_json_payload():
    """Chamada de ferramenta escrita no texto e JSON da operação nunca viram narração."""
    text, closed = _filtered(["Vou ler.\n<tool_", 'call>{"name":"read_file","arguments":{"path":"a"}}</tool_call>'])
    assert text == "Vou ler.\n" and closed
    text, closed = _filtered(["Corrigindo.\n", '{"path": "a.py", "content": "x"}'])
    assert text == "Corrigindo.\n" and closed
    text, closed = _filtered(['{"path": "a.py"}'])
    assert text == "" and closed
    text, closed = _filtered(["``", "`python\nprint(1)\n```"])
    assert text == "" and closed


def test_filter_stops_at_template_tags_seen_in_real_models():
    """`<function-call>` (escrito pelo qwen3-vl:8b no Ollama real) e tokens `<|...|>` não viram narração."""
    text, closed = _filtered(["<func", "tion-call>\n{\"name\": \"list_dir\"}\n</function-call>"])
    assert text == "" and closed
    text, closed = _filtered(["Vou listar a pasta.\n", "<function-call>\n{}"])
    assert text == "Vou listar a pasta.\n" and closed
    text, closed = _filtered(["<|channel|>commentary"])
    assert text == "" and closed


def test_filter_keeps_a_plain_less_than_sign():
    """Um `<` comum (comparação) não é confundido com tag."""
    text, closed = _filtered(["Se x < 3, ", "o teste falha."])
    assert text == "Se x < 3, o teste falha." and not closed


# ── Teste A: fragmentos aparecem antes do fim da resposta ─────────────────


@pytest.mark.asyncio
async def test_a_narration_deltas_are_delivered_before_the_response_ends(tmp_path):
    """A narração chega ao assinante enquanto o modelo ainda está gerando."""
    session, project, root, run = _run(tmp_path)
    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    gate = asyncio.Event()
    provider = _Scripted(["Vou ", "começar ", "lendo ", "a API ", "dos ", "gráficos."], gate=gate)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id, agent="executor"):
        task = asyncio.create_task(observed_chat(provider, REQUEST, purpose="operation"))
        for _ in range(50):
            await asyncio.sleep(0.001)
            if provider.sent_before_gate:
                break
        await asyncio.sleep(0.01)
        early = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
        assert not task.done(), "a resposta ainda não terminou"
        started = [e for e in early if e["type"] == "agent.narration.started"]
        deltas = [e for e in early if e["type"] == "agent.narration.delta"]
        assert len(started) == 1
        assert "".join(d["data"]["text"] for d in deltas) == "Vou começar lendo "
        assert [d["data"]["offset"] for d in deltas] == [0, 4, 12]
        gate.set()
        await task
        session.commit()
    await asyncio.sleep(0.01)
    late = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    bus.unsubscribe(sub)
    done = [e for e in late if e["type"] == "agent.narration.completed"]
    assert done and done[0]["data"]["content"] == "Vou começar lendo a API dos gráficos."
    assert done[0]["data"]["status"] == "completed"
    # Cada delta carrega só o trecho novo: a soma é exatamente o texto final.
    every = [e for e in early + late if e["type"] == "agent.narration.delta"]
    assert "".join(e["data"]["text"] for e in every) == done[0]["data"]["content"]


# ── Teste C: resposta longa ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_c_long_narration_is_not_persisted_token_by_token(tmp_path):
    """Uma fala longa grava só início e fim; o texto gravado tem teto e o total é informado."""
    session, project, root, run = _run(tmp_path)
    pieces = [f"palavra{i} " for i in range(3000)]
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        await observed_chat(_Scripted(pieces), REQUEST, purpose="operation")
        session.commit()
    rows = _rows(session, run.id)
    kinds = [r.event_type for r in rows if r.event_type.startswith("agent.narration")]
    assert kinds == ["agent.narration.started", "agent.narration.completed"]
    done = next(r for r in rows if r.event_type == "agent.narration.completed").payload_json
    total = len("".join(pieces).strip())
    assert done["chars"] == total and done["truncated"] is True
    assert len(done["content"]) == NARRATION_PERSIST_CHARS
    # Nenhuma narração fica aberta no barramento depois do fim (memória liberada).
    assert get_bus().live(str(run.id))["narrations"] == []


# ── Teste D: narração e ferramentas na ordem real ─────────────────────────


@pytest.mark.asyncio
async def test_d_narration_tool_narration_tool_keeps_the_exact_order(tmp_path):
    """Narração → ferramenta → narração → ferramenta: a linha do tempo gravada segue a execução."""
    from agent.orchestrator.tool_loop import run_tool_loop
    from agent.tools.registry import ToolContext, build_default_registry

    (tmp_path / "a.py").write_text("x = 1\n")
    session, project, root, run = _run(tmp_path)
    script = [
        _Scripted(["Vou ler ", "o arquivo a.py."], calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})]),
        _Scripted(["Agora ", "listo a pasta."], calls=[ToolCall(id="c2", name="list_dir", arguments={"path": "."})]),
        _Scripted(["Pronto: nada a alterar."]),
    ]

    class _Seq(_Scripted):
        """Usa um roteiro por chamada ao modelo."""

        async def _chat_streaming(self, request, on_delta):
            """Delega à próxima resposta do roteiro."""
            return await script.pop(0)._chat_streaming(request, on_delta)

    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        await run_tool_loop(
            provider=_Seq([]),
            messages=[ChatMessage(role="user", content="investigue")],
            profile=ModelProfile(model_id="m", context_limit=8192, input_budget=6000, output_reserve=512),
            registry=build_default_registry(),
            ctx=ToolContext(project_root=str(tmp_path)),
            max_iterations=3,
        )
        session.commit()
    timeline = []
    for row in _rows(session, run.id):
        if row.event_type == "agent.narration.completed":
            timeline.append(("narração", row.payload_json["content"]))
        elif row.event_type == "tool.started":
            timeline.append(("ferramenta", row.payload_json["tool"]))
    assert timeline[:4] == [
        ("narração", "Vou ler o arquivo a.py."),
        ("ferramenta", "read_file"),
        ("narração", "Agora listo a pasta."),
        ("ferramenta", "list_dir"),
    ]
    # Argumentos de ferramenta nunca entram no texto da narração.
    assert all("path" not in text for kind, text in timeline if kind == "narração")


# ── Teste E: interrupção ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e_cancelled_generation_keeps_the_partial_narration(tmp_path):
    """Cancelada no meio, a narração é gravada como interrompida, com o texto recebido."""
    session, project, root, run = _run(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        task = asyncio.create_task(
            observed_chat(_Scripted(["Encontrei ", "uma incons"], hang=True), REQUEST, purpose="operation")
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    done = [r for r in _rows(session, run.id) if r.event_type == "agent.narration.completed"]
    assert len(done) == 1
    assert done[0].payload_json["status"] == "interrupted"
    assert done[0].payload_json["content"] == "Encontrei uma incons"


# ── Teste F: reconexão ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_f_live_snapshot_carries_the_partial_text_for_a_reconnecting_client(tmp_path):
    """Durante a geração, a foto ao vivo traz o texto já publicado; o anel reenvia com deslocamentos."""
    session, project, root, run = _run(tmp_path)
    gate = asyncio.Event()
    provider = _Scripted(["Verificando ", "os dados ", "recebidos ", "agora."], gate=gate)
    bus = get_bus()
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        task = asyncio.create_task(observed_chat(provider, REQUEST, purpose="operation"))
        for _ in range(50):
            await asyncio.sleep(0.001)
            if provider.sent_before_gate:
                break
        live = bus.live(str(run.id))
        assert len(live["narrations"]) == 1
        partial = live["narrations"][0]
        assert partial["text"] == "Verificando os dados "
        # O cliente que reconecta depois do evento de início recebe do anel só o que falta.
        replay = [e for e in bus.recent(str(run.id), partial["started_seq"]) if e["type"] == "agent.narration.delta"]
        rebuilt = partial["text"]
        gate.set()
        await task
        session.commit()
        replay += [
            e
            for e in bus.recent(str(run.id), max((e["seq"] for e in replay), default=partial["seq"]))
            if e["type"] == "agent.narration.delta"
        ]
    for event in replay:
        offset, text = event["data"]["offset"], event["data"]["text"]
        if offset + len(text) <= len(rebuilt):
            continue  # já recebido: não se repete
        rebuilt += text[len(rebuilt) - offset:]
    assert rebuilt == "Verificando os dados recebidos agora."


# ── Teste G: runs simultâneas ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_g_simultaneous_runs_never_mix_narrations(tmp_path):
    """Duas runs narrando ao mesmo tempo: cada assinante recebe só a sua fala."""
    a = _run(tmp_path / "a", name="a")
    b = _run(tmp_path / "b", name="b")
    bus = get_bus()
    subs = {str(a[3].id): bus.subscribe(str(a[3].id)), str(b[3].id): bus.subscribe(str(b[3].id))}

    async def narrate(ctx, words):
        """Executa uma chamada observada no contexto de uma run."""
        session, project, root, run = ctx
        with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
            await observed_chat(_Scripted(words), REQUEST, purpose="operation")
            session.commit()

    await asyncio.gather(narrate(a, ["Run ", "A ", "fala."]), narrate(b, ["Run ", "B ", "fala."]))
    await asyncio.sleep(0.01)
    for run_id, sub in subs.items():
        got = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
        bus.unsubscribe(sub)
        assert all(e["run_id"] == run_id for e in got)
        text = "".join(e["data"]["text"] for e in got if e["type"] == "agent.narration.delta")
        assert text == ("Run A fala." if run_id == str(a[3].id) else "Run B fala.")


# ── Teste H: conteúdo privado ─────────────────────────────────────────────


def _patch_transport(monkeypatch, module: str, body: bytes):
    """Substitui o transporte HTTP do provedor por um corpo de streaming fixo."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Exige streaming e devolve o corpo programado."""
        assert json.loads(request.content).get("stream") is True or "alt=sse" in str(request.url)
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        f"agent.providers.{module}.httpx.AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport})
    )


async def _narrated(tmp_path, provider, request=REQUEST):
    """Chama o provedor observado e devolve a resposta e o texto gravado da narração."""
    session, project, root, run = _run(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        resp = await observed_chat(provider, request, purpose="operation")
        session.commit()
    rows = _rows(session, run.id)
    done = [r.payload_json for r in rows if r.event_type == "agent.narration.completed"]
    return resp, (done[0]["content"] if done else None), rows


@pytest.mark.asyncio
async def test_h_ollama_thinking_and_tool_calls_never_become_narration(tmp_path, monkeypatch):
    """Canal `thinking`, bloco `<think>` e chamada de ferramenta do Ollama ficam fora da narração."""
    lines = [
        {"message": {"role": "assistant", "content": "", "thinking": "raciocínio privado"}, "done": False},
        {"message": {"role": "assistant", "content": "<think>outro segredo</think>"}, "done": False},
        {"message": {"role": "assistant", "content": "Vou inspecionar o componente."}, "done": False},
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "chart.js"}}}],
            },
            "done": False,
        },
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop", "eval_count": 9},
    ]
    _patch_transport(monkeypatch, "ollama", b"".join(json.dumps(x).encode() + b"\n" for x in lines))
    resp, narration, rows = await _narrated(tmp_path, OllamaProvider(base_url="http://127.0.0.1:11434"))
    assert narration == "Vou inspecionar o componente."
    assert resp.tool_calls and resp.tool_calls[0].name == "read_file"
    every = json.dumps([r.payload_json for r in rows if r.event_type.startswith("agent.narration")])
    assert "segredo" not in every and "privado" not in every and "chart.js" not in every


def _sse(*events) -> bytes:
    """Serializa eventos como linhas SSE `data:`."""
    return b"".join(b"data: " + (e if isinstance(e, bytes) else json.dumps(e).encode()) + b"\n\n" for e in events)


@pytest.mark.asyncio
async def test_h_openai_stream_keeps_tool_calls_and_hides_reasoning(tmp_path, monkeypatch):
    """No stream OpenAI, a chamada partida é remontada e o raciocínio não vira narração."""
    body = _sse(
        {"choices": [{"delta": {"reasoning_content": "pensamento privado"}}]},
        {"choices": [{"delta": {"content": "Vou ler "}}]},
        {"choices": [{"delta": {"content": "o gráfico."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "t1", "function": {"name": "read_file", "arguments": "{\"pa"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "th\": \"g.js\"}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
        b"[DONE]",
    )
    _patch_transport(monkeypatch, "openai_compatible", body)
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:9999/v1", allow_private_hosts=True)
    resp, narration, _ = await _narrated(tmp_path, provider)
    assert narration == "Vou ler o gráfico."
    assert resp.tool_calls[0].name == "read_file" and resp.tool_calls[0].arguments == {"path": "g.js"}
    assert resp.reasoning == "pensamento privado"


@pytest.mark.asyncio
async def test_h_anthropic_stream_keeps_tool_use_and_hides_thinking(tmp_path, monkeypatch):
    """No stream da Anthropic, `tool_use` é remontado e `thinking_delta` fica fora do texto."""
    body = _sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "privado"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Vou testar."}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu1", "name": "run_tests"}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"command\": "}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "\"pytest\"}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}},
    )
    _patch_transport(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(api_key="teste", base_url="http://127.0.0.1:9998", allow_private_hosts=True)
    resp, narration, _ = await _narrated(tmp_path, provider)
    assert narration == "Vou testar."
    assert resp.tool_calls[0].name == "run_tests" and resp.tool_calls[0].arguments == {"command": "pytest"}
    assert resp.reasoning == "privado"


@pytest.mark.asyncio
async def test_h_gemini_stream_keeps_function_calls_and_hides_thoughts(tmp_path, monkeypatch):
    """No stream do Gemini, `functionCall` não se perde e a parte `thought` fica fora do texto."""
    body = _sse(
        {"candidates": [{"content": {"parts": [{"text": "raciocínio", "thought": True}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "Vou listar a pasta."}]}}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "list_dir", "args": {"path": "."}}}]}, "finishReason": "STOP"}]},
    )
    _patch_transport(monkeypatch, "gemini", body)
    provider = GeminiProvider(api_key="teste", base_url="http://127.0.0.1:9997/v1beta", allow_private_hosts=True)
    resp, narration, _ = await _narrated(tmp_path, provider)
    assert narration == "Vou listar a pasta."
    assert resp.tool_calls[0].name == "list_dir"


# ── Teste I: compatibilidade ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_i_provider_without_streaming_shows_the_text_once_without_faking_fragments(tmp_path):
    """Sem streaming, a fala aparece inteira quando chega: um trecho só, marcado como não transmitido."""
    session, project, root, run = _run(tmp_path)
    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        await observed_chat(MockProvider(responses=["Analisei a estrutura dos dados."]), REQUEST, purpose="operation")
        session.commit()
    await asyncio.sleep(0.01)
    got = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    bus.unsubscribe(sub)
    started = [e for e in got if e["type"] == "agent.narration.started"]
    deltas = [e for e in got if e["type"] == "agent.narration.delta"]
    assert started and started[0]["data"]["streamed"] is False
    assert len(deltas) == 1 and deltas[0]["data"]["text"] == "Analisei a estrutura dos dados."


@pytest.mark.asyncio
async def test_i_final_answer_is_not_repeated_as_narration(tmp_path):
    """A resposta final já aparece na conversa: não vira narração duplicada."""
    session, project, root, run = _run(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        await observed_chat(_Scripted(["Os testes ", "passaram."]), REQUEST, purpose="final_answer")
        session.commit()
    assert not any(r.event_type.startswith("agent.narration") for r in _rows(session, run.id))


@pytest.mark.asyncio
async def test_i_json_only_response_produces_no_narration(tmp_path):
    """Resposta que é só a carga JSON da operação: nenhuma narração é inventada."""
    session, project, root, run = _run(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        await observed_chat(_Scripted(['{"path": ', '"a.py", "content": "x"}']), REQUEST, purpose="operation")
        session.commit()
    assert not any(r.event_type.startswith("agent.narration") for r in _rows(session, run.id))
