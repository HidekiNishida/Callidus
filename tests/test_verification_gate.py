"""
Arquivo: tests/test_verification_gate.py
Nome: test_verification_gate.py
Propósito: verificar o portão de verificação independente (VerificationGate).
Responsabilidade: camada de testes — aprovação só com verificação determinística, estágios
executado → validado → requisito satisfeito → concluído, diagnóstico e recuperação com orçamento.
Dependências: agent.verification.gate, agent.verification.recovery, agent.verification.runner,
agent.persistence, agent.services, agent.domain, agent.config, pytest.
Observações: banco SQLite temporário por teste; executor simulado com os atributos que o gate consome.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.failures import classify_verification
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, ExecutionRunModel, TaskModel
from agent.services.attempt_service import AttemptService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.verification.gate import GateResult, VerificationGate, VerificationStage
from agent.verification.recovery import (
    RecoveryDiagnosis,
    diagnose_verification_failure,
    plan_recovery,
    recovery_signature,
)


@pytest.fixture
def session(tmp_path):
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def project(session, tmp_path):
    ps = ProjectService(session)
    return ps.create_project(ProjectCreate(name="demo", root_path=str(tmp_path), description="test"))


@pytest.fixture
def run(session, project):
    ts = TaskService(session)
    task = ts.create_task(
        project.id,
        TaskCreate(title="root", objective="root", kind=TaskKind.OBJECTIVE.value),
    )
    session.commit()
    run = ExecutionRunModel(
        id=task.id,
        project_id=project.id,
        root_task_id=task.id,
        status="active",
        config_json={"approve_risky_tools": False},
    )
    session.add(run)
    session.flush()
    return run


def _make_executor(session, settings, task):
    tasks = TaskService(session)
    attempts = AttemptService(session)
    tools = SimpleNamespace()
    runtime = SimpleNamespace(
        session=session,
        settings=settings,
        tasks=tasks,
        attempts=attempts,
        tools=tools,
        provider_factory=None,
    )
    return SimpleNamespace(runtime=runtime)


def _make_task(
    session, project, parent_id=None, metadata=None, acceptance="login com código", status=TaskStatus.VERIFYING
):
    ts = TaskService(session)
    task = ts.create_task(
        project.id,
        TaskCreate(
            title="tarefa",
            objective="objetivo",
            kind=TaskKind.OPERATION.value,
            parent_id=parent_id,
            acceptance_criteria=acceptance,
            metadata=metadata or {},
        ),
    )
    task.status = status.value
    session.flush()
    return task


# -- estágios ------------------------------------------------------------


def test_verification_stage_values():
    assert VerificationStage.EXECUTED == "executed"
    assert VerificationStage.VALIDATED == "validated"
    assert VerificationStage.REQUIREMENT_SATISFIED == "requirement_satisfied"
    assert VerificationStage.COMPLETED == "completed"


def test_gate_result_model():
    result = GateResult(
        task_id=uuid4(),
        stage="validated",
        passed=True,
        verifier="pytest",
        summary="testes aprovados",
    )
    assert result.passed is True
    assert result.stage == "validated"
    assert result.blocked is False


# -- diagnóstico ---------------------------------------------------------


def test_diagnose_syntax_error():
    diagnosis = diagnose_verification_failure(
        verifier="syntax",
        summary="SyntaxError: invalid syntax em foo.py",
        detail={"syntax_error": "linha 3: invalid syntax"},
    )
    assert diagnosis.cause == "syntax_error"
    assert diagnosis.action == "fix_syntax"
    assert diagnosis.automatic is True


def test_diagnose_timeout():
    diagnosis = diagnose_verification_failure(
        verifier="pytest",
        summary="tempo esgotado ao executar a suíte",
        detail={"stderr": "TimeoutError: timed out"},
    )
    assert diagnosis.cause == "timeout"
    assert diagnosis.action == "retry"
    assert diagnosis.automatic is True


def test_diagnose_missing_artifact():
    diagnosis = diagnose_verification_failure(
        verifier="file_exists",
        summary="arquivo relatorio.pdf não existe",
        detail={},
        spec={"path": "relatorio.pdf"},
    )
    assert diagnosis.cause == "missing_artifact"
    assert diagnosis.action == "regenerate_artifact"
    assert diagnosis.automatic is True


def test_diagnose_environment():
    diagnosis = diagnose_verification_failure(
        verifier="command",
        summary="permission denied to write directory",
        detail={},
    )
    assert diagnosis.cause == "environment"
    assert diagnosis.action == "manual_review"
    assert diagnosis.automatic is False


# -- planejamento de recuperação -----------------------------------------


def test_plan_recovery_respects_limits():
    diagnosis = diagnose_verification_failure(
        verifier="pytest",
        summary="falha de teste",
        detail={},
    )
    plan = plan_recovery(diagnosis, attempt_count=2, max_recoveries=2)
    assert plan["retry"] is False
    assert plan["action"] == "block"


def test_plan_recovery_allows_retry_under_limit():
    diagnosis = diagnose_verification_failure(
        verifier="pytest",
        summary="falha de teste",
        detail={},
    )
    plan = plan_recovery(diagnosis, attempt_count=0, max_recoveries=2)
    assert plan["retry"] is True
    assert plan["action"] == "fix_and_retry"


def test_recovery_signature_ignores_variable_parts():
    d1 = RecoveryDiagnosis(
        cause="syntax_error",
        action="fix_syntax",
        automatic=True,
        guidance="corrigir sintaxe",
        evidence=["linha 100: invalid syntax"],
    )
    d2 = RecoveryDiagnosis(
        cause="syntax_error",
        action="fix_syntax",
        automatic=True,
        guidance="corrigir sintaxe",
        evidence=["linha 999: invalid syntax"],
    )
    s1 = recovery_signature(d1, {"stdout": "arquivo /tmp/foo.py linha 100"})
    s2 = recovery_signature(d2, {"stdout": "arquivo /tmp/foo.py linha 999"})
    assert s1 == s2


# -- classificação de falha ---------------------------------------------


def test_classify_verification_reports_failure():
    failure = classify_verification(
        passed=False,
        summary="teste falhou: assertion error",
        output="AssertionError: esperado 2, obteve 1",
    )
    assert failure is not None
    assert failure.category is not None
    assert failure.cause is not None


def test_classify_verification_none_when_passed():
    failure = classify_verification(
        passed=True,
        summary="tudo ok",
        output="",
    )
    assert failure is None


# -- gate integrado ------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_blocks_when_verification_fails(session, project, run, tmp_path):
    """Verificação declarada que reprova: não conclui, diagnostica e planeja a recuperação."""
    settings = Settings(data_dir=tmp_path)
    task = _make_task(
        session,
        project,
        acceptance="arquivo inexistente",
        metadata={"verification": {"type": "file_exists", "path": "nao_existe.py"}},
    )
    session.commit()

    executor = _make_executor(session, settings, task)
    gate = VerificationGate(executor)

    result = await gate.gate(
        run=run,
        project=project,
        task=task,
        root_path=str(project.root_path),
        config={},
    )

    assert result.passed is False
    assert result.stage == "executed"
    assert result.diagnosis is not None
    assert result.recovery is not None
    assert result.recovery.get("unmet_criterion", "").startswith("file_exists nao_existe.py")
    assert result.evidence_id is not None

    updated = session.get(TaskModel, task.id)
    assert updated.status in {TaskStatus.BLOCKED.value, TaskStatus.RETRY_PENDING.value}
    assert result.blocked == (updated.status == TaskStatus.BLOCKED.value)


@pytest.mark.asyncio
async def test_gate_without_verifier_records_limitation(session, project, run, tmp_path):
    """Sem verificador aplicável, a etapa conclui marcada como não verificada (não como aprovada)."""
    settings = Settings(data_dir=tmp_path)
    task = _make_task(session, project, acceptance="explicar o arquivo")
    session.commit()

    result = await VerificationGate(_make_executor(session, settings, task)).gate(
        run=run, project=project, task=task, root_path=str(project.root_path)
    )

    assert result.passed is False
    assert result.unverified is True
    updated = session.get(TaskModel, task.id)
    assert updated.consolidated_result_json["verified"] is None
    assert updated.consolidated_result_json["verification_absent"]


@pytest.mark.asyncio
async def test_weaker_check_never_approves_failed_verification(session, project, run, tmp_path):
    """Regressão do verde falso: o arquivo existe e a sintaxe é válida, mas o critério declarado
    (o trecho esperado) não está lá — a etapa continua reprovada; o complemento só orienta."""
    import pathlib

    (pathlib.Path(project.root_path) / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path)
    task = _make_task(
        session,
        project,
        metadata={"verification": {"type": "file_contains", "path": "calc.py", "contains": "return a + b"}},
    )
    session.commit()

    result = await VerificationGate(_make_executor(session, settings, task)).gate(
        run=run, project=project, task=task, root_path=str(project.root_path)
    )

    assert result.passed is False
    updated = session.get(TaskModel, task.id)
    assert updated.status != TaskStatus.COMPLETED.value
    evidence = session.get(EvidenceModel, result.evidence_id)
    assert evidence.passed is False
    assert evidence.detail_json["complement"]["passed"] is True
    assert "a reprovação não vem daí" in result.recovery["guidance"]


@pytest.mark.asyncio
async def test_gate_approves_when_verification_passes(session, project, run, tmp_path):
    import pathlib

    (pathlib.Path(project.root_path) / "login.py").write_text("def login():\n    return True\n", encoding="utf-8")
    session.commit()

    settings = Settings(data_dir=tmp_path)
    task = _make_task(
        session,
        project,
        acceptance="login com código",
        metadata={"verification": {"type": "file_exists", "path": "login.py"}},
    )
    session.commit()

    executor = _make_executor(session, settings, task)
    gate = VerificationGate(executor)

    result = await gate.gate(
        run=run,
        project=project,
        task=task,
        root_path=str(project.root_path),
        config={},
    )

    assert result.passed is True
    assert result.stage in {"validated", "requirement_satisfied", "completed"}
    assert result.verifier is not None
    assert result.evidence_id is not None

    updated = session.get(TaskModel, task.id)
    assert updated.status in {TaskStatus.VERIFYING.value, TaskStatus.COMPLETED.value}
