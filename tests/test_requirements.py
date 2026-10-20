"""
Arquivo: tests/test_requirements.py
Nome: test_requirements.py
Propósito: verificar os requisitos rastreáveis: derivação, identificadores estáveis, cobertura herdada e estado por evidência.
Responsabilidade: camada de testes — comportamento da derivação e do estado dos requisitos de uma tarefa.
Componentes: derivação a partir do objetivo e dos critérios, persistência única com identificadores estáveis, herança de cobertura e partes, estado por cobertura e evidência, resposta final que não satisfaz requisito de mudança, resposta que satisfaz requisito de resposta e aplicabilidade não obrigatória.
Dependências: agent.orchestrator (requirements, decomposition), agent.services (contract, project, task), agent.persistence (database, models), pytest.
Observações: banco SQLite temporário por teste; a cobertura de evidência é criada direto no banco, sem executar o trabalho.

requisitos rastreáveis: derivação, ids estáveis, cobertura herdada/parcial, estado por evidência
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.decomposition import requirements_block
from agent.orchestrator.requirements import (
    derive_requirements,
    effective_covers,
    ensure_requirements,
    normalize_covers,
    requirement_status,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def test_enumerated_objective_and_criteria_become_requirements():
    """Objetivo enumerado e critérios de aceite viram requisitos com origem e evidência declaradas."""
    reqs = derive_requirements(
        "Sistema de pedidos:\n- criar a API de pedidos\n- calcular frete\n",
        "1. pytest passa\n",
    )
    assert [r["id"] for r in reqs] == ["R1", "R2", "R3"]
    assert reqs[0]["description"] == "criar a API de pedidos"
    assert reqs[2]["origin"] == "critérios de aceite"
    assert all(r["applicability"] == "obrigatório" and r["evidence"] == "change" for r in reqs)

    single = derive_requirements("Que dia é hoje?")
    assert len(single) == 1 and single[0]["evidence"] == "answer"


def test_requirements_are_persisted_once_with_stable_ids(session, tmp_path):
    """Os requisitos são gravados uma única vez e mantêm o identificador mesmo com o objetivo alterado."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="R", objective="- criar a.py\n- criar b.py"))

    first = ensure_requirements(session, root)
    root.objective = "- outra coisa"
    second = ensure_requirements(session, root)

    assert first == second
    assert ContractService(session).get(root.id).acceptance_json["requirements"][1]["description"] == "criar b.py"


def test_covers_inherit_from_parent_and_keep_partial_parts(session, tmp_path):
    """A cobertura é herdada do pai e a parte parcial do requisito é preservada."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="R", objective="- criar a.py\n- criar b.py"))
    ensure_requirements(session, root)
    sub = tasks.create_task(
        project.id,
        TaskCreate(title="S", objective="b", parent_id=root.id, metadata={"covers": [{"req": "R2", "partial": True, "part": "testes"}]}),
    )
    leaf = tasks.create_task(project.id, TaskCreate(title="L", objective="b", parent_id=sub.id))

    assert [c["req"] for c in effective_covers(session, root)] == ["R1", "R2"]
    assert effective_covers(session, leaf) == [{"req": "R2", "partial": True, "part": "testes"}]
    assert normalize_covers(["R1"]) == [{"req": "R1", "partial": False, "part": ""}]
    assert normalize_covers(None) is None

    block = requirements_block([{"id": "R2", "description": "criar b.py", "part": "testes"}])
    assert "R2: criar b.py (parte: testes)" in block and "metadata.covers" in block


def _two_requirement_tree(session, tmp_path):
    """Monta uma árvore com dois requisitos, uma etapa que cobre um deles e a etapa de resposta final."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="R", objective="- criar a.py\n- criar b.py"))
    ensure_requirements(session, root)
    a = tasks.create_task(
        project.id,
        TaskCreate(title="A", objective="a", parent_id=root.id, metadata={"covers": ["R1"], "verification": {"type": "file_contains", "path": "a.py", "contains": "a"}}),
    )
    final = tasks.create_task(
        project.id, TaskCreate(title="Fim", objective="resumo", parent_id=root.id, metadata={"covers": [], "final_answer": True})
    )
    session.flush()
    return root, a, final


def test_status_tracks_coverage_and_evidence(session, tmp_path):
    """O status do requisito acompanha a cobertura e só fica satisfeito com evidência registrada."""
    root, a, final = _two_requirement_tree(session, tmp_path)

    status = {r["id"]: r["status"] for r in requirement_status(session, root)}
    assert status == {"R1": "pending", "R2": "uncovered"}

    a.status = TaskStatus.COMPLETED.value
    session.flush()
    assert requirement_status(session, root)[0]["status"] == "pending"

    session.add(EvidenceModel(task_id=a.id, verifier="file_contains", passed=True, summary="ok"))
    session.flush()
    r1 = requirement_status(session, root)[0]
    assert r1["status"] == "satisfied" and r1["evidence_ids"]


def test_change_requirement_is_not_satisfied_by_the_final_answer_alone(session, tmp_path):
    """Um requisito de mudança não é satisfeito apenas pela resposta final."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="R", objective="Criar o arquivo a.py"))
    ensure_requirements(session, root)
    final = tasks.create_task(
        project.id, TaskCreate(title="Fim", objective="resumo", parent_id=root.id, metadata={"final_answer": True})
    )
    final.status = TaskStatus.COMPLETED.value
    final.consolidated_result_json = {"final_answer": True, "markdown": "Pronto, criei a.py."}
    session.flush()

    assert requirement_status(session, root)[0]["status"] == "unverified"


def test_answer_requirement_accepts_the_delivered_answer(session, tmp_path):
    """Um requisito de resposta é satisfeito pela resposta final entregue."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="R", objective="Que dia é hoje?"))
    ensure_requirements(session, root)
    final = tasks.create_task(
        project.id, TaskCreate(title="Fim", objective="resposta", parent_id=root.id, metadata={"final_answer": True})
    )
    final.status = TaskStatus.COMPLETED.value
    final.consolidated_result_json = {"final_answer": True, "markdown": "Hoje é domingo."}
    session.flush()

    assert requirement_status(session, root)[0]["status"] == "satisfied"


def test_non_mandatory_requirement_keeps_its_applicability(session, tmp_path):
    """Um requisito marcado como não aplicável mantém essa aplicabilidade e seu estado."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="R", objective="x"))
    ContractService(session).upsert(
        root.id,
        acceptance={"requirements": [{"id": "R1", "description": "deploy", "applicability": "não aplicável"}]},
    )
    assert ensure_requirements(session, root)[0]["applicability"] == "não aplicável"
    assert requirement_status(session, root)[0]["status"] == "não_aplicável"
