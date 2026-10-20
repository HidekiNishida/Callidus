# tests/test_observability_e2e.py — execução real → eventos → SSE → redutor da interface (Node) → mesmo estado do servidor
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.api.observe_routes import sse_stream
from agent.observability import emit, get_bus, observe
from agent.observability.snapshot import run_snapshot
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ChatCompletionRequest, ChatCompletionResponse, ChatMessage, LLMProvider, ModelProfile, ProviderError
from agent.providers.observed import observed_chat
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

NODE = shutil.which("node")
REPLAY = Path(__file__).parent / "web" / "replay.mjs"
REQUEST = ChatCompletionRequest(messages=[ChatMessage(role="user", content="oi")], profile=ModelProfile(model_id="m"))

pytestmark = pytest.mark.skipif(NODE is None, reason="node indisponível: o redutor da interface roda em Node")


class _Streaming(LLMProvider):
    name = "fake-stream"
    supports_streaming = True

    def __init__(self, pieces: list[str]):
        self.pieces = pieces

    async def list_models(self):
        return []

    async def _chat(self, request):
        raise AssertionError("deveria transmitir")

    async def _chat_streaming(self, request, on_delta) -> ChatCompletionResponse:
        for piece in self.pieces:
            on_delta(piece)
            await asyncio.sleep(0.15)
        return ChatCompletionResponse(content="".join(self.pieces))


class _Broken(_Streaming):
    async def _chat_streaming(self, request, on_delta) -> ChatCompletionResponse:
        on_delta("começ")
        raise ProviderError("conexão caiu")


class _Req:
    async def is_disconnected(self) -> bool:
        return False


def _parse(chunk: str) -> list[dict]:
    out = []
    for block in chunk.split("\n\n"):
        item: dict = {"event": None}
        for line in block.splitlines():
            if line.startswith("event: "):
                item["event"] = line[7:]
            elif line.startswith("data: "):
                item["data"] = json.loads(line[6:])
        if "data" in item:
            out.append(item)
    return out


async def _collect(gen, into: list):
    try:
        async for chunk in gen:
            into.extend(_parse(chunk))
    finally:
        await gen.aclose()


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def _ui(snapshot: dict, messages: list[dict]) -> dict:
    proc = subprocess.run(
        [NODE, str(REPLAY)],
        input=json.dumps({"snapshot": _jsonable(snapshot), "messages": messages}),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(proc.stdout)


def _setup(tmp_path: Path, objective: str):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_project", workspace)
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="e2e", root_path=str(workspace)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Objetivo", objective=objective))
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True})
    )
    session.commit()
    return settings, factory, session, project, root, run


@pytest.mark.asyncio
async def test_real_run_through_sse_reaches_the_same_state_in_the_interface(tmp_path):
    settings, factory, session, project, root, run = _setup(tmp_path, "e2e corrigir calc.py e validar")
    bus = get_bus()
    before = run_snapshot(session, run.id)
    got: list[dict] = []
    reader = asyncio.create_task(
        _collect(sse_stream(run.id, _Req(), before["last_seq"], factory=factory, bus=bus, heartbeat=0.05), got)
    )
    await asyncio.sleep(0.1)

    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id, agent="executor"):
        answer = await observed_chat(_Streaming(["Vou ", "corrigir ", "calc.py"]), REQUEST, purpose="operation")
        with pytest.raises(ProviderError):
            await observed_chat(_Broken([]), REQUEST, purpose="operation")
        session.commit()
    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=80)
    session.commit()
    assert log[-1]["action"] == "run_completed"
    await asyncio.wait_for(reader, 10)
    after = run_snapshot(session, run.id)

    ui = _ui(before, got)

    # Árvore: toda tarefa (inclusive as criadas durante a execução) com o mesmo status do banco.
    assert set(ui["tasks"]) == {t["id"] for t in after["tasks"]}
    assert {i: t["status"] for i, t in ui["tasks"].items()} == {t["id"]: t["status"] for t in after["tasks"]}
    assert not any(t["interrupted"] for t in ui["tasks"].values())
    [root_node] = ui["tree"]
    assert root_node["id"] == str(root.id) and root_node["children"] >= 2 and root_node["done"] == root_node["total"]

    # Cabeçalho e fim da transmissão.
    assert ui["header"]["status"] == "completed" and ui["header"]["mode"] == "replay" and ui["ended"]
    assert ui["connection"] == "ended" and got[-1]["event"] == "end"
    assert ui["header"]["progress"] == after["header"]["progress"]
    assert ui["lastSeq"] == after["last_seq"]

    # Respostas do modelo: transmitida sem duplicar e falha com texto parcial, sem virar concluída.
    texts = {o["status"]: o for o in ui["outputs"]}
    assert texts["completed"]["text"] == answer.content == "Vou corrigir calc.py" and texts["completed"]["streaming"]
    assert texts["failed"]["text"] == "começ"
    assert sum(1 for m in got if m["data"].get("type") == "agent.output.delta") >= 2

    # Ferramentas, arquivo alterado com diff, testes e verificação.
    assert any(o["kind"] == "tool" and o["tool"] == "write_file" and o["status"] == "ok" for o in ui["ops"])
    tests = [o for o in ui["ops"] if o["kind"] == "test"]
    assert tests and tests[-1]["status"] == "ok" and tests[-1]["exit_code"] == 0 and tests[-1]["counts"]["passed"] >= 1
    assert any(f["type"] == "file.changed" and f["path"].endswith("calc.py") and f["hasDiff"] for f in ui["files"])
    assert any(v["status"] == "passed" for v in ui["verifications"])
    assert not any(v["status"] == "started" for v in ui["verifications"])

    # Entrega: nada repetido; persistidos e fragmentos chegaram pelo mesmo canal.
    assert ui["metrics"]["duplicates"] == 0 and ui["metrics"]["ephemeral"] > 0
    session.close()


@pytest.mark.asyncio
async def test_interrupted_run_reopened_in_the_interface_is_never_shown_as_completed(tmp_path):
    settings, factory, session, project, root, run = _setup(tmp_path, "e2e corrigir calc.py e validar")
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id, agent="executor"):
        emit("command.started", {"call_id": "c1", "command": "pytest -q"}, commit=True)
        emit("command.output", {"call_id": "c1", "stream": "stdout", "text": "..."})
    get_bus().reset()  # o processo morreu: o que estava só em memória se perdeu

    ui = _ui(run_snapshot(session, run.id), [])
    assert ui["header"]["mode"] == "interrupted"
    [op] = [o for o in ui["ops"] if o["kind"] == "command"]
    assert op["status"] == "interrupted" and op["exit_code"] is None
    assert ui["tasks"][str(root.id)]["interrupted"] is True

    # Retomada: um passo novo segue de onde parou; a operação antiga continua interrompida, não concluída.
    before = run_snapshot(session, run.id)
    got: list[dict] = []
    reader = asyncio.create_task(
        _collect(sse_stream(run.id, _Req(), before["last_seq"], factory=factory, bus=get_bus(), heartbeat=0.05), got)
    )
    await asyncio.sleep(0.1)
    await RunOrchestrator(session, settings).step(run.id)
    session.commit()
    await asyncio.sleep(0.3)
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader
    resumed = _ui(before, got)
    assert resumed["header"]["mode"] == "live"
    assert [o["status"] for o in resumed["ops"] if o["kind"] == "command"] == ["interrupted"]
    assert any(m["data"].get("type") == "task.started" or m["data"].get("type", "").startswith("task.") for m in got if not m["event"])
    session.close()
