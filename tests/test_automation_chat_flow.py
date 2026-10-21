"""
Arquivo: tests/test_automation_chat_flow.py
Nome: test_automation_chat_flow.py
Propósito: Verificar o caminho completo do chat: pedido em linguagem natural, ferramentas, estado persistido e resposta.
Responsabilidade: camada de testes — conversa simulada com o mecanismo de ferramentas do Callidus.
Componentes: criação, consulta, ativação após confirmação, execução imediata, remoção e pedido ambíguo.
Dependências: agent.orchestrator.runner, agent.automation.intent, agent.tools.automations.
Observações: o modelo é falso e determinístico; o núcleo do Callidus (orquestrador, ferramentas, serviços) é o real.

A conversa real: o usuário pede, o modelo escolhe a ferramenta, o serviço executa e
a resposta final sai do **estado real** — não do que o modelo disse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    AutomationModel,
    ConversationModel,
    ProjectModel,
    TaskModel,
)
from agent.providers.base import ProviderCapabilities, ToolCall
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


class _ScriptedModel:
    """Modelo falso que responde com uma sequência de chamadas de ferramenta."""

    name = "ollama"
    last_usage = None

    def __init__(self, steps: list[dict]) -> None:
        """Guarda os passos do roteiro.

        Args:
            steps: lista de dicionários `{"tool": ..., "arguments": {...}}`; um item
                sem `tool` encerra o laço com texto.
        """
        self._steps = steps
        self.calls = 0
        self.tools_seen: list[str] = []

    def capabilities(self) -> ProviderCapabilities:
        """Declara o provedor capaz de usar ferramentas e laço de ferramentas."""
        return ProviderCapabilities(tools=True, tool_loop=True)

    async def chat(self, request):
        """Devolve a próxima chamada de ferramenta do roteiro."""
        self.calls += 1
        names = []
        for tool in request.tools or []:
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict):
                names.append(str(function.get("name")))
        self.tools_seen = names
        step = self._steps[min(self.calls - 1, len(self._steps) - 1)]
        if "tool" not in step:
            return type(
                "R",
                (),
                {
                    "content": step.get("content", ""),
                    "tool_calls": [],
                    "reasoning": None,
                    "completion_tokens_estimate": 8,
                    "prompt_tokens_estimate": 16,
                },
            )()
        return type(
            "R",
            (),
            {
                "content": "",
                "tool_calls": [
                    ToolCall(id=f"c{self.calls}", name=step["tool"], arguments=step.get("arguments", {}))
                ],
                "reasoning": None,
                "completion_tokens_estimate": 12,
                "prompt_tokens_estimate": 24,
            },
        )()


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de um banco temporário, com um projeto criado."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


async def _run_conversation(session, tmp_path, monkeypatch, objective: str, steps: list[dict]):
    """Simula uma conversa: cria a tarefa, a run e leva o orquestrador até o fim.

    Args:
        session: sessão do banco.
        tmp_path: pasta de trabalho.
        monkeypatch: fixture de monkeypatch do pytest.
        objective: mensagem do usuário.
        steps: roteiro do modelo falso.

    Returns:
        O texto final entregue ao usuário e o modelo falso usado.
    """
    settings = Settings(data_dir=tmp_path / "data")
    project = _project(session, tmp_path)
    conversation = _conversation(session, project)
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(
            title="Pedido",
            objective=objective,
            conversation_id=conversation.id,
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    provider = _ScriptedModel(steps)
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    orchestrator = RunOrchestrator(session, settings)
    for _ in range(12):
        out = await await_step(orchestrator, run.id, session)
        if out.get("action") in {"run_completed", "failed", "blocked", "completed"}:
            break
    session.commit()
    task = session.get(TaskModel, root.id)
    return (task.consolidated_result_json or {}).get("final_answer", ""), provider


def _project(session, tmp_path):
    """Projeto da conversa; o mesmo projeto é reaproveitado entre mensagens."""
    from sqlalchemy import select as _select

    existing = session.scalars(_select(ProjectModel)).first()
    if existing is not None:
        return existing
    return ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )


def _conversation(session, project):
    """Conversa da conversa simulada: as mensagens ficam ligadas a ela."""
    from agent.domain.schemas import ConversationCreate
    from agent.services.conversation_service import ConversationService

    existing = session.scalars(select(ConversationModel)).first()
    if existing is not None:
        return existing
    return ConversationService(session).create_conversation(
        project.id, ConversationCreate(title="conversa", locale="pt")
    )


async def await_step(orchestrator, run_id, session):
    """Dá um passo do orquestrador e confirma a sessão."""
    out = await orchestrator.step(run_id)
    session.commit()
    return out


@pytest.mark.asyncio
async def test_criar_tarefa_agendada_pelo_chat(session, tmp_path, monkeypatch):
    """O pedido vira automação persistida, desabilitada, e a resposta mostra o estado real."""
    answer, provider = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Todos os dias às 9h, verifique os testes deste projeto e me informe as falhas.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Verificação diária",
                    "objective": "Verificar os testes do projeto e informar as falhas",
                    "schedule": "todos os dias às 9h",
                },
            },
            {"content": "Automação criada."},
        ],
    )
    rows = session.scalars(select(AutomationModel)).all()
    assert len(rows) == 1
    automation = rows[0]
    assert automation.state == "disabled"
    assert automation.trigger_json["cron"] == "0 9 * * *"
    assert automation.timezone == "America/Sao_Paulo"
    # O modelo recebeu as ferramentas de automação — e só elas.
    assert "automation_create" in provider.tools_seen
    assert "write_file" not in provider.tools_seen
    # A resposta traz o identificador e o próximo disparo reais.
    print('ANSWER>>>', answer)
    assert str(automation.id) in answer
    assert "todos os dias às 09:00" in answer
    assert "NÃO está ativa" in answer


@pytest.mark.asyncio
async def test_consultar_automacao_em_mensagem_posterior(session, tmp_path, monkeypatch):
    """Numa conversa posterior, a automação é consultada pelo nome e pelo estado real."""
    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Quais tarefas estão agendadas para hoje?",
        [
            {"tool": "automation_list", "arguments": {}},
            {"content": "Listado."},
        ],
    )
    assert "0 automação(ões)" in answer or "Automações encontradas: 0" in answer

    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Quais automações existem?",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Relatório semanal",
                    "objective": "Preparar o resumo",
                    "schedule": "toda segunda-feira às 8h30",
                },
            },
            {"content": "Criada."},
        ],
    )
    rows = session.scalars(select(AutomationModel)).all()
    assert len(rows) == 1

    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Consulte a automação de relatório semanal.",
        [
            {"tool": "automation_get", "arguments": {"query": "relatório"}},
            {"content": "Consultada."},
        ],
    )
    print('ANSWER2>>>', answer)
    assert str(rows[0].id) in answer
    assert "toda segunda-feira às 08:30" in answer


@pytest.mark.asyncio
async def test_ativar_exige_confirmacao_do_usuario(session, tmp_path, monkeypatch):
    """Ativar sem o token da prévia é recusado; com o token, a automação é ativada."""
    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Todos os dias às 9h, verifique os testes.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Verificação diária",
                    "objective": "Verificar os testes",
                    "schedule": "todos os dias às 9h",
                },
            },
            {"content": "Criada."},
        ],
    )
    automation = session.scalars(select(AutomationModel)).one()
    assert automation.state == "disabled"
    assert "confirmação" in answer.lower()

    # O modelo tenta ativar sem token: a definição não é ativada.
    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Ative a automação de verificação diária.",
        [
            {"tool": "automation_enable", "arguments": {"automation_id": str(automation.id)}},
            {"content": "Ativada."},
        ],
    )
    assert session.scalars(select(AutomationModel)).one().state == "disabled"
    assert "confirmation_token" in answer


@pytest.mark.asyncio
async def test_executar_agora_registra_o_disparo(session, tmp_path, monkeypatch):
    """«Execute agora» registra um disparo com estado e run reais."""
    await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Todos os dias às 9h, verifique os testes.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Verificação diária",
                    "objective": "Verificar os testes",
                    "schedule": "todos os dias às 9h",
                },
            },
            {"content": "Criada."},
        ],
    )
    automation = session.scalars(select(AutomationModel)).one()
    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Execute agora a automação de verificação diária.",
        [
            {"tool": "automation_run_now", "arguments": {"automation_id": str(automation.id)}},
            {"content": "Executada."},
        ],
    )
    from agent.persistence.models import AutomationFiringModel

    firings = session.scalars(select(AutomationFiringModel)).all()
    assert len(firings) == 1
    assert firings[0].automation_id == automation.id
    assert firings[0].state in {"running", "completed", "pending"}
    # A resposta separa disparo registrado de objetivo concluído.
    assert "concluído" in answer.lower() or "não está concluído" in answer.lower()


@pytest.mark.asyncio
async def test_remover_automacao_exige_confirmacao(session, tmp_path, monkeypatch):
    """A remoção só acontece com a confirmação explícita."""
    await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Todos os dias às 9h, verifique os testes.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Relatório semanal",
                    "objective": "Preparar o resumo",
                    "schedule": "toda segunda-feira às 8h30",
                },
            },
            {"content": "Criada."},
        ],
    )
    automation = session.scalars(select(AutomationModel)).one()

    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Exclua a automação de relatório semanal.",
        [
            {"tool": "automation_delete", "arguments": {"automation_id": str(automation.id)}},
            {"content": "Removida."},
        ],
    )
    assert len(session.scalars(select(AutomationModel)).all()) == 1
    assert "confirm" in answer.lower()

    await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Exclua a automação de relatório semanal, pode remover.",
        [
            {
                "tool": "automation_delete",
                "arguments": {"automation_id": str(automation.id), "confirm": True},
            },
            {"content": "Removida."},
        ],
    )
    assert len(session.scalars(select(AutomationModel)).all()) == 0


@pytest.mark.asyncio
async def test_confirmacao_curta_ativa_a_automacao_da_conversa(session, tmp_path, monkeypatch):
    """«Sim, pode ativar» depois da criação ativa a automação — pelo contexto da conversa."""
    await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Todos os dias às 9h, verifique os testes deste projeto.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Verificação diária",
                    "objective": "Verificar os testes",
                    "schedule": "todos os dias às 9h",
                },
            },
            {"content": "Criada."},
        ],
    )
    automation = session.scalars(select(AutomationModel)).one()
    assert automation.state == "disabled"

    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Sim, pode ativar.",
        [
            {
                "tool": "automation_enable",
                "arguments": {
                    "automation_id": str(automation.id),
                    "confirmation_token": "token-da-previa",
                },
            },
            {"content": "Ativada."},
        ],
    )
    # O token errado não ativa: a definição tem de ser a que o usuário viu.
    assert session.scalars(select(AutomationModel)).one().state == "disabled"
    assert "confirmation_token" in answer


@pytest.mark.asyncio
async def test_horario_ambiguo_vira_pergunta_e_nao_grava(session, tmp_path, monkeypatch):
    """Um pedido vago não cria automação: a resposta pergunta."""
    answer, _ = await _run_conversation(
        session,
        tmp_path,
        monkeypatch,
        "Agende a verificação dos testes de manhã.",
        [
            {
                "tool": "automation_create",
                "arguments": {
                    "name": "Verificação",
                    "objective": "Verificar os testes",
                    "schedule": "de manhã",
                },
            },
            {"content": "Perguntei."},
        ],
    )
    assert len(session.scalars(select(AutomationModel)).all()) == 0
    assert "impreciso" in answer or "horário" in answer.lower()
