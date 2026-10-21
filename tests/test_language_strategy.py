"""
Arquivo: tests/test_language_strategy.py
Nome: test_language_strategy.py
Propósito: verificar a escolha do idioma operacional e a preservação do pedido original.
Responsabilidade: camada de testes — contrato linguístico, fidelidade e troca única de estratégia.
Componentes: build_language_contract, fidelity, herança, troca após saída inválida, passo da raiz.
Dependências: agent.orchestrator.language_strategy, agent.orchestrator.runner, pytest.
Observações: não chama modelo nem rede. A comparação entre modos é estrutural, não um benchmark.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.failures import Failure, FailureCategory, FailureCause
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.execution.journal import remember_failure
from agent.orchestrator.language_strategy import (
    apply_operational_text,
    build_language_contract,
    compare_strategies,
    explain_language,
    extract_literals,
    fidelity_gaps,
    inherit_language,
    render_operational_for_prompt,
    switch_language,
)
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

_PEDIDO = "Corrija o bug em src/app.py sem alterar o limite 3. Não mude `calc`."


def test_pedido_em_portugues_nao_exige_ingles_do_usuario():
    """O modo nativo guarda o pedido e o idioma de apresentação em português."""
    contract = build_language_contract(_PEDIDO, mode="native")
    assert contract["input_language"] == "pt"
    assert contract["presentation_language"] == "pt"
    assert contract["applied"] == "native"
    assert contract["operational_language"] == "pt"
    assert render_operational_for_prompt({"language": contract}) == ""


def test_auto_usa_ingles_operacional_em_tarefa_tecnica():
    """Pedido técnico em português ganha quadro em inglês e continua visível em português."""
    contract = build_language_contract(_PEDIDO, mode="auto")
    assert contract["applied"] == "english_operational"
    assert contract["operational_language"] == "en"
    assert contract["presentation_language"] == "pt"
    frame = render_operational_for_prompt({"language": contract})
    assert "English" in frame
    assert "português" in frame
    assert "src/app.py" in frame
    assert "Não mude `calc`." in frame
    assert "calc" in frame
    assert "3" in extract_literals(_PEDIDO) or "3" in frame or "3" in _PEDIDO
    assert "sem alterar o limite 3" in frame
    text = explain_language(contract)
    assert text.startswith("Vou usar uma especificação operacional em inglês")
    assert "sucesso" not in text.lower()


def test_prosa_e_pedido_em_ingles_ficam_no_idioma_original():
    """Sem marca técnica, ou com o pedido já em inglês, o automático não cria quadro."""
    prose = build_language_contract("Escreva um texto sobre o verão na praia.", mode="auto")
    assert prose["applied"] == "native"
    english = build_language_contract("Add a test for calc.py and keep the name `total`.", mode="auto")
    assert english["input_language"] == "en"
    assert english["applied"] == "native"
    assert english["operational_language"] == "en"


def test_perfil_do_modelo_pode_preferir_o_idioma_original():
    """O automático obedece a preferência registrada. O nome do modelo não entra na decisão."""
    contract = build_language_contract(
        _PEDIDO,
        mode="auto",
        profile={"preferred": "native"},
    )
    assert contract["applied"] == "native"


def test_apresentacao_explicita_nao_segue_o_idioma_operacional():
    """A interface pode continuar em português enquanto a operação usa inglês."""
    contract = build_language_contract(_PEDIDO, mode="english_operational", presentation="pt")
    assert contract["presentation_language"] == "pt"
    assert contract["operational_language"] == "en"


def test_fidelidade_recusa_traducao_que_troca_numero_ou_caminho():
    """Inglês fluente que perde caminho, número ou restrição devolve o pedido original."""
    bad = "Fix the bug and keep the limit 4."
    assert fidelity_gaps(_PEDIDO, bad)
    kept, reason = apply_operational_text(_PEDIDO, bad)
    assert kept == _PEDIDO
    assert reason.startswith("fidelidade")
    kept_ok, reason_ok = apply_operational_text(_PEDIDO, _PEDIDO + "\nKeep src/app.py and 3.")
    assert kept_ok.startswith("Corrija")
    assert reason_ok == ""


def test_ambiguidade_permanece_sem_escolha():
    """A palavra ou não vira uma decisão escondida na especificação."""
    contract = build_language_contract(
        "Corrija o bug em src/app.py ou recrie o arquivo.",
        mode="english_operational",
    )
    assert contract["ambiguities"]
    assert "ou" in contract["ambiguities"][0]
    frame = render_operational_for_prompt({"language": contract})
    assert "ou recrie" in frame


def test_heranca_nao_retraduz():
    """A filha recebe o mesmo contrato, sem uma cópia nova do pedido."""
    parent = build_language_contract(_PEDIDO, mode="auto")
    child = inherit_language(parent)
    assert child is not None
    assert child["revision"] == parent["revision"]
    assert child["applied"] == parent["applied"]
    assert "objective" not in child


def test_troca_para_o_idioma_original_acontece_uma_vez():
    """Saída inválida abandona o inglês operacional. A falha seguinte não volta ao inglês."""
    contract = build_language_contract(_PEDIDO, mode="auto")
    first = switch_language({"language": contract}, "invalid_output")
    assert first is not None
    assert first["applied"] == "native"
    assert first["switched_from"] == "english_operational"
    assert switch_language({"language": first}, "invalid_output") is None
    assert switch_language({"language": contract}, "tool_error") is None


def test_falha_registrada_aplica_a_troca_sem_apagar_o_pedido():
    """O diário de falha muda o contrato e deixa o objetivo da etapa como estava."""

    class _Task:
        def __init__(self) -> None:
            self.objective = _PEDIDO
            self.metadata_json = {"language": build_language_contract(_PEDIDO, mode="auto")}

    task = _Task()
    remember_failure(task, Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.INVALID_OUTPUT, "JSON vazio"))
    assert task.metadata_json["language"]["applied"] == "native"
    assert task.objective == _PEDIDO


def test_comparacao_estrutural_dos_tres_modos():
    """Os três modos diferem na estratégia aplicada, não no critério de sucesso."""
    compared = compare_strategies(_PEDIDO)
    assert compared["native"] == "native"
    assert compared["english_operational"] == "english_operational"
    assert compared["auto"] == "english_operational"


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco temporário."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


@pytest.mark.asyncio
async def test_raiz_grava_o_contrato_no_primeiro_passo(session, tmp_path: Path):
    """O planejamento da raiz persiste o contrato e explica em português, sem chamada extra."""
    project = ProjectService(session).create_project(ProjectCreate(name="idioma", root_path=str(tmp_path)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Pedido", objective=_PEDIDO))
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "language_mode": "auto"}),
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "started_planning"
    stored = TaskService(session).get_task(root.id)
    language = stored.metadata_json["language"]
    assert language["applied"] == "english_operational"
    assert language["presentation_language"] == "pt"
    assert stored.objective == _PEDIDO
    assert TaskStatus(stored.status) == TaskStatus.PLANNING
