"""
Arquivo: tests/test_write_integrity.py
Nome: test_write_integrity.py
Propósito: travar a conclusão falsa vista com o qwen3-vl:8b — uma escrita que quebra o projeto não pode passar na verificação implícita.
Responsabilidade: camada de testes — imports locais inexistentes, dependentes quebrados e testes que deixam de passar reprovam a escrita.
Componentes: reprodução do caso da calculadora (main.py trocado por `from calculator import Calculator`), módulo que perde uma função usada por outro, regressão nos testes existentes, escrita íntegra que passa.
Dependências: agent.verification (runner, integrity), pytest.
Observações: projetos temporários em tmp_path; nenhum programa de janela é aberto.
"""

import pytest

from agent.verification.integrity import (
    dependents_problems,
    local_import_problems,
    project_has_tests,
)
from agent.verification.runner import run_verification

CALC = "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    if b == 0:\n        raise ValueError('Division by zero')\n    return a / b\n"


def _projeto(tmp_path, *, com_testes=False):
    """Calculadora mínima: calculator.py com as operações e app.py que as usa."""
    (tmp_path / "calculator.py").write_text(CALC, encoding="utf-8")
    (tmp_path / "app.py").write_text("from calculator import add, divide\n\nprint(add(1, 2))\n", encoding="utf-8")
    if com_testes:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_calc.py").write_text(
            "from calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
        )


def _implicita(path, contains):
    """A verificação que o executor monta depois de uma escrita."""
    return {"type": "file_contains", "path": path, "contains": contains, "implicit": True, "syntax": True}


@pytest.mark.asyncio
async def test_rewrite_that_imports_a_missing_name_is_rejected(tmp_path):
    """Regressão: main.py virou `from calculator import Calculator` (classe inexistente) e passou."""
    _projeto(tmp_path)
    novo = "from calculator import Calculator\n\nif __name__ == '__main__':\n    Calculator().run()\n"
    (tmp_path / "app.py").write_text(novo, encoding="utf-8")

    result = await run_verification(project_root=str(tmp_path), spec=_implicita("app.py", novo[:40]), approved=True)

    assert result.passed is False
    assert "Calculator" in result.summary and "calculator" in result.summary


@pytest.mark.asyncio
async def test_rewrite_that_drops_a_function_used_elsewhere_is_rejected(tmp_path):
    """Reescrever calculator.py sem `divide` quebra app.py, que importa `divide`."""
    _projeto(tmp_path)
    (tmp_path / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    assert dependents_problems(str(tmp_path), "calculator.py")
    result = await run_verification(project_root=str(tmp_path), spec=_implicita("calculator.py", "def add"), approved=True)
    assert result.passed is False and "divide" in result.summary


@pytest.mark.asyncio
async def test_existing_tests_must_keep_passing(tmp_path):
    """Escrita que faz os testes que já existiam reprovarem não passa."""
    _projeto(tmp_path, com_testes=True)
    assert project_has_tests(str(tmp_path))
    errado = CALC.replace("return a + b", "return a - b")
    (tmp_path / "calculator.py").write_text(errado, encoding="utf-8")

    result = await run_verification(project_root=str(tmp_path), spec=_implicita("calculator.py", "def add"), approved=True)
    assert result.passed is False and "testes" in result.summary


@pytest.mark.asyncio
async def test_sound_write_still_passes(tmp_path):
    """Escrita íntegra (imports resolvem, dependentes ok, testes passam) continua aprovada."""
    _projeto(tmp_path, com_testes=True)
    melhor = CALC + "\n\ndef multiply(a, b):\n    return a * b\n"
    (tmp_path / "calculator.py").write_text(melhor, encoding="utf-8")

    assert local_import_problems(str(tmp_path), "app.py") == []
    result = await run_verification(project_root=str(tmp_path), spec=_implicita("calculator.py", "def multiply"), approved=True)
    assert result.passed is True, result.summary


def test_write_journal_restores_the_original_after_a_rejected_write(tmp_path):
    """Regressão: a escrita reprovada ficava no disco e a calculadora que funcionava ficava quebrada."""
    from agent.orchestrator.execution.writes import WriteJournal

    original = "import tkinter as tk\n# janela que funciona\n"
    (tmp_path / "main.py").write_text(original, encoding="utf-8")
    journal = WriteJournal(str(tmp_path))
    journal.remember("write_file", "main.py")
    journal.remember("read_file", "outro.py")  # leitura não entra no diário
    (tmp_path / "main.py").write_text("from calculator import Calculator\n", encoding="utf-8")
    journal.remember("edit_file", str(tmp_path / "main.py"))  # segunda escrita não troca o original
    (tmp_path / "novo.py").write_text("x = 1\n", encoding="utf-8")
    journal.remember("write_file", "novo.py")  # arquivo criado agora: nada a restaurar

    restored = journal.restore()

    assert (tmp_path / "main.py").read_text(encoding="utf-8") == original
    assert len(restored) == 1 and restored[0].endswith("main.py")
    assert (tmp_path / "novo.py").exists()


@pytest.mark.asyncio
async def test_stale_evidence_is_reverified_instead_of_redoing_the_work(tmp_path):
    """Regressão (qwen3-vl:8b): duas etapas editando main.py se desatualizavam uma à outra e se reabriam
    sem fim. A escrita aprovada reverifica a outra contra o disco: continua valendo → evidência atual."""
    from agent.config import Settings
    from agent.domain.enums import TaskStatus
    from agent.domain.schemas import ProjectCreate, TaskCreate
    from agent.orchestrator.consolidation import verification_evidence_ok
    from agent.orchestrator.execution.evidence_refresh import refresh_stale_evidence
    from agent.persistence.database import build_session_factory, init_db
    from agent.persistence.models import EvidenceModel
    from agent.services.project_service import ProjectService
    from agent.services.task_service import TaskService
    from agent.verification.fingerprint import snapshot

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.py").write_text("VISOR = 'escuro'\n", encoding="utf-8")
    session = build_session_factory(init_db(settings=Settings(data_dir=tmp_path / "data")))()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(ws)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="R", objective="melhore"))
    spec = {"type": "file_contains", "path": "main.py", "contains": "VISOR = 'escuro'", "implicit": True, "syntax": True}
    cores = tasks.create_task(project.id, TaskCreate(title="Cores", objective="visor", parent_id=root.id, metadata={"implicit_verification": spec}))
    teclado = tasks.create_task(project.id, TaskCreate(title="Teclado", objective="teclas", parent_id=root.id))
    cores.status = TaskStatus.COMPLETED.value
    session.add(EvidenceModel(task_id=cores.id, verifier="file_contains", passed=True, summary="ok", detail_json={"artifacts": snapshot(str(ws), spec)}))
    session.flush()

    (ws / "main.py").write_text("VISOR = 'escuro'\nTECLAS = '0123456789'\n", encoding="utf-8")
    assert verification_evidence_ok(session, cores) is False  # desatualizada: seria reaberta
    titles = await refresh_stale_evidence(session, task=teclado, path="main.py", root_path=str(ws), approved=True)

    assert titles == ["Cores"]
    assert verification_evidence_ok(session, cores) is True

    (ws / "main.py").write_text("TECLAS = '0123456789'\n", encoding="utf-8")  # a escrita nova apagou a mudança
    await refresh_stale_evidence(session, task=teclado, path="main.py", root_path=str(ws), approved=True)
    assert verification_evidence_ok(session, cores) is False
    session.close()


class _ModeloChamado(Exception):
    """O teste falha se a etapa chamar o modelo quando devia só reconferir."""


def _operacao(session, settings):
    """ModelOperation com um executor mínimo: a verificação é registrada e o modelo não pode ser chamado."""
    from types import SimpleNamespace

    from agent.domain.enums import TaskStatus
    from agent.domain.schemas import TaskStatusUpdate
    from agent.orchestrator.execution.model_operation import ModelOperation
    from agent.services.task_service import TaskService

    tasks = TaskService(session)
    chamadas = []

    def _sem_modelo(*_a, **_k):
        raise _ModeloChamado()

    async def finalize(run, project, task, root, implicit_spec=None):
        chamadas.append(implicit_spec)
        meta = task.metadata_json or {}
        if implicit_spec and not meta.get("verification"):
            task.metadata_json = {**meta, "implicit_verification": implicit_spec}  # como o executor real
        tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
        return {"action": "verified_ok", "task_id": str(task.id)}

    executor = SimpleNamespace(
        runtime=SimpleNamespace(session=session, settings=settings, tasks=tasks, attempts=None, tools=None, provider_factory=_sem_modelo),
        finalize_verification=finalize,
        note_thought=lambda *a, **k: None,
    )
    return ModelOperation(executor), chamadas


@pytest.mark.asyncio
async def test_stale_or_overwritten_step_is_rechecked_without_calling_the_model(tmp_path):
    """Regressão (qwen3-vl:8b): a etapa reaberta só por evidência desatualizada chamava o modelo, que fazia
    uma edição qualquer (`delete` → `deletee`). Agora reconfere; sobrescrita por etapa posterior, refaz uma vez."""
    from types import SimpleNamespace

    from agent.config import Settings
    from agent.domain.enums import TaskStatus
    from agent.domain.schemas import ProjectCreate, TaskCreate
    from agent.persistence.database import build_session_factory, init_db
    from agent.persistence.models import EvidenceModel
    from agent.services.project_service import ProjectService
    from agent.services.task_service import TaskService
    from agent.verification.fingerprint import snapshot

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.py").write_text("VISOR = 'escuro'\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data")
    session = build_session_factory(init_db(settings=settings))()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(ws)))
    tasks = TaskService(session)
    spec = {"type": "file_contains", "path": "main.py", "contains": "VISOR = 'escuro'", "implicit": True, "syntax": True}
    etapa = tasks.create_task(project.id, TaskCreate(title="Cores", objective="visor", metadata={"model_operation": True, "implicit_verification": spec}))
    etapa.status = TaskStatus.RUNNING.value  # como o executor deixa a etapa antes da operação
    session.add(EvidenceModel(task_id=etapa.id, verifier="file_contains", passed=True, summary="ok", detail_json={"artifacts": snapshot(str(ws), spec)}))
    session.flush()
    (ws / "main.py").write_text("VISOR = 'escuro'\nTECLAS = '0123'\n", encoding="utf-8")  # outra etapa mexeu

    operacao, chamadas = _operacao(session, settings)
    run = SimpleNamespace(id=None, config_json={})
    done = await operacao.run(run, project, etapa, {}, str(ws), None)
    assert done["rechecked"] is True and chamadas[-1]["contains"] == ""

    # Sobrescrita: a reconferência disparada por outra etapa reprovou esta.
    etapa.status = TaskStatus.RUNNING.value
    session.add(EvidenceModel(task_id=etapa.id, verifier="file_contains", passed=False, summary="trecho ausente", detail_json={"refreshed_after": "outra"}))
    session.flush()
    with pytest.raises(_ModeloChamado):
        await operacao.run(run, project, etapa, {}, str(ws), None)  # primeira vez: refaz
    etapa.status = TaskStatus.RUNNING.value
    done = await operacao.run(run, project, etapa, {}, str(ws), None)  # segunda: a posterior prevalece
    assert done["rechecked"] is True
    session.close()
