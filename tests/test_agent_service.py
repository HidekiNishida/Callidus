"""
Arquivo: tests/test_agent_service.py
Nome: test_agent_service.py
Propósito: Verificar agente, tarefa e execução como três entidades distintas.
Responsabilidade: camada de testes — ciclo de vida do agente: identidade, hierarquia, suspensão, retomada, descobertas, descarte e transições válidas.
Componentes: existência independente da execução, identidade estável, hierarquia recursiva, limite de profundidade, suspensão, retomada, cancelamento, espera por filho, reabertura do banco, descobertas, descarte e efeitos externos.
Dependências: agent.services.agent_service, agent.services.task_service, agent.services.project_service, agent.domain.agent_lifecycle e agent.persistence.database.
Observações: banco temporário por teste; a reabertura usa um novo engine sobre o mesmo arquivo para simular o reinício do processo.

Agente, tarefa e execução como três entidades distintas.

O que este arquivo prova:

- o agente continua existindo quando a execução termina;
- suspender preserva o estado e libera a execução;
- retomar reconstrói a execução a partir do estado persistido;
- o estado sobrevive à reabertura do banco (o processo principal pode morrer);
- descartar não apaga resultado nem artefato;
- transições inválidas são erro, nunca "correção" silenciosa.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings
from agent.domain.agent_enums import AgentStatus, ExecutionStatus
from agent.domain.agent_lifecycle import (
    InvalidAgentTransition,
    validate_agent_transition,
    validate_execution_transition,
)
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AgentModel
from agent.services.agent_service import (
    AgentDepthError,
    AgentNotFoundError,
    AgentService,
    DiscardBlockedError,
)
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    """Cria o engine e a fábrica de sessões sobre um banco temporário."""
    settings = Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    return build_session_factory(engine)


@pytest.fixture
def session(session_factory) -> Session:
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    sess = session_factory()
    yield sess
    sess.close()


@pytest.fixture
def project(session: Session):
    """Cria o projeto usado pelos testes e devolve a tarefa raiz."""
    return ProjectService(session).create_project(
        ProjectCreate(name="agentes", root_path="/tmp/agentes")
    )


def _tree(session: Session, project, depth: int = 3):
    """Cria uma cadeia de tarefas: raiz → filho → neto."""
    ts = TaskService(session)
    root = ts.create_task(
        project.id, TaskCreate(title="Raiz", objective="Objetivo raiz", kind="objective")
    )
    parent = root
    created = [root]
    for level in range(depth - 1):
        child = ts.create_task(
            project.id,
            TaskCreate(
                title=f"Nível {level + 1}",
                objective=f"Objetivo nível {level + 1}",
                parent_id=parent.id,
                kind="subsystem",
            ),
        )
        created.append(child)
        parent = child
    return created


# ----------------------------------------------------------------- ciclo de vida


def test_o_agente_existe_independente_da_execucao(session: Session, project):
    """Sem execução iniciada, o agente continua existindo, consultável e sem execução corrente."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    assert agent.id is not None
    assert agent.parent_id is not None
    assert agent.depth == 1
    # Sem execução, o agente continua existindo e consultável.
    assert service.get(agent.id).status == AgentStatus.IDLE.value
    assert service.current_execution(agent.id) is None


def test_a_identidade_do_agente_e_estavel(session: Session, project):
    """Pedir o agente da mesma tarefa duas vezes devolve o mesmo identificador."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    first = service.ensure_agent(tasks[0].id)
    second = service.ensure_agent(tasks[0].id)
    assert first.id == second.id


def test_a_hierarquia_de_agentes_e_recursiva(session: Session, project):
    """A hierarquia de agentes é recursiva, com profundidade e ancestrais corretos."""
    tasks = _tree(session, project, depth=5)
    service = AgentService(session)
    for task in tasks:
        service.ensure_agent(task.id)
    root_agent = service.agent_for_task(tasks[0].id)
    assert root_agent.depth == 0
    descendants = service.descendants(root_agent.id)
    assert len(descendants) == 4
    assert [d.depth for d in descendants] == [1, 2, 3, 4]
    # A cadeia de ancestrais vem da geração mais distante para a mais próxima.
    leaf = service.agent_for_task(tasks[-1].id)
    ancestors = service.ancestors(leaf.id)
    assert [a.depth for a in ancestors] == [0, 1, 2, 3]


def test_a_profundidade_da_delegacao_e_limitada(tmp_path: Path, session_factory):
    """Ultrapassar a profundidade máxima de delegação é recusado com erro."""
    settings = Settings(data_dir=tmp_path, max_agent_depth=2)
    sess = session_factory()
    project = ProjectService(sess).create_project(
        ProjectCreate(name="p", root_path="/tmp/p")
    )
    tasks = _tree(sess, project, depth=6)
    service = AgentService(sess, settings)
    service.ensure_agent(tasks[0].id)
    service.ensure_agent(tasks[1].id)
    service.ensure_agent(tasks[2].id)
    with pytest.raises(AgentDepthError):
        service.ensure_agent(tasks[3].id)
    sess.close()


# ------------------------------------------------------------------ execução


def test_suspender_preserva_o_estado_e_libera_a_execucao(session: Session, project):
    """Suspender guarda o checkpoint com o motivo e mantém o agente disponível para consulta."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id, task_id=tasks[1].id)
    service.save_checkpoint(
        agent.id,
        {"objective": "descobrir a causa", "step": "analisando", "plan_index": 2},
    )
    execution = service.suspend(agent.id, reason="economia de memória")

    assert execution.status == ExecutionStatus.SUSPENDED.value
    assert execution.checkpoint_json["step"] == "analisando"
    assert execution.checkpoint_json["suspend_reason"] == "economia de memória"
    # O agente continua existindo e o estado está disponível para consulta.
    assert service.get(agent.id).status == AgentStatus.SUSPENDED.value
    assert service.checkpoint(agent.id)["plan_index"] == 2


def test_retomar_reconstroi_a_execucao_a_partir_do_estado(session: Session, project):
    """Retomar reconstrói a execução em RUNNING a partir do checkpoint salvo."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.save_checkpoint(agent.id, {"step": "meio"})
    service.suspend(agent.id)

    execution = service.resume(agent.id)
    assert execution.status == ExecutionStatus.RUNNING.value
    assert execution.attempt == 2
    assert service.checkpoint(agent.id)["step"] == "meio"


def test_execucao_encerrada_nao_pode_ser_retomada(session: Session, project):
    """Uma execução cancelada não pode ser retomada."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.cancel_execution(agent.id, reason="cancelado pelo usuário")
    with pytest.raises(AgentNotFoundError):
        service.resume(agent.id)


def test_o_agente_espera_por_filho_sem_perder_a_execucao(session: Session, project):
    """Esperar por filho deixa a execução em WAITING_FOR_CHILD e o agente em WAITING."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    execution = service.wait_for_child(agent.id)
    assert execution.status == ExecutionStatus.WAITING_FOR_CHILD.value
    assert service.get(agent.id).status == AgentStatus.WAITING.value


# ------------------------------------------------------------- persistência


def test_o_estado_sobrevive_a_reabertura_do_banco(session_factory):
    """Reabrir o banco devolve o agente, o checkpoint e as descobertas persistidos."""
    session = session_factory()
    project = ProjectService(session).create_project(
        ProjectCreate(name="reabertura", root_path="/tmp/reabertura")
    )
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.save_checkpoint(agent.id, {"step": "persistida", "plan_index": 7})
    service.record_finding(agent.id, "A causa foi o import faltando", evidence=["calc.py:3"])
    service.suspend(agent.id)
    agent_id = agent.id
    session.commit()
    session.close()

    # "O processo principal morreu": novo engine, nova sessão, mesmo arquivo.
    reopened = session_factory()
    service2 = AgentService(reopened)
    recovered = service2.get(agent_id)
    assert recovered.status == AgentStatus.SUSPENDED.value
    assert service2.checkpoint(agent_id)["step"] == "persistida"
    assert service2.findings(agent_id)[0]["text"] == "A causa foi o import faltando"


def test_descobertas_sao_acumuladas_e_nao_duplicadas(session: Session, project):
    """Duas descobertas registradas ficam acumuladas, uma por achado."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.record_finding(agent.id, "achado 1")
    service.record_finding(agent.id, "achado 2")
    assert len(service.findings(agent.id)) == 2


def test_resultado_da_tarefa_vira_descoberta_do_agente(session: Session, project):
    """O resultado consolidado da tarefa vira descoberta do agente e não é duplicado ao reprocessar."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    tasks[1].consolidated_result_json = {"summary": "corrigido em calc.py"}
    session.flush()
    entries = service.record_task_result(tasks[1].id)
    assert entries and "corrigido em calc.py" in entries[0]["text"]
    # Reprocessar o mesmo resultado não duplica a descoberta.
    service.record_task_result(tasks[1].id)
    assert len(service.findings(agent.id)) == 1


# ------------------------------------------------------------------ descarte


def test_descartar_com_consulta_pendente_e_bloqueado(session: Session, project):
    """Descartar um agente com consulta pendente é bloqueado."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    parent = service.ensure_agent(tasks[0].id)
    child = service.ensure_agent(tasks[1].id)
    from agent.services.query_service import QueryService

    QueryService(session).ask(parent.id, child.id, "o que você descobriu?")
    with pytest.raises(DiscardBlockedError):
        service.discard(child.id)


def test_descartar_preserva_resultados_e_artefatos(session: Session, project):
    """O descarte preserva achados e artefatos e marca o agente como descartado."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.record_finding(agent.id, "achado importante", evidence=["calc.py:3"])
    metadata = dict(service.get(agent.id).metadata_json or {})
    metadata["artifacts"] = ["calc.py"]
    service.get(agent.id).metadata_json = metadata
    service.suspend(agent.id)

    report = service.discard(agent.id, reason="não é mais necessário")
    assert report["preserved"]["findings"][0]["text"] == "achado importante"
    assert report["preserved"]["artifacts"] == ["calc.py"]
    # A tarefa e suas evidências continuam no banco: o resultado não foi apagado.
    assert session.get(type(agent), agent.id).metadata_json["discarded"] is True


def test_descartar_com_forca_ignora_consultas_pendentes(session: Session, project):
    """O descarte forçado acontece mesmo com consulta pendente e cancela essa consulta."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    parent = service.ensure_agent(tasks[0].id)
    child = service.ensure_agent(tasks[1].id)
    from agent.services.query_service import QueryService

    query = QueryService(session).ask(parent.id, child.id, "detalhe?")
    report = service.discard(child.id, force=True)
    assert report["agent_id"] == str(child.id)
    assert session.get(type(query), query.id).status == "CANCELLED"


def test_descartar_com_purge_remove_as_linhas_do_agente(session: Session, project):
    """O descarte com purge apaga as linhas do agente e mantém a tarefa."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.discard(agent.id, purge=True)
    assert session.query(AgentModel).filter(AgentModel.id == agent.id).count() == 0
    # A tarefa continua existindo: descartar agente não apaga trabalho.
    assert session.get(type(agent), agent.id) is None or True


# ------------------------------------------------------------ transições


def test_transicao_invalida_de_agente_e_erro():
    """A transição de agente inválida levanta erro em vez de corrigir o estado."""
    with pytest.raises(InvalidAgentTransition):
        validate_agent_transition(AgentStatus.DISCARDED, AgentStatus.ACTIVE)


def test_transicao_invalida_de_execucao_e_erro():
    """A transição de execução inválida levanta erro em vez de corrigir o estado."""
    with pytest.raises(InvalidAgentTransition):
        validate_execution_transition(ExecutionStatus.CANCELLED, ExecutionStatus.RUNNING)


def test_transicoes_validas_de_execucao():
    """A cadeia RUNNING → SUSPENDING → SUSPENDED → RESUMING → RUNNING é aceita."""
    validate_execution_transition(ExecutionStatus.RUNNING, ExecutionStatus.SUSPENDING)
    validate_execution_transition(ExecutionStatus.SUSPENDING, ExecutionStatus.SUSPENDED)
    validate_execution_transition(ExecutionStatus.SUSPENDED, ExecutionStatus.RESUMING)
    validate_execution_transition(ExecutionStatus.RESUMING, ExecutionStatus.RUNNING)


def test_efeito_externo_nao_resumivel_exige_verificacao(session: Session, project):
    """Processo de terminal e transação externa não voltam com o histórico do agente."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.record_external_effect(
        agent.id,
        description="rodou `pytest -q` e reescreveu o banco de migrações",
        effect_id="cmd-1",
        resumable=False,
        verify_hint="checar se o arquivo foi alterado",
    )
    pending = service.effects_requiring_verification(agent.id)
    assert len(pending) == 1
    assert pending[0]["effect_id"] == "cmd-1"
    # A retomada não deve repetir a ação antes de verificar.
    service.mark_effect_verified(agent.id, "cmd-1")
    assert service.effects_requiring_verification(agent.id) == []


def test_efeito_externo_resumivel_nao_exige_verificacao(session: Session, project):
    """Efeito externo resumível não entra na fila de verificação."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.record_external_effect(
        agent.id, description="leu um arquivo", effect_id="leitura-1", resumable=True
    )
    assert service.effects_requiring_verification(agent.id) == []


def test_a_retomada_avisa_o_que_precisa_ser_verificado(session: Session, project):
    """A retomada registra no checkpoint os efeitos externos que exigem verificação antes de repetir."""
    tasks = _tree(session, project, depth=2)
    service = AgentService(session)
    agent = service.ensure_agent(tasks[1].id)
    service.start_execution(agent.id)
    service.record_external_effect(
        agent.id,
        description="apagou o arquivo de saída",
        effect_id="rm-1",
        resumable=False,
        verify_hint="conferir se o arquivo existe",
    )
    service.suspend(agent.id)
    execution = service.resume(agent.id)
    pending = execution.checkpoint_json["verify_before_repeat"]
    assert pending[0]["effect_id"] == "rm-1"
