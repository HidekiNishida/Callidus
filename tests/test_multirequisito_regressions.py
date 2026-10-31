"""
Arquivo: tests/test_multirequisito_regressions.py
Nome: test_multirequisito_regressions.py
Propósito: travar as falhas que o modelo pequeno (qwen3:8b, qwen3-vl:8b) expôs no cenário de dois arquivos e dois requisitos.
Responsabilidade: camada de testes — prova de requisito pelo arquivo certo, plano com etapa duplicada e edição com trecho antigo vazio.
Componentes: janela que acompanha a reserva de saída ampliada, arquivos citados no requisito, evidência de outro arquivo que não prova o requisito, evidência do projeto inteiro que continua valendo, duplicata religada à original, acréscimo do edit_file.
Dependências: agent.orchestrator (requirements, plan_validation, decomposition), agent.services, agent.persistence, agent.tools, agent.verification.fingerprint, pytest.
Observações: banco SQLite e projeto temporários por teste; nenhum modelo é chamado.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.context.budget import assemble_messages, fit_window
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.decomposition import (
    DecompositionResult,
    SubTaskSpec,
    apply_decomposition,
)
from agent.orchestrator.plan_validation import active_children, validate_and_repair
from agent.orchestrator.requirements import (
    ensure_requirements,
    named_files,
    requirement_status,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, TaskDependencyModel
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.diffing import append_block
from agent.tools.registry import ToolContext, build_default_registry
from agent.verification.fingerprint import snapshot

OBJETIVO = "Pedido:\n- em a.py, crie a função soma(a, b) que retorna a mais b\n- em b.py, crie a função sub(a, b) que retorna a menos b"


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _projeto(session, tmp_path: Path):
    """Projeto com a.py e b.py quase vazios e a raiz do pedido de dois requisitos."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("# vazio\n", encoding="utf-8")
    (ws / "b.py").write_text("# vazio\n", encoding="utf-8")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(ws)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="multirequisito", objective=OBJETIVO))
    ensure_requirements(session, root)
    return ws, project, root


def _evidencia(session, task, ws: Path, path: str) -> None:
    """Grava uma evidência aprovada e atual de `file_contains` sobre `path`."""
    spec = {"type": "file_contains", "path": path, "contains": "def"}
    session.add(
        EvidenceModel(
            task_id=task.id,
            verifier="file_contains",
            passed=True,
            summary=f"trecho encontrado em {path}",
            detail_json={"artifacts": snapshot(str(ws), spec)},
        )
    )
    session.flush()


def test_named_files_reads_paths_and_ignores_abbreviations():
    """O requisito cita arquivo pelo nome; abreviação com ponto não vira arquivo."""
    assert named_files("em b.py, crie a função sub(a, b)") == {"b.py"}
    assert named_files("corrija src/pkg/app.py e o README.md") == {"src/pkg/app.py", "readme.md"}
    assert named_files("retorna a mais b. Depois, e.g. some") == set()


def test_evidence_of_a_py_does_not_prove_the_b_py_requirement(session, tmp_path):
    """Regressão: com cobertura implícita, a evidência de a.py "provava" R1 e R2 e o run concluía sem b.py."""
    ws, project, root = _projeto(session, tmp_path)
    (ws / "a.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    etapa = TaskService(session).create_task(
        project.id, TaskCreate(title="Escrever soma", objective="soma em a.py", parent_id=root.id)
    )
    etapa.status = TaskStatus.COMPLETED.value
    _evidencia(session, etapa, ws, "a.py")

    status = {r["id"]: r["status"] for r in requirement_status(session, root)}

    assert status["R1"] == "satisfied"
    assert status["R2"] != "satisfied"


def test_evidence_of_each_file_proves_each_requirement(session, tmp_path):
    """Com a evidência de cada arquivo, os dois requisitos ficam provados."""
    ws, project, root = _projeto(session, tmp_path)
    (ws / "a.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "b.py").write_text("def sub(a, b):\n    return a - b\n", encoding="utf-8")
    etapa = TaskService(session).create_task(
        project.id, TaskCreate(title="Escrever", objective="as duas funções", parent_id=root.id)
    )
    etapa.status = TaskStatus.COMPLETED.value
    _evidencia(session, etapa, ws, "a.py")
    _evidencia(session, etapa, ws, "b.py")

    assert {r["status"] for r in requirement_status(session, root)} == {"satisfied"}


def test_whole_project_evidence_still_counts_for_named_files(session, tmp_path):
    """Verificação do projeto inteiro (pytest na raiz) continua valendo para requisito que cita arquivo."""
    ws, project, root = _projeto(session, tmp_path)
    etapa = TaskService(session).create_task(
        project.id, TaskCreate(title="Testes", objective="rodar a suíte", parent_id=root.id)
    )
    etapa.status = TaskStatus.COMPLETED.value
    session.add(
        EvidenceModel(
            task_id=etapa.id,
            verifier="pytest",
            passed=True,
            summary="pytest passou",
            detail_json={"artifacts": snapshot(str(ws), {"type": "pytest", "path": "."})},
        )
    )
    session.flush()

    assert {r["status"] for r in requirement_status(session, root)} == {"satisfied"}


def test_duplicate_step_is_cancelled_and_dependents_follow_the_original(session, tmp_path):
    """Regressão: a duplicata cancelada deixava a resposta final dependendo de etapa cancelada e o plano
    inteiro era declarado inválido; o run parava no primeiro passo."""
    ws, project, root = _projeto(session, tmp_path)
    verificar = {"tool": "list_dir", "tool_args": {"path": "."}}
    plano = DecompositionResult(
        subtasks=[
            SubTaskSpec(title="Listar", objective="ver o projeto", metadata={"tool": "list_dir", "tool_args": {"path": "."}}),
            SubTaskSpec(
                title="Criar soma",
                objective="soma em a.py",
                metadata={"tool": "edit_file", "tool_args": {"path": "a.py", "old_string": "", "new_string": "def soma(a, b):\n    return a + b"}},
                depends_on_indices=[0],
            ),
            SubTaskSpec(title="Verificar arquivos", objective="conferir a.py e b.py", metadata=verificar, depends_on_indices=[1]),
            SubTaskSpec(title="Verificar arquivos", objective="conferir a.py e b.py", metadata=verificar, depends_on_indices=[1]),
            SubTaskSpec(
                title="Resposta final ao usuário",
                objective="resumir",
                metadata={"model_operation": True, "final_answer": True},
                depends_on_indices=[2, 3],
            ),
        ]
    )
    apply_decomposition(session, project.id, root.id, plano)
    session.flush()

    result = validate_and_repair(session, root, project_root=str(ws), run_config={}, max_tasks=None, run_id=None)

    assert result.runnable, result.issues
    kids = active_children(session, root.id)
    cancelados = [k for k in kids if k.status == TaskStatus.CANCELLED.value]
    assert [k.title for k in cancelados] == ["Verificar arquivos"]
    final = next(k for k in kids if (k.metadata_json or {}).get("final_answer"))
    deps = session.query(TaskDependencyModel).filter(TaskDependencyModel.task_id == final.id).all()
    alvos = {d.depends_on_task_id for d in deps}
    assert cancelados[0].id not in alvos
    assert any(k.title == "Verificar arquivos" and k.status != TaskStatus.CANCELLED.value and k.id in alvos for k in kids)


def test_append_block_keeps_content_and_separates_lines():
    """O acréscimo preserva o conteúdo e separa com quebra de linha."""
    assert append_block("# vazio\n", "def f():\n    return 1") == "# vazio\ndef f():\n    return 1\n"
    assert append_block("x = 1", "y = 2\n") == "x = 1\ny = 2\n"
    assert append_block("", "z = 3") == "z = 3\n"


@pytest.mark.asyncio
async def test_edit_file_with_empty_old_string_appends(tmp_path):
    """Regressão: `old_string` vazio falhava ("old_string vazio") e o modelo repetia a mesma chamada."""
    (tmp_path / "a.py").write_text("# vazio\n", encoding="utf-8")
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))

    done = await reg.execute("edit_file", ctx, {"path": "a.py", "old_string": "", "new_string": "def soma(a, b):\n    return a + b"})

    assert done["success"] and done["appended"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "# vazio\ndef soma(a, b):\n    return a + b\n"

    missing = await reg.execute("edit_file", ctx, {"path": "novo.py", "old_string": "", "new_string": "x = 1"})
    assert not missing["success"] and "write_file" in missing["error"]
    assert not (tmp_path / "novo.py").exists()


def test_window_grows_with_the_widened_output_reserve():
    """Regressão (qwen3-vl:8b): três cortes seguidos dobravam a reserva até 8 192 numa janela de 8 192;
    o orçamento de entrada ficava negativo e o run quebrava com ValueError."""
    from agent.context.budget import ContextComponent
    from agent.providers.base import ModelProfile

    profile = ModelProfile(model_id="qwen3-vl:8b", context_limit=8192, input_budget=6000, output_reserve=8192)
    fitted = fit_window(profile)

    assert fitted.context_limit >= 6000 + 8192 + 256
    assert fitted.context_limit % 4096 == 0 and fitted.context_limit <= 32768
    result = assemble_messages(fitted, [ContextComponent(name="objetivo", text="crie sub em b.py", required=True, priority=10)])
    assert result.messages

    pequeno = ModelProfile(model_id="qwen3:8b", context_limit=8192, input_budget=6000, output_reserve=1024)
    assert fit_window(pequeno) is pequeno


@pytest.mark.asyncio
async def test_pytest_without_tests_in_a_python_project_checks_syntax(tmp_path):
    """Regressão (qwen3-vl:8b): projeto Python sem testes reprovava o pytest para sempre ("no tests ran")
    e o run replanejava até o limite de passos. Agora vale a sintaxe dos .py."""
    from agent.verification.runner import run_verification

    (tmp_path / "a.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def sub(a, b):\n    return a - b\n", encoding="utf-8")
    ok = await run_verification(project_root=str(tmp_path), spec={"type": "pytest", "path": "."}, approved=True)
    assert ok.passed is True and "sintaxe" in ok.summary

    (tmp_path / "b.py").write_text("def sub(a, b):\n    return a -\n", encoding="utf-8")
    bad = await run_verification(project_root=str(tmp_path), spec={"type": "pytest", "path": "."}, approved=True)
    assert bad.passed is False and "b.py" in bad.summary


def test_write_payloads_from_several_objects_and_wrapped_calls():
    """Regressão (qwen3-vl:8b sem raciocínio): vários objetos seguidos davam "Extra data" e a escrita
    embrulhada em chamada dava "faltam campos: path"."""
    from agent.util.json_parse import pick_write_payload, write_payloads

    text = (
        '{"name": "read_file", "arguments": {"path": "a.py"}}\n'
        '{"name": "write_file", "arguments": {"path": "a.py", "content": "def soma(a, b):\\n    return a + b"}}\n'
        '{"name": "edit_file", "arguments": {"path": "b.py", "old_string": "", "new_string": "def sub(a, b):\\n    return a - b"}}\n'
    )
    payloads = write_payloads(text)
    assert [p["path"] for p in payloads] == ["a.py", "b.py"]
    assert pick_write_payload(payloads, "Criar sub em b.py")["new_string"].startswith("def sub")
    assert pick_write_payload(payloads, "Criar a função") is None
    assert pick_write_payload(write_payloads('{"path": "a.py", "content": "x"}\n{"path": "a.py", "content": "y"}'), "")["content"] == "y"
