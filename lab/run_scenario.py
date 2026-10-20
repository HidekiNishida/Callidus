"""Cenário controlado: reproduz a última conversa real ("continue") com gpt-oss:20b.

Uso: python lab/run_scenario.py <label> <db> <root>
O script não toca no banco nem nos projetos do usuário: cria um banco novo e trabalha numa
cópia do projeto.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine, select

from agent.config import Settings
from agent.domain.enums import MemoryKind, TaskKind, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, MemoryCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import OperationAttemptModel, TaskModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

SOURCE = Path("/Users/hidekinishida/Documents/Projetos/Rede Social")


async def main() -> None:
    label = sys.argv[1]
    db_path = Path(sys.argv[2])
    root = Path(sys.argv[3])
    if db_path.exists():
        db_path.unlink()
    if root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, root)

    settings = Settings(data_dir=Path("data"), database_url=f"sqlite:///{db_path.resolve()}")
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()

    project = ProjectService(session).create_project(
        ProjectCreate(name="Rede Social (lab)", root_path=str(root))
    )
    # Memória do projeto igual à da conversa real: o objetivo que o "continue" continua.
    ProjectService(session).add_memory(
        project.id,
        MemoryCreate(
            kind=MemoryKind.CANONICAL,
            title="Objetivo global",
            content="Crie o frontend de uma rede social",
        ),
    )
    tasks = TaskService(session)
    root_task = tasks.create_task(
        project.id,
        TaskCreate(
            title="continue",
            objective="continue",
            kind=TaskKind.OBJECTIVE,
            metadata={"locale": "pt"},
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root_task.id,
            config={
                "provider": "meu_ollama",
                "model_id": "gpt-oss:20b",
                "approve_risky_tools": True,
                "use_generic_template": True,
                "browser_mode": "off",
            },
        ),
    )
    session.commit()

    started = time.monotonic()
    orchestrator = RunOrchestrator(session, settings)
    trace: list[dict] = []
    for _ in range(40):
        out = await orchestrator.step(run.id)
        session.commit()
        trace.append(out)
        if out.get("action") in {
            "run_completed",
            "run_terminal",
            "run_paused",
            "run_stalled",
            "run_failed",
            "blocked_decompose",
            "blocked_loop",
            "blocked_attempts",
            "blocked_context",
        }:
            break
    elapsed = time.monotonic() - started

    attempts = list(
        session.scalars(
            select(OperationAttemptModel)
            .where(OperationAttemptModel.task_id == root_task.id)
            .order_by(OperationAttemptModel.created_at)
        ).all()
    )
    all_attempts = list(session.scalars(select(OperationAttemptModel)).all())
    model_attempts = [a for a in all_attempts if a.kind == "model"]
    tool_attempts = [a for a in all_attempts if a.kind == "tool"]
    prompt_tokens = 0
    completion_tokens = 0
    for task in session.scalars(select(TaskModel)).all():
        usage = (task.metadata_json or {}).get("usage") or {}
        prompt_tokens += int(usage.get("prompt") or 0)
        completion_tokens += int(usage.get("completion") or 0)

    tasks_all = list(session.scalars(select(TaskModel)).all())
    report = {
        "label": label,
        "seconds": round(elapsed, 1),
        "steps": len(trace),
        "actions": [item.get("action") for item in trace],
        "model_attempts": len(model_attempts),
        "tool_attempts": len(tool_attempts),
        "failed_model_attempts": sum(1 for a in model_attempts if not a.success),
        "empty_responses": sum(
            1 for a in model_attempts if (a.error_message or "").find("resposta vazia") >= 0
        ),
        "tool_calls_requested": sum(
            len(((a.response_json or {}).get("tool_calls") or []))
            for a in model_attempts
            if isinstance(a.response_json, dict)
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "task_statuses": {t.title: t.status for t in tasks_all},
        "files_after": sorted(
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".DS_Store" not in p.name
        ),
        "run_status": run.status,
    }
    out = Path("lab/out") / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))


asyncio.run(main())
