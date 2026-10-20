"""
Arquivo: tests/test_hierarchical_decompose.py
Nome: test_hierarchical_decompose.py
Propósito: Verificar a decomposição em dois níveis, com plano genérico e micro plano.
Responsabilidade: camada de testes — árvore de tarefas com dois níveis de decomposição e profundidade resultante.
Componentes: primeiro nível com três filhos e segundo nível com três netos.
Dependências: agent.orchestrator.decomposition, agent.orchestrator.atomizer e agent.services.task_service.
Observações: banco temporário por teste.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.atomizer import micro_decompose_operation
from agent.orchestrator.consolidation import children_of
from agent.orchestrator.decomposition import GENERIC_TEMPLATE, apply_decomposition
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_two_level_task_tree(session, tmp_path: Path):
    """A decomposição gera três filhos na raiz e três netos no meio, com profundidade de pelo menos dois níveis."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="p", root_path=str(tmp_path))
    )
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Root", objective="Implementar autenticação completa")
    )
    apply_decomposition(session, project.id, root.id, GENERIC_TEMPLATE)
    level1 = children_of(session, root.id)
    assert len(level1) == 3
    mid = level1[1]
    plan = micro_decompose_operation("Definir contrato do serviço de credenciais")
    apply_decomposition(session, project.id, mid.id, plan)
    level2 = children_of(session, mid.id)
    assert len(level2) == 3
    all_tasks = TaskService(session).list_tasks(project.id)
    depths = []
    by_id = {t.id: t for t in all_tasks}
    for t in all_tasks:
        d = 0
        cur = t
        while cur.parent_id and cur.parent_id in by_id:
            d += 1
            cur = by_id[cur.parent_id]
        depths.append(d)
    assert max(depths) >= 2
