"""
Arquivo: tests/test_final_review.py
Nome: test_final_review.py
Propósito: verificar a revisão final de pedidos de conclusão — defeitos de comportamento viram requisitos, uma vez por raiz.
Responsabilidade: camada de testes — quando roda, o que grava no contrato e quando não faz nada.
Componentes: caso da calculadora (botão que sempre divide), revisão sem defeito, revisão que roda uma vez só, pedido que não é de conclusão.
Dependências: agent.orchestrator.final_review, agent.orchestrator.requirements, agent.services, agent.persistence, pytest.
Observações: o modelo é falso (resposta fixa); banco e projeto temporários.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.final_review import final_review, needs_final_review
from agent.orchestrator.requirements import load_requirements
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ChatCompletionResponse, ModelProfile
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


class _Revisor:
    """Modelo falso que devolve a resposta programada e conta as chamadas."""

    name = "fake"
    last_usage = None

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, request):
        self.calls += 1
        return ChatCompletionResponse(content=self.content)


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco temporária."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _calculadora(session, tmp_path, objetivo="termine essa calculadora e abra para eu ver"):
    """Projeto com o defeito real visto com o qwen3-vl:8b: o botão Calculate chama a divisão."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.py").write_text(
        "def calculate(a, b):\n    return a / b  # botão 'Calculate'\n\n\ndef divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    project = ProjectService(session).create_project(ProjectCreate(name="calc", root_path=str(ws)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="calc", objective=objetivo))
    return ws, root


@pytest.mark.asyncio
async def test_defects_become_requirements_once(session, tmp_path):
    """A revisão aponta o botão que sempre divide: vira requisito novo; na segunda vez não roda."""
    ws, root = _calculadora(session, tmp_path)
    revisor = _Revisor('{"defeitos": ["em main.py, faça o botão Calculate usar a operação escolhida em vez de sempre dividir"]}')
    profile = ModelProfile(model_id="qwen3-vl:8b")

    added = await final_review(session, root, provider=revisor, profile=profile, project_root=str(ws))

    assert [r["origin"] for r in added] == ["revisão final"]
    reqs = load_requirements(session, root)
    assert any("Calculate" in r["description"] and r["evidence"] == "change" for r in reqs)
    assert root.metadata_json["final_review"]["defects"] == 1

    again = await final_review(session, root, provider=revisor, profile=profile, project_root=str(ws))
    assert again == [] and revisor.calls == 1


@pytest.mark.asyncio
async def test_no_defect_keeps_the_acceptance(session, tmp_path):
    """Sem defeito real, nada muda (e a raiz fica marcada como revisada)."""
    ws, root = _calculadora(session, tmp_path)
    added = await final_review(session, root, provider=_Revisor('{"defeitos": []}'), profile=ModelProfile(model_id="m"), project_root=str(ws))
    assert added == [] and root.metadata_json["final_review"]["defects"] == 0


def test_only_completion_requests_are_reviewed(session, tmp_path):
    """Pedido que não é de conclusão (nem tem lacunas) não passa pela revisão."""
    _ws, root = _calculadora(session, tmp_path, objetivo="Qual é a capital do Brasil?")
    assert needs_final_review(root, []) is False
    assert needs_final_review(root, [{"origin": "lacuna do pedido"}]) is True
