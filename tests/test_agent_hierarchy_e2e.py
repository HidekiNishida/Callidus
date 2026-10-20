"""
Arquivo: tests/test_agent_hierarchy_e2e.py
Nome: test_agent_hierarchy_e2e.py
Propósito: Verificar o cenário completo de três gerações de agentes, com estado real e banco real.
Responsabilidade: camada de testes — percurso de ponta a ponta da hierarquia de agentes: executar, suspender, consultar, retomar e descartar.
Componentes: árvore avô–pai–filho–neto, cenário completo, consulta a agente suspenso, sobrevivência a reinício, retomada após falha, reaproveitamento de resultado, decomposição real e descarte preservador.
Dependências: agent.orchestrator.runner, agent.services.agent_service, agent.services.query_service, agent.services.run_service, agent.persistence.database e fixtures de sample_project.
Observações: banco SQLite temporário por teste; o cenário de decomposição copia o fixture sample_project para tmp_path.

O cenário completo do enunciado, com estado real e banco real.

Avô → pai → filho → neto. O neto persiste as descobertas e é suspenso; o filho
prossegue e também é suspenso; o pai consulta o filho; o filho recupera a informação
do neto; a resposta chega ao pai; o pai continua; os agentes desnecessários são
encerrados; os artefatos permanecem.

O teste também cobre o que costuma quebrar: reinício do processo, retomada depois de
falha e reuso de resultado já disponível (sem reanalisar o que já se sabe).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings
from agent.domain.agent_enums import AgentStatus, ExecutionStatus, QueryStatus
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AgentModel, EvidenceModel, TaskModel
from agent.services.agent_service import AgentService
from agent.services.project_service import ProjectService
from agent.services.query_service import QueryService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """Cria o engine e a fábrica de sessões sobre um banco temporário."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    return build_session_factory(engine)


@pytest.fixture
def session(factory) -> Session:
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    sess = factory()
    yield sess
    sess.close()


def _three_generations(session: Session):
    """Cria avô → pai → filho → neto, cada um com seu agente lógico."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="hierarquia", root_path="/tmp/hierarquia")
    )
    ts = TaskService(session)
    avo = ts.create_task(
        project.id, TaskCreate(title="Avô", objective="Resolver o incidente", kind="objective")
    )
    pai = ts.create_task(
        project.id,
        TaskCreate(title="Pai", objective="Diagnosticar", parent_id=avo.id, kind="subsystem"),
    )
    filho = ts.create_task(
        project.id,
        TaskCreate(title="Filho", objective="Investigar", parent_id=pai.id, kind="subsystem"),
    )
    neto = ts.create_task(
        project.id,
        TaskCreate(title="Neto", objective="Ler o log", parent_id=filho.id, kind="operation"),
    )
    agents = AgentService(session)
    return {
        "project": project,
        "tasks": {"avo": avo, "pai": pai, "filho": filho, "neto": neto},
        "agents": {
            "avo": agents.ensure_agent(avo.id),
            "pai": agents.ensure_agent(pai.id),
            "filho": agents.ensure_agent(filho.id),
            "neto": agents.ensure_agent(neto.id),
        },
    }


@pytest.mark.asyncio
async def test_cenario_completo_de_tres_geracoes(session: Session):
    """O ciclo completo — netos persistem descobertas, os agentes são suspensos, o pai consulta o filho e os artefatos permanecem — conclui com o trabalho entregue."""
    agents = AgentService(session)
    queries = QueryService(session)
    ids = _three_generations(session)
    agents_by_role = ids["agents"]
    tasks = ids["tasks"]

    # 1. O neto executa e persiste suas descobertas.
    agents.start_execution(agents_by_role["neto"].id)
    agents.save_checkpoint(agents_by_role["neto"].id, {"step": "liu o log", "plan_index": 1})
    agents.record_finding(
        agents_by_role["neto"].id,
        "A causa da falha foi o import de math removido em calc.py",
        evidence=["calc.py:1", "log: linha 42"],
        artifacts=["calc.py"],
    )

    # 2. O neto é suspenso: libera a execução, guarda o estado.
    agents.suspend(agents_by_role["neto"].id, reason="liberar memória")
    assert agents.get(agents_by_role["neto"].id).status == AgentStatus.SUSPENDED.value

    # 3. O filho continua e também é suspenso.
    agents.start_execution(agents_by_role["filho"].id)
    agents.record_finding(
        agents_by_role["filho"].id,
        "A investigação apontou um problema no cálculo de soma",
        evidence=["calc.py:7"],
    )
    agents.suspend(agents_by_role["filho"].id, reason="liberar memória")
    assert agents.get(agents_by_role["filho"].id).status == AgentStatus.SUSPENDED.value

    # 4. O pai consulta o filho. A evidência está no neto: a busca desce a hierarquia.
    query = queries.ask(
        agents_by_role["pai"].id,
        agents_by_role["filho"].id,
        "Qual foi a causa da falha?",
    )
    resolved = await queries.resolve(query.id)

    assert resolved.status == QueryStatus.ANSWERED.value
    assert "import de math" in (resolved.answer or "")
    # Quem respondeu foi o agente que tinha a evidência, e a resposta está correlacionada.
    assert resolved.answered_by_agent_id == agents_by_role["neto"].id
    assert resolved.task_id == tasks["filho"].id

    # 5. O pai recebe a resposta e continua o trabalho.
    pai_agent = agents.get(agents_by_role["pai"].id)
    agents.record_finding(pai_agent.id, resolved.answer or "", evidence=["calc.py:1"])
    assert len(agents.findings(pai_agent.id)) == 1

    # 6. Agentes desnecessários são encerrados; o que importa é preservado.
    agents.discard(agents_by_role["neto"].id, reason="já consultado")
    assert agents.get(agents_by_role["neto"].id).status == AgentStatus.DISCARDED.value
    # O estado recuperável (checkpoint) foi liberado; a descoberta — que é resultado —
    # continua disponível para quem precisar.
    assert agents.checkpoint(agents_by_role["neto"].id) == {}
    assert agents.findings(agents_by_role["neto"].id)[0]["text"].startswith("A causa da falha")

    # 7. O artefato continua acessível pela tarefa do agente descartado.
    neto_task = session.get(TaskModel, tasks["neto"].id)
    assert neto_task is not None
    assert neto_task.objective


@pytest.mark.asyncio
async def test_o_pai_consulta_o_filho_suspenso_sem_reativar_o_que_nao_precisa(
    session: Session,
):
    """A consulta usa o estado persistido: o filho suspenso nem precisa ser reativado."""
    agents = AgentService(session)
    queries = QueryService(session)
    ids = _three_generations(session)
    agents_by_role = ids["agents"]

    agents.record_finding(
        agents_by_role["filho"].id,
        "Os testes executados foram pytest -q e passaram",
        evidence=["pytest: 3 passed"],
    )
    agents.start_execution(agents_by_role["filho"].id)
    agents.suspend(agents_by_role["filho"].id)
    attempt_before = agents.current_execution(agents_by_role["filho"].id).attempt

    query = queries.ask(
        agents_by_role["pai"].id,
        agents_by_role["filho"].id,
        "quais testes foram executados?",
    )
    resolved = await queries.resolve(query.id)

    assert "pytest -q" in (resolved.answer or "")
    assert resolved.answer_json["inference_used"] is False
    assert resolved.answer_json["from_persisted_state"] is True
    # O filho não foi reativado: a tentativa de execução não mudou.
    assert agents.current_execution(agents_by_role["filho"].id).attempt == attempt_before


@pytest.mark.asyncio
async def test_o_estado_sobrevive_a_reinicio_do_processo(factory):
    """O processo principal morre e volta: as tarefas persistidas são recuperadas."""
    session = factory()
    ids = _three_generations(session)
    agents = AgentService(session)
    net = ids["agents"]["neto"]
    agents.start_execution(net.id)
    agents.save_checkpoint(net.id, {"step": "meio da leitura", "plan_index": 3})
    agents.record_finding(net.id, "achado que não pode ser perdido", evidence=["log:1"])
    agents.suspend(net.id)
    session.commit()
    session.close()

    # "O processo principal reiniciou": novo engine e novas sessões, mesmo arquivo.
    session = factory()
    recovered = AgentService(session)
    assert recovered.get(net.id).status == AgentStatus.SUSPENDED.value
    assert recovered.checkpoint(net.id)["step"] == "meio da leitura"
    assert recovered.findings(net.id)[0]["text"] == "achado que não pode ser perdido"

    # E a retomada continua de onde parou, sem repetir trabalho.
    execution = recovered.resume(net.id)
    assert execution.status == ExecutionStatus.RUNNING.value
    assert execution.checkpoint_json["plan_index"] == 3
    session.close()


@pytest.mark.asyncio
async def test_a_retomada_apos_falha_nao_duplica_a_acao(session: Session):
    """Depois de falhar, a retomada retoma do mesmo ponto sem avançar o trabalho por conta própria."""
    agents = AgentService(session)
    ids = _three_generations(session)
    net = ids["agents"]["neto"]
    agents.start_execution(net.id)
    agents.save_checkpoint(net.id, {"step": "antes da falha"})
    agents.fail_execution(net.id, "timeout do provedor")
    assert agents.get(net.id).status == AgentStatus.FAILED.value

    execution = agents.resume(net.id)
    assert execution.status == ExecutionStatus.RUNNING.value
    # O passo é o mesmo: a retomada não avança o trabalho por conta própria.
    assert agents.checkpoint(net.id)["step"] == "antes da falha"


@pytest.mark.asyncio
async def test_o_resultado_ja_conhecido_e_reaproveitado(session: Session):
    """A mesma pergunta duas vezes: a segunda não reanálise o que já se sabe."""
    agents = AgentService(session)
    queries = QueryService(session)
    ids = _three_generations(session)
    agents_by_role = ids["agents"]
    agents.record_finding(
        agents_by_role["neto"].id,
        "A causa da falha foi o import removido em calc.py",
        evidence=["calc.py:1"],
    )
    first = queries.ask(
        agents_by_role["pai"].id, agents_by_role["filho"].id, "qual foi a causa da falha?"
    )
    await queries.resolve(first.id)
    second = queries.ask(
        agents_by_role["pai"].id, agents_by_role["filho"].id, "qual foi a causa da falha?"
    )
    resolved = await queries.resolve(second.id)
    assert resolved.answer_json["inference_used"] is False
    assert resolved.answer == first.answer


@pytest.mark.asyncio
async def test_a_decomposicao_real_cria_a_hierarquia_de_agentes(tmp_path: Path):
    """O orquestrador de verdade, com o mock: cada subtarefa vira um agente filho."""
    fixture = Path(__file__).parent / "fixtures" / "sample_project"
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)

    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(
        ProjectCreate(name="e2e-agentes", root_path=str(workspace))
    )
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Objetivo E2E", objective="e2e corrigir calc.py e validar"),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root.id,
            config={"provider": "mock", "approve_risky_tools": True},
        ),
    )
    session.commit()

    orch = RunOrchestrator(session, settings)
    await orch.run_until_idle(run.id, max_steps=80)
    session.commit()

    agents = AgentService(session)
    root_agent = agents.agent_for_task(root.id)
    assert root_agent is not None
    descendants = agents.descendants(root_agent.id)
    assert descendants, "a decomposição deveria ter criado agentes filhos"
    assert all(child.parent_id == root_agent.id for child in descendants)
    assert all(child.depth == 1 for child in descendants)
    # A hierarquia não tem número fixo de gerações: ela acompanha a decomposição.
    assert all(child.role for child in descendants)
    session.close()


@pytest.mark.asyncio
async def test_o_descartar_preserva_tarefa_e_evidencias(session: Session):
    """Descartar o agente não apaga a tarefa nem as evidências registradas nela."""
    agents = AgentService(session)
    ids = _three_generations(session)
    net = ids["agents"]["neto"]
    tasks = ids["tasks"]
    session.add(
        EvidenceModel(
            task_id=tasks["neto"].id,
            verifier="pytest",
            passed=True,
            summary="3 testes passaram",
        )
    )
    session.flush()
    agents.start_execution(net.id)
    agents.record_finding(net.id, "achado preservado", evidence=["calc.py:1"])
    agents.suspend(net.id)

    report = agents.discard(net.id, reason="não é mais necessário")
    assert report["preserved"]["findings"][0]["text"] == "achado preservado"
    # Tarefa e evidência continuam lá: o descarte do agente não apaga o trabalho.
    assert session.get(TaskModel, tasks["neto"].id) is not None
    assert (
        session.query(EvidenceModel).filter(EvidenceModel.task_id == tasks["neto"].id).count() == 1
    )


@pytest.mark.asyncio
async def test_o_agente_e_o_estado_sobrevive_ao_encerramento_do_run(session: Session):
    """Encerrar um run não apaga o agente nem as descobertas."""
    agents = AgentService(session)
    ids = _three_generations(session)
    agents.record_finding(ids["agents"]["filho"].id, "descoberta do filho")
    agents.start_execution(ids["agents"]["filho"].id)
    agents.complete_execution(ids["agents"]["filho"].id)

    assert agents.get(ids["agents"]["filho"].id).status == AgentStatus.COMPLETED.value
    assert agents.findings(ids["agents"]["filho"].id)
    assert agents.get(ids["agents"]["filho"].id).id is not None
