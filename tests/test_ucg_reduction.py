"""
Arquivo: tests/test_ucg_reduction.py
Nome: test_ucg_reduction.py
Propósito: Verificar a redução progressiva de contexto — seleção explicável e limitada de
arquivos com base no índice de inspeção, respeitando orçamento e relevância.
Responsabilidade: camada de testes — redução de contexto sem carregar catálogo de arquivos.
Componentes: ProgressiveContextReducer, ContextReduction, FileSelection.
Dependências: agent.memory.inspection, agent.memory.state, agent.knowledge.ucg.reduction,
agent.config, agent.domain.schemas, agent.persistence.database, agent.services.project_service.
Observações: banco e arquivos temporários em tmp_path; não grava dados de negócio.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.memory.inspection import FileInspection, InspectionIndex, record_inspection
from agent.knowledge.ucg.reduction import ProgressiveContextReducer
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


@pytest.fixture
def project(session, tmp_path: Path):
    """Cria um projeto com arquivos de conteúdo controlado."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "relevant.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (root / "irrelevant.py").write_text("# apenas comentários\nx = 2\n", encoding="utf-8")
    (root / "large.py").write_text("# " + "a" * 5000 + "\n", encoding="utf-8")
    project = ProjectService(session).create_project(
        ProjectCreate(name="reduction", root_path=str(root))
    )
    return project, root


def _index_files(session, project, root, objective: str) -> InspectionIndex:
    """Inspeciona os arquivos do projeto e grava o índice nos metadados da tarefa."""
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="t", objective=objective)
    )
    index = InspectionIndex()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8")
        record_inspection(index, rel, str(root), content, objective=objective)
    task.metadata_json = index.to_metadata_extended()
    session.flush()
    return task, index


def test_reduce_seleciona_arquivos_relevantes(session, project):
    """Arquivos relevantes são selecionados; irrelevantes são excluídos com motivo."""
    project, root = project
    task, _ = _index_files(session, project, root, "hello")
    reducer = ProgressiveContextReducer(session)
    reduction = reducer.reduce(
        task.id, "hello", root_path=str(root), budget_bytes=12000, max_files=12
    )

    selected_paths = {s.path for s in reduction.selected}
    excluded_paths = {s.path for s in reduction.excluded}
    assert "relevant.py" in selected_paths
    assert "irrelevant.py" in excluded_paths
    assert reduction.budget_respected is True
    assert reduction.total_bytes > 0
    assert reduction.estimated_tokens > 0
    assert "selecionado(s)" in reduction.explanation


def test_reduce_respeita_orcamento(session, project):
    """Quando o orçamento é pequeno, arquivos são excluídos com motivo de orçamento."""
    project, root = project
    task, _ = _index_files(session, project, root, "hello")
    reducer = ProgressiveContextReducer(session)
    reduction = reducer.reduce(
        task.id, "hello", root_path=str(root), budget_bytes=100, max_files=12
    )

    # O arquivo grande não cabe no orçamento mínimo.
    large_excluded = [s for s in reduction.excluded if s.path == "large.py"]
    assert any("orçamento" in s.reason for s in large_excluded) or len(reduction.selected) <= 1


def test_reduce_deteta_arquivo_estale(session, project):
    """Arquivo que mudou desde a inspeção é excluído como estale."""
    project, root = project
    task, _ = _index_files(session, project, root, "hello")
    # Altera o conteúdo de relevant.py após a inspeção.
    (root / "relevant.py").write_text("def alterado():\n    return 99\n", encoding="utf-8")
    reducer = ProgressiveContextReducer(session)
    reduction = reducer.reduce(
        task.id, "hello", root_path=str(root), budget_bytes=12000, max_files=12
    )
    stale = [s for s in reduction.excluded if s.path == "relevant.py"]
    assert stale and stale[0].stale is True
    assert any("estale" in s.reason for s in stale)


def test_reduce_tarefa_inexistente_retorna_vazio(session):
    """Tarefa inexistente devolve redução vazia sem falhar."""
    reducer = ProgressiveContextReducer(session)
    from uuid import uuid4

    reduction = reducer.reduce(uuid4(), "x", root_path=".", budget_bytes=12000, max_files=12)
    assert reduction.selected == []
    assert reduction.excluded == []
    assert "não encontrada" in reduction.explanation
