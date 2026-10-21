"""
Validação manual com o modelo real (gpt-oss:20b via Ollama).

Uso:
    python scripts/chat_automation_manual.py "primeira mensagem" "segunda mensagem" ...

Cada mensagem é uma conversa: tarefa nova, run nova, o mesmo banco temporário.
O banco é sempre isolado — a validação nunca toca o banco do usuário.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AutomationModel, TaskModel
from agent.providers.ollama import OllamaProvider
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

MODEL = "gpt-oss:20b"


async def _one(
    session,
    project,
    provider,
    settings,
    objective: str,
    conversation_id,
) -> str:
    """Roda uma conversa (tarefa + run) e devolve a resposta final."""
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Pedido", objective=objective, conversation_id=conversation_id),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root.id,
            config={"provider": "ollama", "model": provider.default_model, "approve_risky_tools": True},
        ),
    )
    session.commit()
    orchestrator = RunOrchestrator(session, settings)
    for _ in range(14):
        out = await orchestrator.step(run.id)
        session.commit()
        print(f"  [step] {out.get('action')}")
        if out.get("action") in {"run_completed", "failed", "blocked"}:
            break
    task = session.get(TaskModel, root.id)
    return (task.consolidated_result_json or {}).get("final_answer", "")


async def converse(messages: list[str], *, model: str = MODEL) -> list[str]:
    """Roda uma sequência de conversas com o modelo local."""
    tmp = Path(tempfile.mkdtemp())
    # Banco isolado: a validação manual nunca toca o banco do usuário.
    url = f"sqlite:///{tmp / 'manual.db'}"
    os.environ["DATABASE_URL"] = url
    settings = Settings(data_dir=tmp / "data", database_url=url)
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(
        ProjectCreate(name="projeto", root_path=str(tmp))
    )
    provider = OllamaProvider(
        "http://127.0.0.1:11434", timeout=600.0, default_model=model
    )
    from agent.domain.schemas import ConversationCreate
    from agent.services.conversation_service import ConversationService

    conversation = ConversationService(session).create_conversation(
        project.id, ConversationCreate(title="Validação", locale="pt")
    )
    import agent.orchestrator.runner as runner_module

    original = runner_module._select_provider
    runner_module._select_provider = lambda settings, config: provider
    answers: list[str] = []
    try:
        for message in messages:
            print(f"\n=== USUÁRIO: {message}")
            answer = await _one(
                session, project, provider, settings, message, conversation.id
            )
            print(f"=== RESPOSTA:\n{answer}")
            answers.append(answer)
    finally:
        runner_module._select_provider = original
    print("\n=== AUTOMAÇÕES NO BANCO ===")
    for row in session.scalars(select(AutomationModel)).all():
        print(
            f"- id={row.id} nome={row.name!r} estado={row.state} "
            f"gatilho={row.trigger_json.get('cron') or row.trigger_json.get('interval_seconds') or row.trigger_json.get('run_at')} "
            f"fuso={row.timezone} proximo={row.next_run_at}"
        )
    session.close()
    return answers


def main() -> None:
    """Ponto de entrada: as mensagens vêm da linha de comando."""
    messages = sys.argv[1:]
    if not messages:
        messages = [
            "Todos os dias às 9h, verifique os testes deste projeto e me avise "
            "caso algum esteja falhando."
        ]
    asyncio.run(converse(messages))


if __name__ == "__main__":
    main()
