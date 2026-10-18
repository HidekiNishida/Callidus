# tests/test_observability_streaming.py — fragmentos reais do modelo, resposta final sem duplicar, erro e cancelamento
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.observability import get_bus, observe
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel
from agent.providers.base import ChatCompletionRequest, ChatCompletionResponse, ChatMessage, LLMProvider, ModelProfile, ProviderError
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.mock import MockProvider
from agent.providers.observed import observed_chat
from agent.providers.ollama import OllamaProvider
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

REQUEST = ChatCompletionRequest(messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m"))


def _run(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="o"))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id))
    session.commit()
    return session, project, root, run


def _patch_transport(monkeypatch, module: str, body: bytes, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(status, content=body)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(f"agent.providers.{module}.httpx.AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport}))


async def _observed(tmp_path, provider, *, purpose="operation"):
    session, project, root, run = _run(tmp_path)
    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    error = None
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id, agent="executor"):
        try:
            resp = await observed_chat(provider, REQUEST, purpose=purpose)
        except Exception as exc:
            resp, error = None, exc
        session.commit()
    await asyncio.sleep(0.01)
    delivered = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    bus.unsubscribe(sub)
    rows = list(session.scalars(select(EventLogModel).where(EventLogModel.run_id == run.id).order_by(EventLogModel.seq)))
    return resp, error, delivered, rows


def _ndjson(*objs) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


@pytest.mark.asyncio
async def test_ollama_streams_fragments_and_final_answer_is_not_duplicated(tmp_path, monkeypatch):
    body = _ndjson(
        {"message": {"content": "Olá"}, "done": False},
        {"message": {"content": ", mundo"}, "done": False},
        {"message": {"content": "!"}, "done": True, "done_reason": "stop", "prompt_eval_count": 7, "eval_count": 3},
    )
    _patch_transport(monkeypatch, "ollama", body)
    provider = OllamaProvider("http://ollama")
    resp, error, delivered, rows = await _observed(tmp_path, provider)
    assert error is None and resp.content == "Olá, mundo!"
    assert resp.prompt_tokens_estimate == 7 and provider.last_usage

    deltas = [e for e in delivered if e["type"] == "agent.output.delta"]
    assert deltas and "".join(e["data"]["text"] for e in deltas) == "Olá, mundo!"
    assert all(not e["persisted"] for e in deltas)
    started = next(r for r in rows if r.event_type == "agent.started")
    assert started.payload_json["streaming"] is True and started.agent == "executor"
    done = [r for r in rows if r.event_type == "agent.output.completed"]
    assert len(done) == 1 and done[0].payload_json["content"] == "Olá, mundo!" and done[0].payload_json["streamed"]
    assert not any(r.event_type == "agent.output.delta" for r in rows)
    assert get_bus().live(str(started.run_id))["outputs"] == []


@pytest.mark.asyncio
async def test_llamacpp_streams_openai_sse(tmp_path, monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "par"}}]},
        {"choices": [{"delta": {"content": "cial"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
    ]
    body = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
    _patch_transport(monkeypatch, "llamacpp", body)
    resp, error, delivered, rows = await _observed(tmp_path, LlamaCppProvider("http://llama"))
    assert error is None and resp.content == "parcial" and resp.completion_tokens_estimate == 2
    assert "".join(e["data"]["text"] for e in delivered if e["type"] == "agent.output.delta") == "parcial"


@pytest.mark.asyncio
async def test_stream_cut_midway_is_a_failure_with_the_partial_text(tmp_path, monkeypatch):
    _patch_transport(monkeypatch, "ollama", _ndjson({"message": {"content": "come"}, "done": False}))
    resp, error, delivered, rows = await _observed(tmp_path, OllamaProvider("http://ollama"))
    assert isinstance(error, ProviderError)
    failed = [r for r in rows if r.event_type == "agent.output.failed"]
    assert len(failed) == 1 and failed[0].payload_json["partial_chars"] == 4
    assert failed[0].payload_json["partial_tail"] == "come"
    assert not any(r.event_type == "agent.output.completed" for r in rows)


@pytest.mark.asyncio
async def test_provider_without_streaming_never_fakes_fragments(tmp_path):
    resp, error, delivered, rows = await _observed(tmp_path, MockProvider(responses=["resposta inteira"]))
    assert resp.content == "resposta inteira"
    assert not any(e["type"] == "agent.output.delta" for e in delivered)
    status = [e["data"]["status"] for e in delivered if e["type"] == "agent.status"]
    assert status == ["waiting_full_response"]
    started = next(r for r in rows if r.event_type == "agent.started")
    assert started.payload_json["streaming"] is False
    done = next(r for r in rows if r.event_type == "agent.output.completed")
    assert done.payload_json["streamed"] is False and done.payload_json["deltas"] == 0


class _Hanging(LLMProvider):
    name = "hanging"
    supports_streaming = True

    async def list_models(self):
        return []

    async def chat(self, request):
        raise AssertionError("não deveria chamar chat")

    async def chat_streaming(self, request, on_delta) -> ChatCompletionResponse:
        on_delta("pensando")
        await asyncio.sleep(3600)
        raise AssertionError("inalcançável")


@pytest.mark.asyncio
async def test_cancelled_call_is_recorded_as_cancelled_not_completed(tmp_path):
    session, project, root, run = _run(tmp_path)
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id):
        task = asyncio.create_task(observed_chat(_Hanging(), REQUEST, purpose="operation"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    rows = list(session.scalars(select(EventLogModel).where(EventLogModel.run_id == run.id)))
    failed = [r for r in rows if r.event_type == "agent.output.failed"]
    assert len(failed) == 1 and failed[0].payload_json["cancelled"] is True
    assert failed[0].payload_json["partial_tail"] == "pensando"
    assert not any(r.event_type == "agent.output.completed" for r in rows)


@pytest.mark.asyncio
async def test_outside_a_run_the_provider_is_called_plainly(monkeypatch):
    resp = await observed_chat(MockProvider(responses=["ok"]), REQUEST, purpose="chat")
    assert resp.content == "ok"
