"""
Arquivo: tests/test_ucg_agent.py
Nome: test_ucg_agent.py
Propósito: Verificar o Agent Graph — perfis de agente, seleção adaptativa por competência
e handoff estruturado com contexto mínimo.
Responsabilidade: camada de testes — integração do Agent Graph com a tabela `agents`
existente.
Componentes: AgentProfile, AgentSelection, AgentHandoff, AgentGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.agent,
agent.persistence.database, agent.services.project_service.
Observações: banco temporário em tmp_path; não grava dados de negócio.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.ucg.agent import (
    AgentGraphService,
    AgentHandoff,
    AgentProfile,
    AgentSelection,
)
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AgentModel
from agent.services.project_service import ProjectService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


@pytest.fixture
def project(session, tmp_path: Path):
    """Cria um projeto com agentes de diferentes papéis e competências."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="agent-graph", root_path=str(tmp_path / "root"))
    )
    now = None  # criado automaticamente pelo modelo
    agents = [
        AgentModel(
            project_id=project.id,
            role="reviewer",
            permissions_json=["fs.read", "fs.write"],
            status="idle",
            depth=0,
            metadata_json={
                "competencies": ["code_review", "testing", "quality"],
                "limitations": ["sem interface gráfica"],
                "compatible_models": ["qwen3:8b", "llama3.2"],
                "recommended_context": 4000,
                "estimated_cost": "baixo",
                "availability": 1.0,
                "reliability": 0.95,
                "suitable_task_kinds": ["operation"],
            },
        ),
        AgentModel(
            project_id=project.id,
            role="specialist",
            permissions_json=["fs.read", "mcp:playwright"],
            status="busy",
            depth=0,
            metadata_json={
                "competencies": ["frontend", "ui", "browser"],
                "limitations": ["não roda em linha de comando"],
                "compatible_models": ["qwen3:8b"],
                "recommended_context": 8000,
                "estimated_cost": "alto",
                "availability": 0.0,
                "reliability": 0.9,
                "suitable_task_kinds": ["subsystem"],
            },
        ),
        AgentModel(
            project_id=project.id,
            role="worker",
            permissions_json=["fs.read"],
            status="idle",
            depth=1,
            metadata_json={
                "competencies": ["edicao", "leitura"],
                "limitations": [],
                "compatible_models": ["llama3.2"],
                "recommended_context": 3000,
                "estimated_cost": "baixo",
                "availability": 1.0,
                "reliability": 0.8,
                "suitable_task_kinds": ["operation"],
            },
        ),
    ]
    for agent in agents:
        session.add(agent)
    session.flush()
    return project


def test_agent_profile_to_graph_node_ref():
    """AgentProfile converte para GraphNodeRef do domínio agent."""
    profile = AgentProfile(
        agent_id="agent-1",
        role="reviewer",
        competencies=["code_review", "testing"],
        recommended_context=4000,
        estimated_cost="baixo",
        availability=1.0,
        reliability=0.95,
        project_id=str(uuid4()),
    )
    ref = profile.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.AGENT
    assert ref.domain == GraphDomain.AGENT
    assert ref.source_system == "agent"
    assert ref.source_id == "agent-1"
    assert ref.metadata["role"] == "reviewer"
    assert ref.metadata["estimated_cost"] == "baixo"
    assert profile.is_available is True


def test_agent_profile_not_available_when_busy():
    """Agente com status busy não está disponível."""
    profile = AgentProfile(
        agent_id="agent-2",
        role="specialist",
        status="busy",
        availability=0.0,
    )
    assert profile.is_available is False


def test_agent_graph_discover_agents(session, project):
    """Serviço descobre agentes disponíveis por competência."""
    proj = project
    service = AgentGraphService(session, proj)
    agents = service.discover_agents(
        required_competencies=["code_review", "testing"],
        suitable_task_kinds=["operation"],
        limit=10,
    )
    assert len(agents) >= 1
    # O agente reviewer está idle e tem as competências.
    reviewer = [a for a in agents if a.role == "reviewer"]
    assert len(reviewer) == 1
    assert reviewer[0].is_available is True
    # O agente specialist está busy, não deve aparecer.
    specialists = [a for a in agents if a.role == "specialist"]
    assert len(specialists) == 0


def test_agent_graph_select_agent(session, project):
    """select_agent devolve o melhor agente para as competências requeridas."""
    proj = project
    service = AgentGraphService(session, proj)
    selection = service.select_agent(
        required_competencies=["code_review", "testing"],
        suitable_task_kinds=["operation"],
        objective="revisar código",
    )
    assert selection is not None
    assert selection.agent.role == "reviewer"
    assert "code_review" in selection.coverage
    assert len(selection.gaps) == 0
    assert selection.cost_estimate == "baixo"


def test_agent_graph_select_agent_with_gaps(session, project):
    """select_agent reporta gaps quando nenhuma competência é coberta."""
    proj = project
    service = AgentGraphService(session, proj)
    selection = service.select_agent(
        required_competencies=["competencia_inexistente"],
        suitable_task_kinds=["operation"],
        objective="tarefa desconhecida",
    )
    assert selection is not None
    assert len(selection.gaps) >= 1
    assert "competencia_inexistente" in selection.gaps


def test_agent_graph_select_agent_none_available(session, project):
    """select_agent devolve None quando não há agente disponível."""
    proj = project
    service = AgentGraphService(session, proj)
    # Desativa todos os agentes marcando como offline/busy.
    from sqlalchemy import select

    rows = list(session.scalars(select(AgentModel).where(AgentModel.project_id == proj.id)))
    for row in rows:
        row.status = "offline"
    session.flush()

    selection = service.select_agent(
        required_competencies=["code_review"],
        suitable_task_kinds=["operation"],
    )
    assert selection is None


def test_agent_graph_build_handoff(session, project):
    """build_handoff monta pacote de contexto mínimo para o agente."""
    proj = project
    service = AgentGraphService(session, proj)
    handoff = service.build_handoff(
        agent_id="agent-1",
        task_id="task-1",
        objective="revisar o código do módulo X",
        essential_information=["O módulo X está em src/agent/"],
        files_and_references=["src/agent/ucg/model.py"],
        preconditions=["Ambiente de testes configurado"],
        expected_output="Relatório de revisão com problemas encontrados",
        acceptance_criteria=["Todos os problemas críticos listados"],
        budget={"max_attempts": 3, "max_tokens": 4000},
        relevant_memories=[{"title": "Revisão anterior", "summary": "Sem problemas críticos"}],
        available_capabilities=[{"id": "tool:read_file", "kind": "tool"}],
    )
    assert handoff.agent_id == "agent-1"
    assert handoff.task_id == "task-1"
    assert "O módulo X está em src/agent/" in handoff.essential_information
    assert "src/agent/ucg/model.py" in handoff.files_and_references
    assert handoff.expected_output == "Relatório de revisão com problemas encontrados"
    assert handoff.budget["max_attempts"] == 3
    assert len(handoff.relevant_memories) == 1
    assert len(handoff.available_capabilities) == 1
    d = handoff.to_dict()
    assert d["agent_id"] == "agent-1"


def test_agent_graph_relate_agent_to_task(session, project):
    """relate_agent_to_task cria aresta EXECUTED_BY entre agente e tarefa."""
    proj = project
    service = AgentGraphService(session, proj)
    agents = service.discover_agents(
        required_competencies=["code_review"], suitable_task_kinds=["operation"], limit=1
    )
    assert len(agents) >= 1
    edge = service.relate_agent_to_task(agents[0], str(uuid4()))
    assert edge is not None
    assert edge.relation == GraphRelationKind.EXECUTED_BY
    assert edge.source.kind == GraphNodeKind.TASK
    assert edge.target.kind == GraphNodeKind.AGENT
