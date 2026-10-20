# tests/test_recovery_and_reporting.py — falhas diagnosticadas, reladas honestas
"""Regressões da recuperação de falhas e do relatório final.

1. O replanejamento cancela as etapas pendentes e as substitui: sem a marcação, a consolidação
   entende "trabalho não feito" e bloqueia o pai mesmo com o plano novo já concluído.
2. Rodar a suíte de testes e ver reprovar é **resultado**, não ferramenta quebrada: repetir a
   mesma chamada devolve a mesma falha.
3. A resposta final carrega um rodapé determinístico com o que foi verificado: uma resposta
   que afirma sucesso em silêncio, com a suíte reprovando, é conclusão falsa.
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.closing import verification_footer
from agent.orchestrator.replan import replan_parent
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _project(session, tmp_path):
    return ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))


def test_etapa_cancelada_pelo_replanejamento_e_marcada_como_substituida(session, tmp_path):
    project = _project(session, tmp_path)
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    root.status = TaskStatus.RUNNING.value
    pending = tasks.create_task(
        project.id, TaskCreate(title="Etapa pendente", objective="fazer", parent_id=root.id)
    )
    bloqueada = tasks.create_task(
        project.id, TaskCreate(title="Etapa bloqueada", objective="fazer", parent_id=root.id)
    )
    bloqueada.status = TaskStatus.BLOCKED.value
    session.flush()

    replan_parent(session, root)

    for etapa in (pending, bloqueada):
        refreshed = TaskService(session).get_task(etapa.id)
        assert refreshed.status == TaskStatus.CANCELLED.value
        assert (refreshed.metadata_json or {}).get("superseded_by_replan") is True


def test_suica_de_testes_reprovando_e_resultado_e_nao_falha_de_ferramenta():
    from agent.orchestrator.runner import _is_informative_test_result

    reprovou = {"success": False, "exit_code": 1, "stdout": "1 failed, 4 passed"}
    ferramenta_quebrada = {"success": False, "error": "executável indisponível: pytest"}

    assert _is_informative_test_result("run_pytest", reprovou) is True
    assert _is_informative_test_result("run_pytest", ferramenta_quebrada) is False
    assert _is_informative_test_result("run_command", reprovou) is False
    assert _is_informative_test_result("run_pytest", {"success": True}) is False


def test_rodape_da_resposta_final_relata_a_reprovacao(session, tmp_path):
    """O texto do modelo é conciso por desenho; quem lê precisa do veredito das verificações."""
    from agent.persistence.models import EvidenceModel

    project = _project(session, tmp_path)
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    etapa = tasks.create_task(
        project.id, TaskCreate(title="Rodar testes", objective="rodar", parent_id=root.id)
    )
    session.flush()
    session.add(
        EvidenceModel(
            task_id=etapa.id,
            verifier="pytest",
            passed=False,
            summary="1 failed, 4 passed",
        )
    )
    session.flush()

    footer = verification_footer(session, root)

    assert "Verificações executadas" in footer
    assert "reprovou" in footer
    assert "pytest" in footer


def test_rodape_relata_apenas_o_que_passou(session, tmp_path):
    from agent.persistence.models import EvidenceModel

    project = _project(session, tmp_path)
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    etapa = tasks.create_task(
        project.id, TaskCreate(title="Conferir", objective="conferir", parent_id=root.id)
    )
    session.flush()
    session.add(
        EvidenceModel(task_id=etapa.id, verifier="file_contains", passed=True, summary="trecho encontrado")
    )
    session.flush()

    footer = verification_footer(session, root)

    assert "passou" in footer
    assert "reprovou" not in footer


def test_sem_verificacao_nao_ha_rodape(session, tmp_path):
    project = _project(session, tmp_path)
    root = TaskService(session).create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    session.flush()

    assert verification_footer(session, root) == ""


def test_requisito_com_evidencia_nao_espera_etapa_de_apoio_pendente(session, tmp_path):
    """Uma etapa de apoio ainda pendente não invalida a prova: o requisito já tem evidência."""
    from agent.orchestrator.requirements import ensure_requirements, requirement_status
    from agent.persistence.models import EvidenceModel

    project = _project(session, tmp_path)
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="Criar a.py"))
    root.status = TaskStatus.PLANNING.value
    ensure_requirements(session, root)
    prova = tasks.create_task(
        project.id,
        TaskCreate(
            title="Fazer",
            objective="fazer",
            parent_id=root.id,
            metadata={"covers": ["R1"], "verification": {"type": "file_contains", "path": "a.py", "contains": "x"}},
        ),
    )
    apoio = tasks.create_task(
        project.id,
        TaskCreate(title="Apoio", objective="apoio", parent_id=root.id, metadata={"covers": ["R1"]}),
    )
    session.flush()
    prova.status = TaskStatus.COMPLETED.value
    session.add(EvidenceModel(task_id=prova.id, verifier="file_contains", passed=True, summary="ok"))
    session.flush()

    status = requirement_status(session, root)[0]

    assert status["status"] == "satisfied"
    assert apoio.status == TaskStatus.PENDING.value
