#!/usr/bin/env python3

"""
Arquivo: tests/test_intelligence_graph.py
Nome: test_intelligence_graph.py
Propósito: verificar o grafo cognitivo (topologia, estados, arestas percorridas, aplicação de eventos).
Responsabilidade: camada de testes — comportamento unitário do CognitiveGraph.
Componentes: CognitiveGraph, CognitiveGraphNode, CognitiveGraphEdge, mapeamento de eventos para nós.
Dependências: agent.intelligence.graph, agent.persistence (models, database), sqlalchemy, uuid, pytest.
Observações: banco SQLite em memória por teste; nenhum serviço externo ou rede é usado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from agent.intelligence.graph import CognitiveGraph, ARCHITECTURE_NODES, ARCHITECTURE_EDGES
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, ExecutionRunModel, ProjectModel, TaskModel
from agent.domain.enums import TaskStatus, RunStatus, TaskKind


def setup_function():
    """Cria um banco SQLite em memória novo para o teste e devolve a fábrica de sessões."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    return SessionLocal


def _create_run(session):
    """Cria projeto, run e tarefa raiz."""
    project = ProjectModel(name="test", root_path="/tmp")
    session.add(project)
    session.flush()

    root = TaskModel(
        id=uuid.uuid4(),
        project_id=project.id,
        title="root",
        objective="objetivo",
        kind=TaskKind.OBJECTIVE.value,
        status=TaskStatus.COMPLETED.value,
    )
    session.add(root)
    session.flush()

    run = ExecutionRunModel(
        id=uuid.uuid4(),
        project_id=project.id,
        root_task_id=root.id,
        status=RunStatus.COMPLETED.value,
        config_json={"provider": "ollama", "model_id": "llama3.2"},
    )
    session.add(run)
    session.flush()
    return run


def test_graph_topology():
    """O grafo constrói nós e arestas a partir da topologia da arquitetura real."""
    SessionLocal = setup_function()
    session = SessionLocal()
    graph = CognitiveGraph(session, run_id=None)

    assert len(graph.nodes) == len(ARCHITECTURE_NODES)
    for node_id, info in ARCHITECTURE_NODES.items():
        assert node_id in graph.nodes
        assert graph.nodes[node_id].name == info["name"]
        assert graph.nodes[node_id].type == info["type"]
        assert graph.nodes[node_id].category == info["category"]
        assert graph.nodes[node_id].state == "idle"

    expected_edges = set()
    for source, targets in ARCHITECTURE_EDGES.items():
        for target in targets:
            expected_edges.add((source, target))
    assert set(graph.edges.keys()) == expected_edges
    session.close()


def test_graph_applies_events():
    """Eventos de execução atualizam o estado dos nós e arestas percorridas."""
    SessionLocal = setup_function()
    session = SessionLocal()
    run = _create_run(session)

    # Adiciona eventos à run
    events = [
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="orchestrator.step.started",
            payload_json={"step_index": 1},
        ),
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="provider.inference.started",
            payload_json={"provider": "ollama", "model": "llama3.2", "purpose": "plan"},
        ),
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="provider.inference.completed",
            payload_json={"provider": "ollama", "model": "llama3.2", "duration_ms": 100},
        ),
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="task.state.transitioned",
            payload_json={"from": "PENDING", "to": "RUNNING", "reason": "iniciou execução"},
        ),
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="task.state.transitioned",
            payload_json={"from": "RUNNING", "to": "COMPLETED", "reason": "concluída"},
        ),
    ]
    for ev in events:
        session.add(ev)
    session.flush()

    graph = CognitiveGraph(session, run_id=run.id)

    # O orchestrator deve estar ativo e depois concluído
    orch = graph.nodes["orchestrator"]
    assert orch.state == "active"  # último evento de step.started
    # provider deve estar concluído
    prov = graph.nodes["provider"]
    assert prov.state == "completed"
    # task_manager deve estar concluído (última transição)
    tm = graph.nodes["task_manager"]
    assert tm.state == "completed"

    # Aresta orchestrator -> provider deve estar percorrida
    edge_key = ("orchestrator", "provider")
    assert edge_key in graph.edges
    assert graph.edges[edge_key].traversed is True
    session.close()


def test_graph_node_dict():
    """CognitiveGraphNode.to_dict exporta todos os campos."""
    from agent.intelligence.graph import CognitiveGraphNode

    node = CognitiveGraphNode(
        id="test-node",
        name="Teste",
        type="component",
        category="planejamento",
        state="active",
        activations=3,
        total_duration_ms=500,
        error_count=1,
        last_event_at="2026-01-01T00:00:00+00:00",
        metadata={"key": "value"},
    )
    d = node.to_dict()
    assert d["id"] == "test-node"
    assert d["name"] == "Teste"
    assert d["state"] == "active"
    assert d["activations"] == 3
    assert d["total_duration_ms"] == 500
    assert d["error_count"] == 1
    assert d["metadata"] == {"key": "value"}
    assert d["last_event_at"] == "2026-01-01T00:00:00+00:00"


def test_graph_edge_dict():
    """CognitiveGraphEdge.to_dict exporta todos os campos."""
    from agent.intelligence.graph import CognitiveGraphEdge

    edge = CognitiveGraphEdge(
        source="a",
        target="b",
        traversed=True,
        traversal_count=2,
        last_traversed_at="2026-01-01T00:00:00+00:00",
        failure_count=0,
    )
    d = edge.to_dict()
    assert d["source"] == "a"
    assert d["target"] == "b"
    assert d["traversed"] is True
    assert d["traversal_count"] == 2
    assert d["failure_count"] == 0


def test_graph_get_active_and_failed():
    """get_active_nodes e get_failed_nodes filtram por estado."""
    SessionLocal = setup_function()
    session = SessionLocal()
    run = _create_run(session)

    events = [
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="orchestrator.step.started",
            payload_json={},
        ),
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            event_type="provider.inference.failed",
            payload_json={"provider": "ollama"},
        ),
    ]
    for ev in events:
        session.add(ev)
    session.flush()

    graph = CognitiveGraph(session, run_id=run.id)
    active = graph.get_active_nodes()
    failed = graph.get_failed_nodes()
    assert len(active) >= 1
    assert len(failed) >= 1
    session.close()


def test_graph_to_dict():
    """graph.to_dict exporta schema_version, run_id, nodes, edges e event_history."""
    SessionLocal = setup_function()
    session = SessionLocal()
    graph = CognitiveGraph(session, run_id=None)
    d = graph.to_dict()
    assert "schema_version" in d
    assert d["run_id"] is None
    assert "nodes" in d
    assert "edges" in d
    assert "event_history" in d
    assert len(d["nodes"]) == len(ARCHITECTURE_NODES)
    session.close()
