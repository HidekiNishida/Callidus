"""
Arquivo: tests/test_quality_disposition.py
Nome: test_quality_disposition.py
Propósito: verificar o contrato de qualidade, a decisão de decomposição e a explicação do feed.
Responsabilidade: camada de testes — comportamento do refinamento, da disposição e da narração.
Componentes: contrato explícito versus inferido, protótipo, herança, investigação, execução direta, redação de segredo.
Dependências: agent.orchestrator.quality_contract, agent.orchestrator.disposition, agent.orchestrator.narration, agent.orchestrator.runner.
Observações: banco temporário; nenhuma chamada de modelo.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.observability import get_bus
from agent.orchestrator.disposition import decide_disposition, investigation_plan
from agent.orchestrator.narration import explain_quality, explanation_event, safe_explanation
from agent.orchestrator.quality_contract import (
    attach_quality_contract,
    build_quality_contract,
    inherit_quality,
    render_quality_for_prompt,
)
from agent.orchestrator.runner import RunOrchestrator
from agent.orchestrator.strategy import ProfessionalStrategist
from agent.persistence.database import build_session_factory, init_db
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


def test_contrato_separa_pedido_de_piso_e_de_premissa():
    """O texto do usuário fica explícito; o piso do domínio fica inferido; a premissa não vira fato."""
    strategy = ProfessionalStrategist().analyze("Corrigir a falha de timeout na chamada da api")
    contract = build_quality_contract(strategy.original_request, strategy)

    assert contract["explicit"][0]["origin"] == "explícito"
    assert contract["explicit"][0]["text"].startswith("Corrigir")
    assert contract["inferred"]
    assert all(item["origin"] == "inferido" for item in contract["inferred"])
    assert contract["inferred"][0]["text"] not in contract["explicit"][0]["text"]
    assert contract["premises"]
    assert contract["premises"][0]["origin"] == "premissa"
    assert contract["scope_ceiling"] == "professional"
    assert "não criar capacidade" in contract["exclusions"][0]


def test_prototipo_nao_recebe_endurecimento_de_producao():
    """Um protótipo mantém o piso curto e registra o que ficou de fora."""
    strategy = ProfessionalStrategist().analyze("Faça um protótipo de página de login")
    contract = build_quality_contract(strategy.original_request, strategy)

    assert contract["scope_ceiling"] == "prototype"
    assert contract["inferred"] == [{"text": "demonstrar o fluxo pedido de ponta a ponta", "origin": "inferido"}]
    assert any("produção" in item for item in contract["exclusions"])
    assert "protótipo" in explain_quality(contract)


def test_pedido_contraditorio_registra_a_restricao_explicita():
    """Quando o texto pede mudança e proíbe alterar, a proibição prevalece e a tensão fica registrada."""
    text = "não altere nenhum arquivo e corrija o bug do cálculo"
    strategy = ProfessionalStrategist().analyze(text)
    contract = build_quality_contract(text, strategy)

    assert any("somente leitura" in item for item in contract["constraints"])
    assert contract["uncertainties"]


def test_heranca_leva_so_o_recorte_e_o_prompt_nao_trata_premissa_como_fato():
    """A filha não recebe o contrato inteiro, e o prompt marca a premissa como não confirmada."""
    strategy = ProfessionalStrategist().analyze("Documentar o módulo de rotas do agente")
    contract = build_quality_contract(strategy.original_request, strategy)
    child = inherit_quality(contract, "Escrever o guia de rotas")

    assert child is not None
    assert "premises" not in child
    assert "history" not in child
    assert child["constraints"] == contract["constraints"] or child["exclusions"]
    rendered = render_quality_for_prompt({"quality_contract": {**child, "premises": contract["premises"]}})
    assert "premissa, não confirmada" in rendered
    assert "Critérios desta etapa" in rendered


def test_etapa_unica_executa_e_incerteza_investiga_e_falha_replaneja():
    """A decisão distingue passo único, falta de contexto, várias partes e falha repetida."""
    single = decide_disposition(
        objective="Aplicar a correção no arquivo frete.py",
        metadata={"atomize": True},
        depth=2,
        max_depth=16,
        attempt_count=0,
        strategy={"complexity": "complex"},
    )
    assert single.action == "execute"

    unknown = decide_disposition(
        objective="Não sei onde está o erro que derruba o cálculo",
        metadata={"atomize": True},
        depth=1,
        max_depth=16,
        attempt_count=0,
    )
    assert unknown.action == "investigate"
    plan = investigation_plan(unknown.reason, read_only=False)
    assert plan.subtasks[0].metadata["tool"] == "list_dir"
    assert plan.subtasks[1].depends_on_indices == [0]
    assert plan.subtasks[0].metadata["atomic"] is True

    many = decide_disposition(
        objective="1. criar a rota\n2. validar o contrato\n3. cobrir o erro",
        metadata={"atomize": True},
        depth=1,
        max_depth=16,
        attempt_count=0,
    )
    assert many.action == "decompose"

    again = decide_disposition(
        objective="Repetir a mesma escrita",
        metadata={"last_failure": {"cause": "verification_failed"}},
        depth=1,
        max_depth=16,
        attempt_count=2,
    )
    assert again.action == "replan"

    guarded = decide_disposition(objective="qualquer coisa longa " * 40, metadata={}, depth=16, max_depth=16, attempt_count=0)
    assert guarded.action == "execute"


def test_explicacao_redige_segredo_e_nao_inventa_evento():
    """Segredo sai do texto e categoria inválida não vira evento."""
    leaked = safe_explanation("a chave sk-abcdefghijklmnopqrstuvwxyz apareceu no log")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in leaked
    assert explanation_event("nope", "texto", phase="plan") is None
    assert explanation_event("result", "", phase="plan") is None
    event = explanation_event("result", "Vou fazer: investigar e corrigir.", phase="plan")
    assert event is not None
    assert event["category"] == "result"
    assert explain_quality(None) == ""


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco temporário."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


@pytest.mark.asyncio
async def test_raiz_grava_contrato_e_publica_explicacao(session, tmp_path: Path):
    """O primeiro passo da raiz grava o contrato e emite a explicação, sem declarar a tarefa concluída."""
    project = ProjectService(session).create_project(ProjectCreate(name="q", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Pedido", objective="Corrigir a falha de timeout na chamada da api"),
    )
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "started_planning"
    stored = ContractService(session).get(root.id)
    quality = (stored.acceptance_json or {}).get("quality")
    assert quality["explicit"][0]["origin"] == "explícito"
    assert quality["acceptance"][0]["status"] == "pendente"
    task = TaskService(session).get_task(root.id)
    assert task.metadata_json["quality_contract"]["explicit_summary"].startswith("Corrigir")
    events = [item["type"] for item in get_bus().recent(str(run.id), 0)]
    assert "work.explained" in events
    assert TaskStatus(task.status) == TaskStatus.PLANNING


@pytest.mark.asyncio
async def test_etapa_marcada_para_dividir_executa_quando_ja_e_um_passo(session, tmp_path: Path):
    """Uma filha com atomize e um objetivo único não ganha outra árvore de três etapas."""
    project = ProjectService(session).create_project(ProjectCreate(name="d", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Correção", objective="Aplicar a correção no arquivo frete.py"),
    )
    root.status = TaskStatus.PLANNING.value
    root.metadata_json = {"atomize": True, "lead_specialty": "software_engineering"}
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)

    assert out["action"] == "operation_ready"
    meta = TaskService(session).get_task(root.id).metadata_json
    assert meta["atomize"] is False
    assert meta["model_operation"] is True
    assert meta["disposition"]["action"] == "execute"


@pytest.mark.asyncio
async def test_etapa_incerta_investiga_antes_de_alterar(session, tmp_path: Path):
    """Sem saber o ponto da mudança, a etapa marcada para dividir começa por uma investigação real."""
    project = ProjectService(session).create_project(ProjectCreate(name="i", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Falha", objective="Não sei onde está o erro que derruba o cálculo"),
    )
    root.status = TaskStatus.PLANNING.value
    root.metadata_json = {"atomize": True}
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()

    out = await RunOrchestrator(session, Settings(data_dir=tmp_path / "data")).step(run.id)
    session.commit()

    assert out["action"] == "decomposed"
    assert out["source"] == "disposition-investigate"
    children = TaskService(session).list_tasks(project.id)
    titles = [item.title for item in children if item.parent_id == root.id]
    assert "Investigar o contexto" in titles
    assert TaskService(session).get_task(root.id).metadata_json["investigated"] is True


def test_contrato_persistido_sobrevive_a_nova_leitura(session, tmp_path: Path):
    """Gravar o contrato não apaga os requisitos e uma segunda gravação igual não duplica histórico."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    task = TaskService(session).create_task(project.id, TaskCreate(title="t", objective="Criar notas.md"))
    ContractService(session).upsert(task.id, acceptance={"requirements": [{"id": "R1", "description": "Criar notas.md"}]})
    strategy = ProfessionalStrategist().analyze(task.objective)
    contract = build_quality_contract(task.objective, strategy)
    attach_quality_contract(session, task, contract)
    attach_quality_contract(session, task, contract)
    session.commit()

    acceptance = ContractService(session).get(task.id).acceptance_json
    assert acceptance["requirements"][0]["id"] == "R1"
    assert acceptance["quality"]["history"] == []
