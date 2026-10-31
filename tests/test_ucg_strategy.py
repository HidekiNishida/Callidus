"""
Arquivo: tests/test_ucg_strategy.py
Nome: test_ucg_strategy.py
Propósito: Verificar o Strategy Graph — estratégias de resolução, resultados históricos
e aprendizado operacional com seleção adaptativa baseada em evidências.
Responsabilidade: camada de testes — integração do Strategy Graph com os modelos
existentes (`MemoryRecordModel`, `EvidenceModel`).
Componentes: Strategy, StrategyResult, StrategyGraphService.
Dependências: agent.config, agent.domain.schemas, agent.knowledge.ucg.strategy,
agent.persistence.database, agent.services.project_service.
Observações: banco temporário em tmp_path; grava em modelos existentes.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate
from agent.knowledge.ucg.model import (
    GraphDomain,
    GraphNodeKind,
    GraphRelationKind,
)
from agent.knowledge.ucg.strategy import (
    Strategy,
    StrategyGraphService,
    StrategyResult,
    _MIN_CONFIDENCE,
    _MIN_OBSERVATIONS,
)
from agent.persistence.database import build_session_factory, init_db
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
    """Cria um projeto."""
    return ProjectService(session).create_project(
        ProjectCreate(name="strategy", root_path=str(tmp_path / "root"))
    )


def test_strategy_to_graph_node_ref():
    """Strategy converte para GraphNodeRef do domínio strategy."""
    strat = Strategy(
        strategy_id="strat-1",
        name="Recuperação + execução direta",
        task_class="implement_feature",
        conditions=["contexto_limitado", "modelo_pequeno"],
        sequence=["consultar", "planejar", "executar", "verificar"],
        resources=["skill:frontend-audit", "tool:read_file"],
        model="llama3.2",
        agent="worker",
        expected_budget=3000,
        cost="baixo",
        risk="baixo",
        expected_result="Funcionalidade implementada e verificada",
    )
    ref = strat.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.STRATEGY
    assert ref.domain == GraphDomain.STRATEGY
    assert ref.source_system == "strategy"
    assert ref.source_id == "strat-1"
    assert ref.metadata["cost"] == "baixo"
    assert ref.metadata["risk"] == "baixo"


def test_strategy_result_to_graph_node_ref():
    """StrategyResult converte para GraphNodeRef do domínio strategy."""
    res = StrategyResult(
        result_id="res-1",
        strategy_id="strat-1",
        task_class="implement_feature",
        tokens_in=2000,
        tokens_out=1500,
        inferences=3,
        duration_seconds=45.0,
        tools_used=2,
        success=True,
        rework=False,
        failure=False,
        quality=0.9,
        total_cost="baixo",
    )
    ref = res.to_graph_node_ref()
    assert ref.kind == GraphNodeKind.EXECUTION
    assert ref.domain == GraphDomain.STRATEGY
    assert ref.metadata["success"] is True
    assert ref.metadata["quality"] == 0.9


def test_strategy_graph_register_strategy(session, project):
    """register_strategy persiste uma estratégia vinculada ao projeto."""
    proj = project
    service = StrategyGraphService(session)
    strat = service.register_strategy(
        strategy_id="strat-1",
        name="Recuperação + execução direta",
        task_class="implement_feature",
        conditions=["contexto_limitado", "modelo_pequeno"],
        sequence=["consultar", "planejar", "executar", "verificar"],
        resources=["skill:frontend-audit"],
        model="llama3.2",
        agent="worker",
        expected_budget=3000,
        cost="baixo",
        risk="baixo",
        expected_result="Funcionalidade implementada",
        project_id=str(proj.id),
    )
    assert strat.strategy_id == "strat-1"
    assert strat.name == "Recuperação + execução direta"
    assert strat.task_class == "implement_feature"
    assert strat.cost == "baixo"


def test_strategy_graph_record_result(session, project):
    """record_result persiste um resultado histórico de execução."""
    proj = project
    service = StrategyGraphService(session)
    res = service.record_result(
        result_id="res-1",
        strategy_id="strat-1",
        task_class="implement_feature",
        tokens_in=2000,
        tokens_out=1500,
        inferences=3,
        duration_seconds=45.0,
        tools_used=2,
        success=True,
        rework=False,
        failure=False,
        quality=0.9,
        total_cost="baixo",
        project_id=str(proj.id),
    )
    assert res.result_id == "res-1"
    assert res.strategy_id == "strat-1"
    assert res.success is True
    assert res.quality == 0.9


def test_strategy_graph_select_strategy_insufficient_observations(session, project):
    """select_strategy retorna None quando não há observações suficientes."""
    proj = project
    service = StrategyGraphService(session)
    # Registra uma estratégia mas sem resultados suficientes.
    service.register_strategy(
        strategy_id="strat-1",
        name="Estratégia de teste",
        task_class="implement_feature",
        conditions=[],
        sequence=["consultar", "executar"],
        resources=[],
        model="llama3.2",
        agent="worker",
        expected_budget=3000,
        cost="baixo",
        risk="baixo",
        expected_result="Resultado",
        project_id=str(proj.id),
    )
    selected = service.select_strategy(
        task_class="implement_feature",
        conditions=[],
        min_observations=5,
    )
    assert selected is None


def test_strategy_graph_select_strategy_with_evidence(session, project):
    """select_strategy seleciona a melhor estratégia com base em evidências."""
    proj = project
    service = StrategyGraphService(session)

    # Registra duas estratégias.
    service.register_strategy(
        strategy_id="strat-cheap",
        name="Estratégia barata",
        task_class="implement_feature",
        conditions=[],
        sequence=["consultar", "executar"],
        resources=[],
        model="llama3.2",
        agent="worker",
        expected_budget=1000,
        cost="baixo",
        risk="baixo",
        expected_result="Resultado barato",
        project_id=str(proj.id),
    )
    service.register_strategy(
        strategy_id="strat-expensive",
        name="Estratégia cara",
        task_class="implement_feature",
        conditions=[],
        sequence=["consultar", "planejar", "executar", "verificar"],
        resources=["skill:audit"],
        model="qwen3:8b",
        agent="reviewer",
        expected_budget=8000,
        cost="alto",
        risk="medio",
        expected_result="Resultado caro",
        project_id=str(proj.id),
    )

    # Registra 6 resultados para cada estratégia.
    now = datetime.now(UTC)
    for i in range(6):
        service.record_result(
            result_id=f"res-cheap-{i}",
            strategy_id="strat-cheap",
            task_class="implement_feature",
            tokens_in=1000,
            tokens_out=800,
            inferences=2,
            duration_seconds=30.0,
            tools_used=1,
            success=True,
            rework=False,
            failure=False,
            quality=0.85,
            total_cost="baixo",
            project_id=str(proj.id),
            executed_at=now + timedelta(minutes=i),
        )
        service.record_result(
            result_id=f"res-expensive-{i}",
            strategy_id="strat-expensive",
            task_class="implement_feature",
            tokens_in=4000,
            tokens_out=3000,
            inferences=6,
            duration_seconds=120.0,
            tools_used=4,
            success=True,
            rework=False,
            failure=False,
            quality=0.9,
            total_cost="alto",
            project_id=str(proj.id),
            executed_at=now + timedelta(minutes=i),
        )

    selected = service.select_strategy(
        task_class="implement_feature",
        conditions=[],
        min_observations=5,
    )
    assert selected is not None
    # A estratégia barata tem melhor custo e sucesso semelhante, deve ser preferida.
    assert selected.strategy_id == "strat-cheap"


def test_min_observations_and_confidence():
    """_MIN_OBSERVATIONS e _MIN_CONFIDENCE têm valores razoáveis."""
    assert _MIN_OBSERVATIONS > 0
    assert 0.0 < _MIN_CONFIDENCE < 1.0
