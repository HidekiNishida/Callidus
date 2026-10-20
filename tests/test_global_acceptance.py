"""
Arquivo: tests/test_global_acceptance.py
Nome: test_global_acceptance.py
Propósito: Verificar a aceitação global do objetivo a partir dos requisitos e das evidências.
Responsabilidade: camada de testes — relatório de requisitos, reabertura de tarefa sem evidência, bloqueio por requisito pendente, falha de integração e regressão.
Componentes: requisitos comprovados com relatório, tarefa declarada concluída sem evidência, requisito obrigatório pendente, falha de integração e regressão que reabre só a tarefa afetada.
Dependências: agent.orchestrator.global_verify, agent.orchestrator.requirements e agent.verification.fingerprint.
Observações: banco temporário por teste; os arquivos de verificação são criados dentro de tmp_path.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.consolidation import children_of, verification_evidence_ok
from agent.orchestrator.global_verify import (
    ensure_global_verification_task,
    evaluate_global_acceptance,
    reopen_verification_gaps,
    requirements_report,
)
from agent.orchestrator.requirements import ensure_requirements
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, TaskDependencyModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.verification.fingerprint import snapshot


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _spec(name: str) -> dict:
    """Monta a especificação de verificação por conteúdo de arquivo."""
    return {"type": "file_contains", "path": name, "contains": "ok"}


def _evidence(session, task, root: Path, passed: bool = True) -> None:
    """Registra a evidência de uma tarefa a partir da sua especificação de verificação."""
    spec = task.metadata_json["verification"]
    session.add(
        EvidenceModel(
            task_id=task.id,
            verifier=spec["type"],
            passed=passed,
            summary="trecho encontrado" if passed else "falhou",
            detail_json={"state": "aprovado" if passed else "reprovado", "artifacts": snapshot(str(root), spec)},
        )
    )
    session.flush()


def _tree(session, tmp_path: Path, objective: str, leaves: list[dict], *, root_meta=None):
    """Raiz concluída com folhas concluídas e uma resposta final que depende delas."""
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(proj)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective=objective, metadata=root_meta or {}))
    ensure_requirements(session, root)
    made = []
    for leaf in leaves:
        meta = {"covers": leaf["covers"]}
        if leaf.get("file"):
            (proj / leaf["file"]).write_text("ok\n")
            meta["verification"] = _spec(leaf["file"])
        task = tasks.create_task(project.id, TaskCreate(title=leaf["title"], objective=leaf["title"], parent_id=root.id, metadata=meta))
        task.status = TaskStatus.COMPLETED.value
        made.append(task)
    final = tasks.create_task(
        project.id,
        TaskCreate(title="Responder", objective="responder", parent_id=root.id, metadata={"final_answer": True, "covers": []}),
    )
    for task in made:
        tasks.add_dependency(final.id, TaskDependencyCreate(depends_on_task_id=task.id))
    final.status = TaskStatus.COMPLETED.value
    root.status = TaskStatus.COMPLETED.value
    session.flush()
    for task, leaf in zip(made, leaves):
        if leaf.get("file") and leaf.get("evidence", True):
            _evidence(session, task, proj)
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    session.commit()
    return run, root, made, final, proj


def _statuses(session, root) -> dict[str, str]:
    """Devolve o estado de cada requisito da raiz."""
    return {r["id"]: r["status"] for r in requirements_report(session, root)}


OBJ = "- criar a.py\n- criar b.py"


@pytest.mark.asyncio
async def test_every_requirement_with_valid_evidence_completes_with_report(session, tmp_path):
    """Com todos os requisitos comprovados, o run termina e o relatório marca cada um como comprovado com evidência."""
    run, root, _, _, _ = _tree(
        session, tmp_path, OBJ, [{"title": "A", "covers": ["R1"], "file": "a.py"}, {"title": "B", "covers": ["R2"], "file": "b.py"}]
    )

    assert evaluate_global_acceptance(session, root.id) == (True, "ok")
    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "run_completed"
    report = TaskService(session).get_task(root.id).consolidated_result_json["requirements"]
    assert [(r["id"], r["label"]) for r in report] == [("R1", "comprovado"), ("R2", "comprovado")]
    assert all(r["evidence_ids"] for r in report)


@pytest.mark.asyncio
async def test_task_claimed_done_without_evidence_gets_a_localized_fix(session, tmp_path):
    """Tarefa concluída sem evidência gera uma tarefa de correção só do requisito afetado."""
    run, root, (a, b), final, _ = _tree(
        session, tmp_path, OBJ, [{"title": "A", "covers": ["R1"], "file": "a.py"}, {"title": "B", "covers": ["R2"]}]
    )

    ok, reason = evaluate_global_acceptance(session, root.id)
    assert not ok and "R2 (concluído sem evidência suficiente)" in reason and "R1" not in reason

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "requirements_reopen"
    ts = TaskService(session)
    [fix] = [ts.get_task(uuid.UUID(x)) for x in out["created"]]
    assert fix.title == "Comprovar R2" and fix.metadata_json["covers"] == ["R2"]
    assert ts.get_task(a.id).status == TaskStatus.COMPLETED.value and verification_evidence_ok(session, ts.get_task(a.id))
    assert ts.get_task(b.id).status == TaskStatus.COMPLETED.value
    assert ts.get_task(final.id).status == TaskStatus.PLANNING.value
    deps = session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id == final.id)).all()
    assert fix.id in {d.depends_on_task_id for d in deps}
    assert ts.get_task(root.id).status == TaskStatus.PLANNING.value


@pytest.mark.asyncio
async def test_pending_mandatory_requirement_blocks_completion_with_partial_report(session, tmp_path):
    """Requisito obrigatório sem comprovação impede a conclusão e o relatório mostra o que faltou."""
    run, root, _, _, _ = _tree(
        session, tmp_path, OBJ + "\n- criar c.py", [{"title": "A", "covers": ["R1"], "file": "a.py"}, {"title": "B", "covers": ["R2"], "file": "b.py"}]
    )
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    first = await orch.step(run.id)
    assert first["action"] == "requirements_reopen"
    ts = TaskService(session)
    [fix] = [ts.get_task(uuid.UUID(x)) for x in first["created"]]
    assert fix.title == "Atender R3"

    for task in children_of(session, root.id):
        task.status = TaskStatus.COMPLETED.value
    ts.get_task(root.id).status = TaskStatus.COMPLETED.value
    session.commit()

    second = await orch.step(run.id)

    assert second["action"] == "run_stalled"
    report = ts.get_task(root.id).consolidated_result_json
    assert report["achieved"] is False
    labels = {r["id"]: r["label"] for r in report["requirements"]}
    assert labels == {"R1": "comprovado", "R2": "comprovado", "R3": "concluído sem evidência suficiente"}
    assert "### Requisitos" in report["final_answer"] and "R3" in report["final_answer"]
    assert "requisitos obrigatórios sem comprovação: R3" in second["reason"]


def test_integration_failure_keeps_requirements_unaccepted(session, tmp_path):
    """A falha da verificação global bloqueia os requisitos, mesmo com as evidências locais aprovadas."""
    run, root, (a, b), _, proj = _tree(
        session,
        tmp_path,
        OBJ,
        [{"title": "A", "covers": ["R1"], "file": "a.py"}, {"title": "B", "covers": ["R2"], "file": "b.py"}],
        root_meta={"global_verification": _spec("integracao.txt")},
    )
    assert _statuses(session, root) == {"R1": "satisfied", "R2": "satisfied"}

    step = ensure_global_verification_task(session, root.project_id, root)
    session.flush()
    assert step.metadata_json["covers"] == ["R1", "R2"]
    assert _statuses(session, root) == {"R1": "pending", "R2": "pending"}

    (proj / "integracao.txt").write_text("falhou\n")
    _evidence(session, step, proj, passed=False)
    step.status = TaskStatus.BLOCKED.value
    TaskService(session).get_task(root.id).status = TaskStatus.COMPLETED.value
    session.flush()

    assert _statuses(session, root) == {"R1": "blocked", "R2": "blocked"}
    ok, reason = evaluate_global_acceptance(session, root.id)
    assert not ok and "R1 (bloqueado)" in reason
    assert verification_evidence_ok(session, a) and verification_evidence_ok(session, b)


@pytest.mark.asyncio
async def test_regression_reopens_only_the_affected_task(session, tmp_path):
    """A regressão reabre apenas a tarefa cujo arquivo mudou e mantém a outra comprovada."""
    run, root, (a, b), _, proj = _tree(
        session, tmp_path, OBJ, [{"title": "A", "covers": ["R1"], "file": "a.py"}, {"title": "B", "covers": ["R2"], "file": "b.py"}]
    )
    (proj / "a.py").write_text("quebrado sem o trecho\n")

    assert reopen_verification_gaps(session, root.id) == [a.id]
    ts = TaskService(session)
    assert ts.get_task(a.id).status == TaskStatus.VERIFYING.value
    assert ts.get_task(b.id).status == TaskStatus.COMPLETED.value
    assert verification_evidence_ok(session, ts.get_task(b.id))
    assert _statuses(session, root)["R2"] == "satisfied"
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "verify_failed" and out["task_id"] == str(a.id)
    assert ts.get_task(a.id).status == TaskStatus.RETRY_PENDING.value
    assert ts.get_task(b.id).status == TaskStatus.COMPLETED.value
    assert _statuses(session, root) == {"R1": "pending", "R2": "satisfied"}
