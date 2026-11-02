"""
Arquivo: lab/medir_narracao.py
Nome: medir_narracao.py
Propósito: medir, com um modelo local real, a narração em tempo real — do fragmento do Ollama ao evento entregue.
Responsabilidade: laboratório — verifica o streaming de ponta a ponta (teste B) e mede TTFT, latência por lote,
quantidade de eventos e crescimento de memória; não faz parte da suíte (precisa do Ollama local).
Componentes: main(), _medir().
Dependências: agent.observability, agent.providers (ollama, observed), agent.context.operation_builder (NARRATION_HINT),
agent.orchestrator.tool_loop (esquemas de ferramentas), agent.persistence (banco temporário).
Observações: banco e pasta isolados em `lab/out/narracao-<label>/`; nada do `data/agent.db` do usuário é tocado.

Uso:
    python lab/medir_narracao.py --model qwen3-vl:8b --label qwen3
    python lab/medir_narracao.py --model gpt-oss:20b --label gptoss

Saída: `lab/out/narracao-<label>.json` e um resumo no terminal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# O orquestrador primeiro: importar `operation_builder` sozinho cai num ciclo de import antigo.
import agent.orchestrator  # noqa: E402,F401
from agent.config import Settings  # noqa: E402
from agent.context.operation_builder import NARRATION_HINT  # noqa: E402
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate  # noqa: E402
from agent.observability import get_bus, observe  # noqa: E402
from agent.orchestrator.tool_loop import INSPECTION_TOOLS, tool_schemas  # noqa: E402
from agent.persistence.database import build_session_factory, init_db  # noqa: E402
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile  # noqa: E402
from agent.providers.observed import observed_chat  # noqa: E402
from agent.providers.ollama import OllamaProvider  # noqa: E402
from agent.services.project_service import ProjectService  # noqa: E402
from agent.services.run_service import RunService  # noqa: E402
from agent.services.task_service import TaskService  # noqa: E402
from agent.tools.registry import build_default_registry  # noqa: E402

PEDIDO = (
    "Investigue por que os gráficos da seção Inteligência não aparecem. "
    "Comece inspecionando o projeto com as ferramentas."
)


async def _medir(model: str, base_url: str, work: Path) -> dict:
    """Faz uma chamada real observada, com ferramentas, e mede a narração entregue ao assinante.

    Args:
        model: modelo do Ollama.
        base_url: endereço do Ollama.
        work: pasta isolada para o banco temporário.

    Returns:
        As medidas da chamada (tempos em ms, contagens e memória).
    """
    settings = Settings(data_dir=work / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="medida", root_path=str(work)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Medida", objective=PEDIDO))
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id))
    session.commit()
    (work / "intelligence.js").write_text("export function chart(data) { return data.series.map(x => x.v); }\n")

    bus = get_bus()
    sub = bus.subscribe(str(run.id))
    request = ChatCompletionRequest(
        # Mesmo arranjo da operação real (`context/budget.py`): o formato de saída, com o pedido
        # de narração, vai na mensagem do usuário.
        messages=[
            ChatMessage(role="system", content="Siga o objetivo e o formato pedido. Responda de forma concisa."),
            ChatMessage(
                role="user",
                content=(
                    f"## objetivo\n{PEDIDO}\n\n## formato-saída\n"
                    f"Inspecione o projeto com as ferramentas. {NARRATION_HINT}"
                ),
            ),
        ],
        profile=ModelProfile(model_id=model, context_limit=8192, input_budget=6000, output_reserve=1024),
        tools=tool_schemas(build_default_registry(), INSPECTION_TOOLS),
    )
    provider = OllamaProvider(base_url=base_url)
    arrivals: list[tuple[float, dict]] = []

    async def drain() -> None:
        """Recebe os eventos como um cliente SSE e marca a hora de chegada de cada um."""
        while True:
            env = await sub.queue.get()
            arrivals.append((time.perf_counter(), env))

    reader = asyncio.create_task(drain())
    tracemalloc.start()
    started = time.perf_counter()
    with observe(session, run_id=run.id, project_id=project.id, task_id=root.id, agent="executor"):
        response = await observed_chat(provider, request, purpose="operation")
        session.commit()
    total = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    await asyncio.sleep(0.05)
    reader.cancel()
    bus.unsubscribe(sub)

    def ms(t: float) -> int:
        """Milissegundos desde o início da chamada."""
        return int((t - started) * 1000)

    output = [(t, e) for t, e in arrivals if e["type"] == "agent.output.delta"]
    narration = [(t, e) for t, e in arrivals if e["type"] == "agent.narration.delta"]
    done = [e for _, e in arrivals if e["type"] == "agent.narration.completed"]
    return {
        "model": model,
        "total_ms": int(total * 1000),
        "first_output_delta_ms": ms(output[0][0]) if output else None,
        "first_narration_delta_ms": ms(narration[0][0]) if narration else None,
        "narration_deltas": len(narration),
        "narration_delta_times_ms": [ms(t) for t, _ in narration][:40],
        "narration": done[0]["data"]["content"] if done else None,
        "narration_status": done[0]["data"]["status"] if done else None,
        "tool_calls": [c.name for c in (response.tool_calls or [])],
        "reasoning_chars": len(response.reasoning or ""),
        "reasoning_in_narration": bool(
            response.reasoning and done and response.reasoning[:40] in done[0]["data"]["content"]
        ),
        "output_head": "".join(e["data"]["text"] for _, e in output)[:300],
        "events_delivered": len(arrivals),
        "peak_python_kib": peak // 1024,
    }


def main() -> None:
    """Lê os argumentos, mede e grava o resultado em `lab/out/`."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    parser.add_argument("--model", default="qwen3-vl:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--label", default="atual")
    args = parser.parse_args()
    out = Path(__file__).resolve().parent / "out"
    work = out / f"narracao-{args.label}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result = asyncio.run(_medir(args.model, args.base_url, work))
    (out / f"narracao-{args.label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
