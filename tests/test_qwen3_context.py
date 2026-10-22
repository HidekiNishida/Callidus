"""
Arquivo: tests/test_qwen3_context.py
Nome: test_qwen3_context.py
Propósito: verificar que a conversa com um modelo de janela pequena (qwen3:8b) cabe na janela e leva só o contexto certo.
Responsabilidade: camada de testes — resumo de resultados antigos no ciclo de ferramentas, preservação do pedido e das regras, e ausência do estado de tarefas irmãs nas regras do projeto.
Componentes: fit_history, history_tokens, run_tool_loop (janela pequena), OperationContextBuilder (regras do projeto).
Dependências: agent.orchestrator.tool_loop, agent.context.operation_builder, agent.memory.operational, agent.persistence, pytest.
Observações: provedor falso com roteiro; banco SQLite temporário; nenhum modelo real.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.tool_loop import fit_history, history_tokens, run_tool_loop
from agent.providers.base import ChatCompletionRequest, ChatMessage, ModelProfile, ProviderCapabilities, ToolCall
from agent.tools.registry import ToolContext, build_default_registry


def _profile(context_limit: int = 4096, output_reserve: int = 512) -> ModelProfile:
    """Perfil de um modelo pequeno com janela curta."""
    return ModelProfile(model_id="qwen3:8b", context_limit=context_limit, input_budget=2000, output_reserve=output_reserve)


def _history(results: int, size: int = 6000) -> list[ChatMessage]:
    """Conversa com pedido, regras e `results` resultados de ferramenta grandes."""
    history = [
        ChatMessage(role="system", content="REGRAS: responda só JSON."),
        ChatMessage(role="user", content="OBJETIVO: corrigir calc.py"),
    ]
    for index in range(results):
        history.append(
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[{"id": f"c{index}", "function": {"name": "read_file", "arguments": {"path": f"f{index}.py"}}}],
            )
        )
        history.append(ChatMessage(role="tool", content=f"arquivo {index}:" + "y" * size, tool_call_id=f"c{index}"))
    return history


def test_fit_history_summarises_old_results_and_keeps_the_rest_intact():
    """Resultados antigos viram resumo; os dois últimos, o pedido e as regras ficam inteiros."""
    history = _history(5, size=3000)
    profile = _profile()
    before = [m.content for m in history]
    applied = fit_history(history, profile)

    assert applied, "a conversa não cabia e nada foi resumido"
    assert history_tokens(history) <= profile.context_limit - profile.output_reserve
    assert history[0].content == before[0] and history[1].content == before[1]
    tools = [m for m in history if m.role == "tool"]
    assert tools[-1].content == before[-1] and tools[-2].content == before[-3]
    assert all(m.content.startswith("[resumido") for m in tools[: len(applied)])
    # O resumo diz de onde veio: o começo do resultado continua lá.
    assert "arquivo 0:" in tools[0].content


def test_fit_history_does_nothing_when_the_conversation_fits():
    """Conversa pequena não é tocada."""
    history = _history(2, size=100)
    assert fit_history(history, _profile()) == []


class _Reader:
    """Modelo falso que lê arquivos até cansar e depois entrega; registra o tamanho de cada pedido."""

    name = "fake"
    supports_streaming = False

    def __init__(self, reads: int) -> None:
        """Prepara o roteiro: `reads` leituras e a entrega."""
        self.reads = reads
        self.requests: list[ChatCompletionRequest] = []

    def capabilities(self) -> ProviderCapabilities:
        """Declara ferramentas e laço de ferramentas."""
        return ProviderCapabilities(tools=True, tool_loop=True)

    async def chat(self, request: ChatCompletionRequest):
        """Pede uma leitura por rodada; depois responde o JSON."""
        self.requests.append(request)
        index = len(self.requests)
        if index <= self.reads:
            calls = [ToolCall(id=f"c{index}", name="read_file", arguments={"path": f"big{index}.txt"})]
            content = ""
        else:
            calls, content = None, '{"path":"a.txt","content":"ok"}'
        return type("R", (), {"content": content, "tool_calls": calls, "reasoning": None, "completion_tokens_estimate": 5})()


@pytest.mark.asyncio
async def test_tool_loop_never_sends_more_than_the_window(tmp_path: Path):
    """Com leituras grandes e janela curta, cada pedido cabe na janela e o pedido original segue nele."""
    for index in range(1, 6):
        (tmp_path / f"big{index}.txt").write_text(f"conteúdo {index}\n" + "z" * 5000)
    profile = _profile(context_limit=4096, output_reserve=512)
    provider = _Reader(reads=4)
    outcome = await run_tool_loop(
        provider=provider,
        messages=[ChatMessage(role="system", content="REGRAS"), ChatMessage(role="user", content="OBJETIVO: corrigir")],
        profile=profile,
        registry=build_default_registry(),
        ctx=ToolContext(project_root=str(tmp_path)),
        max_iterations=6,
        max_tool_calls=6,
        chat=lambda p, r, purpose, stream: p.chat(r),
    )
    assert outcome.content == '{"path":"a.txt","content":"ok"}'
    limit = profile.context_limit - profile.output_reserve
    for request in provider.requests:
        assert history_tokens(request.messages, request.tools) <= limit
        assert request.messages[0].content == "REGRAS"
        assert request.messages[1].content == "OBJETIVO: corrigir"
    # Sem o ajuste, a última chamada levaria as quatro leituras inteiras (~4 × 2000 caracteres).
    last_tools = [m for m in provider.requests[-1].messages if m.role == "tool"]
    assert any(m.content.startswith("[resumido") for m in last_tools)


def test_project_rules_do_not_carry_sibling_task_state(tmp_path: Path):
    """O estado de execução de uma tarefa irmã não entra nas regras do projeto de outra tarefa."""
    from agent.context.operation_builder import OperationContextBuilder
    from agent.memory.operational import upsert_operational
    from agent.persistence.database import build_session_factory, init_db
    from agent.services.project_service import ProjectService
    from agent.services.task_service import TaskService

    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    session = build_session_factory(init_db(settings=settings))()
    workspace = tmp_path / "w"
    workspace.mkdir()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    sibling = tasks.create_task(project.id, TaskCreate(title="Corrigir calc.py", objective="SIBLING corrigir a soma"))
    current = tasks.create_task(project.id, TaskCreate(title="Criar README", objective="Criar README.md com o uso"))
    upsert_operational(session, sibling, status_note="verificação reprovada: FAILURES")
    session.commit()

    builder = OperationContextBuilder(session, settings)
    rules, _note = builder._memory_block(project.id, current)
    assert "SIBLING" not in rules
    assert "Estado de Corrigir calc.py" not in rules
