# tests/test_sufficient_context.py — a operação recebe o que precisa: arquivos, contrato, objetivo e dependências
from pathlib import Path

import pytest

from agent.config import Settings
from agent.context.assembler import build_operation_context
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService

PROFILE = ModelProfile(model_id="m", context_limit=16000, input_budget=12000, output_reserve=1024)


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _prompt(session, project, root_path: Path, task) -> tuple[str, list[str]]:
    budget, snap = OperationContextBuilder(session).build_for_task(
        project_id=project.id, root_path=str(root_path), task=task, profile=PROFILE
    )
    return "\n".join(m.content for m in budget.messages), snap.strategy_notes_json or []


def test_operation_sees_the_files_it_must_change(session, tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def soma(a,  b):\n    return a - b\n", encoding="utf-8")
    (tmp_path.parent / "fora.py").write_text("segredo\n", encoding="utf-8")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Corrigir soma",
            objective="Corrija pkg/mod.py; não mexa em ../fora.py nem em nao_existe.py (versão 3.10).",
            metadata={"model_operation": True},
        ),
    )

    text, notes = _prompt(session, project, tmp_path, task)

    assert "## arquivos-alvo" in text
    assert "--- pkg/mod.py ---\ndef soma(a,  b):" in text
    assert "segredo" not in text
    assert "nao_existe.py ---" not in text
    assert "arquivos: pkg/mod.py" in notes


def test_contract_root_goal_and_dependency_results_reach_the_operation(session, tmp_path):
    (tmp_path / "api.py").write_text("ROTAS = []\n", encoding="utf-8")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Pedido", objective="Criar a API de pedidos com testes"))
    read = tasks.create_task(
        project.id, TaskCreate(title="Ler rotas", objective="ler", parent_id=root.id, metadata={"tool": "read_file"})
    )
    read.consolidated_result_json = {"tool": "read_file", "result": {"success": True, "content": "ROTAS = []"}}
    change = tasks.create_task(
        project.id,
        TaskCreate(title="Adicionar rota", objective="Adicione a rota", parent_id=root.id, metadata={"model_operation": True}),
    )
    tasks.add_dependency(change.id, TaskDependencyCreate(depends_on_task_id=read.id))
    ContractService(session).upsert(
        change.id,
        outputs={"files": ["api.py"], "rota": "/pedidos"},
        invariants=["não remover rotas existentes"],
    )
    session.flush()

    text, _ = _prompt(session, project, tmp_path, change)

    assert "## contrato" in text and "não remover rotas existentes" in text and "/pedidos" in text
    assert "--- api.py ---\nROTAS = []" in text
    assert "## objetivo-global\nCriar a API de pedidos com testes" in text
    assert "## resultados-dependências\n- Ler rotas (PENDING): ROTAS = []" in text


def test_compaction_never_alters_target_files():
    code = "x  =  1\n\n\n\ny = 2\n"
    result = build_operation_context(
        PROFILE,
        global_rules="r",
        project_rules="p",
        objective="obj   com   espaços",
        technical="t",
        acceptance="a",
        tools_summary="f",
        output_format="o",
        target_files=code,
        compact=True,
    )
    body = result.messages[1].content
    assert code.strip() in body
    assert "obj com espaços" in body
