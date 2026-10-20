# tests/test_request_permissions.py — restrições do pedido viram permissões
"""Regressões das permissões derivadas do pedido.

O pedido do usuário é a fonte das restrições. Duas delas viram **permissão de ferramenta**
(não apenas instrução no prompt, que um modelo pequeno ignora):

1. "Não altere nenhum arquivo do projeto" — a etapa é somente leitura.
2. Os testes são a **régua** da medição: alterá-los para a medição passar é trocar o
   critério, não resolver o problema. A régua só muda se o pedido pedir.
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.consolidation import inherits_flag
from agent.orchestrator.strategy import (
    ProfessionalStrategist,
    is_read_only_request,
    looks_like_test_file,
    protects_test_files,
)
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def test_pedido_somente_leitura_e_reconhecido():
    assert is_read_only_request("Execute a suíte e diga o resultado. Não altere nenhum arquivo.") is True
    assert is_read_only_request("Apenas leia os arquivos e me diga o que encontrou") is True
    assert is_read_only_request("Crie em app.py uma função dobro(x)") is False


def test_régua_protegida_só_abre_quando_o_pedido_manda_mexer_nos_testes():
    assert protects_test_files("Corrija o módulo para que a soma funcione") is True
    assert protects_test_files("Crie testes para a função soma") is False
    assert protects_test_files("Atualize a suíte de testes para cobrir o novo caso") is False
    assert protects_test_files("Escreva os testes de regressão") is False


def test_reconhece_arquivo_de_teste():
    assert looks_like_test_file("tests/test_calc.py") is True
    assert looks_like_test_file("test_app.py") is True
    assert looks_like_test_file("src/foo_test.py") is True
    assert looks_like_test_file("web/app.spec.ts") is True
    assert looks_like_test_file("app.py") is False
    assert looks_like_test_file("docs/readme.md") is False


def test_a_marca_desce_com_a_decomposicao(session, tmp_path):
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    root.metadata_json = {"read_only": True, "protect_tests": True}
    child = tasks.create_task(
        project.id, TaskCreate(title="Etapa", objective="fazer", parent_id=root.id)
    )
    session.flush()

    assert inherits_flag(session, child, "read_only") is True
    assert inherits_flag(session, child, "protect_tests") is True


def test_escrita_em_arquivo_de_teste_e_recusada_quando_a_régua_esta_protegida():
    from agent.orchestrator.runner import _write_refusal_reason

    meta = {"protect_tests": True}

    assert _write_refusal_reason(meta, "write_file", "tests/test_calc.py") is not None
    assert _write_refusal_reason(meta, "write_file", "calc.py") is None
    assert _write_refusal_reason(meta, "read_file", "tests/test_calc.py") is None


def test_escrita_e_recusada_em_pedido_somente_leitura():
    from agent.orchestrator.runner import _write_refusal_reason

    meta = {"read_only": True}

    assert _write_refusal_reason(meta, "edit_file", "app.py") is not None
    assert _write_refusal_reason(meta, "write_file", "app.py") is not None
    assert _write_refusal_reason(meta, "read_file", "app.py") is None


def test_a_estrategia_marca_a_raiz():
    strategist = ProfessionalStrategist()

    leitura = strategist.analyze("Rode os testes e diga o resultado. Não altere nenhum arquivo.")
    assert leitura.metadata["read_only"] is True
    assert leitura.metadata["protect_tests"] is True

    mudanca = strategist.analyze("Crie em app.py uma função dobro(x) que retorna x vezes 2.")
    assert mudanca.metadata["read_only"] is False
    assert mudanca.metadata["protect_tests"] is True

    com_testes = strategist.analyze("Crie testes para a função soma em tests/test_soma.py.")
    assert com_testes.metadata["protect_tests"] is False
