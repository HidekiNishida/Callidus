# tests/test_agent_resilience.py — falhas e acessibilidade do resultado
"""O que acontece quando algo dá errado no meio do caminho.

Cobre os cinco pontos onde a hierarquia pode quebrar:

- falha durante a **execução** (o provedor cai);
- falha durante a **suspensão** (não dá para persistir o estado);
- falha durante a **retomada**;
- falha durante a **consulta** (a inferência estoura);
- falha durante o **descarte**.

E verifica a propriedade de não-duplicação: retomar não reexecuta o que já foi feito.

Por fim, confere que resultado, evidências e artefatos continuam acessíveis depois de
suspender, concluir e descartar o agente.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings
from agent.domain.agent_enums import AgentStatus, ExecutionStatus, QueryStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AgentModel, EvidenceModel, TaskModel
from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMProvider,
    ModelProfile,
)
from agent.services.agent_service import AgentService
from agent.services.project_service import ProjectService
from agent.services.query_service import QueryService
from agent.services.task_service import TaskService


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    settings = Settings(data_dir=tmp_path / "data")
    return build_session_factory(init_db(settings=settings))


@pytest.fixture
def session(factory) -> Session:
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def arvore(session: Session):
    project = ProjectService(session).create_project(
        ProjectCreate(name="resiliencia", root_path="/tmp/resiliencia")
    )
    ts = TaskService(session)
    pai = ts.create_task(
        project.id, TaskCreate(title="Pai", objective="Investigar", kind="objective")
    )
    filho = ts.create_task(
        project.id,
        TaskCreate(title="Filho", objective="Coletar", parent_id=pai.id, kind="operation"),
    )
    agents = AgentService(session)
    return {
        "tasks": {"pai": pai, "filho": filho},
        "agents": {"pai": agents.ensure_agent(pai.id), "filho": agents.ensure_agent(filho.id)},
    }


class _ProvedorQueFalha(LLMProvider):
    """Provedor que estoura no meio da inferência (passa pelo executor do processo)."""

    name = "quebrado"

    def __init__(self) -> None:
        self.chamadas = 0

    async def list_models(self):
        return []

    async def _chat(self, request):
        self.chamadas += 1
        raise RuntimeError("provedor caiu no meio da inferência")


class _ProvedorQueResponde(LLMProvider):
    name = "bom"

    def __init__(self, texto: str = "A causa foi o import removido") -> None:
        self.texto = texto
        self.chamadas = 0

    async def list_models(self):
        return []

    async def _chat(self, request):
        self.chamadas += 1
        return ChatCompletionResponse(content=self.texto)


# --------------------------------------------------------------- execução


def test_a_falha_da_execucao_preserva_o_checkpoint(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.save_checkpoint(filho.id, {"step": "coletando logs", "plan_index": 2})

    agents.fail_execution(filho.id, "provedor caiu")

    assert agents.get(filho.id).status == AgentStatus.FAILED.value
    execution = agents.current_execution(filho.id)
    assert execution.status == ExecutionStatus.FAILED.value
    assert "provedor caiu" in execution.last_error
    # O progresso anterior não se perdeu: a retomada sabe onde parou.
    assert agents.checkpoint(filho.id)["step"] == "coletando logs"


def test_a_falha_da_execucao_nao_prende_o_slot_do_executor():
    """O executor tem que devolver o slot quando o provedor estoura."""
    import asyncio

    from agent.services.executor import get_executor, reset_executor

    async def cenario():
        reset_executor()
        executor = get_executor()
        provider = _ProvedorQueFalha()
        try:
            with pytest.raises(RuntimeError):
                await provider.chat(
                    ChatCompletionRequest(
                        messages=[],
                        profile=ModelProfile(model_id="m"),
                    )
                )
            assert executor.metrics().active == 0
            assert executor.metrics().inferences_failed == 1
        finally:
            reset_executor()

    asyncio.run(cenario())


# --------------------------------------------------------------- suspensão


def test_a_suspensao_grava_o_ponto_exato_de_parada(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.save_checkpoint(filho.id, {"step": "meio do log", "plan_index": 4})
    execution = agents.suspend(filho.id, reason="limite de memória")

    assert execution.status == ExecutionStatus.SUSPENDED.value
    assert execution.checkpoint_json["step"] == "meio do log"
    assert execution.checkpoint_json["suspend_reason"] == "limite de memória"
    assert "suspended_at" in execution.checkpoint_json


def test_a_suspensao_que_falha_nao_deixa_estado_meio_consumido(session: Session, arvore):
    """Se a suspensão estoura, o agente continua no estado anterior — não pela metade."""
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.save_checkpoint(filho.id, {"step": "antes"})
    session.commit()

    original = AgentService._set_execution_status

    def _explode(self, execution, target, error=None):
        if target == ExecutionStatus.SUSPENDED:
            raise RuntimeError("falha ao persistir o estado")
        return original(self, execution, target, error=error)

    AgentService._set_execution_status = _explode
    try:
        with pytest.raises(RuntimeError):
            agents.suspend(filho.id, reason="x")
    finally:
        AgentService._set_execution_status = original
    session.rollback()

    # Estado íntegro: o agente segue ativo e com o checkpoint anterior.
    recem = AgentService(session).get(filho.id)
    assert recem.status == AgentStatus.ACTIVE.value
    assert AgentService(session).checkpoint(filho.id)["step"] == "antes"


# --------------------------------------------------------------- retomada


def test_a_retomada_apos_falha_preserva_o_ponto_de_parada(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.save_checkpoint(filho.id, {"step": "antes da falha", "plan_index": 1})
    agents.fail_execution(filho.id, "timeout")

    execution = agents.resume(filho.id)
    assert execution.status == ExecutionStatus.RUNNING.value
    assert execution.attempt == 2
    # A retomada não avança o trabalho sozinha: o passo é o mesmo.
    assert agents.checkpoint(filho.id)["step"] == "antes da falha"


def test_a_retomada_nao_reexecuta_acao_ja_concluida(session: Session, arvore):
    """O checkpoint guarda o que já foi feito; a retomada não o repete."""
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.record_finding(filho.id, "import removido em calc.py", evidence=["calc.py:1"])
    agents.save_checkpoint(filho.id, {"step": "concluido", "acao_concluida": "corrigir calc.py"})
    agents.suspend(filho.id)

    agents.resume(filho.id)
    assert agents.checkpoint(filho.id)["acao_concluida"] == "corrigir calc.py"
    assert len(agents.findings(filho.id)) == 1


# ----------------------------------------------------------------- consulta


@pytest.mark.asyncio
async def test_a_falha_da_inferencia_nao_corrompe_a_consulta(session: Session, arvore):
    queries = QueryService(session)
    pai = arvore["agents"]["pai"]
    filho = arvore["agents"]["filho"]
    provider = _ProvedorQueFalha()

    consulta = queries.ask(pai.id, filho.id, "qual foi a causa da falha?")
    with pytest.raises(RuntimeError):
        await queries.resolve(
            consulta.id, provider=provider, profile=ModelProfile(model_id="m")
        )

    # A consulta ficou coerente: conta a tentativa e pode ser refeita.
    recem = queries.get(consulta.id)
    assert recem.status == QueryStatus.ROUTED.value
    assert recem.attempts == 1
    assert recem.answer is None


@pytest.mark.asyncio
async def test_a_consulta_refeita_apos_falha_consegue_responder(session: Session, arvore):
    queries = QueryService(session)
    pai = arvore["agents"]["pai"]
    filho = arvore["agents"]["filho"]

    consulta = queries.ask(pai.id, filho.id, "qual foi a causa da falha?")
    with pytest.raises(RuntimeError):
        await queries.resolve(
            consulta.id,
            provider=_ProvedorQueFalha(),
            profile=ModelProfile(model_id="m"),
        )
    respondida = await queries.resolve(
        consulta.id,
        provider=_ProvedorQueResponde("A causa foi o import removido em calc.py"),
        profile=ModelProfile(model_id="m"),
    )
    assert respondida.status == QueryStatus.ANSWERED.value
    assert respondida.attempts == 2
    assert "import removido" in respondida.answer


@pytest.mark.asyncio
async def test_a_consulta_a_agente_descartado_responde_sem_evidencia(session: Session, arvore):
    """Descartar o alvo cancela a consulta pendente: não fica esperando para sempre."""
    queries = QueryService(session)
    agents = AgentService(session)
    pai = arvore["agents"]["pai"]
    filho = arvore["agents"]["filho"]

    consulta = queries.ask(pai.id, filho.id, "qual foi a causa da falha?")
    agents.discard(filho.id, force=True, reason="cancelado")
    assert queries.get(consulta.id).status == QueryStatus.CANCELLED.value
    assert queries.pending_for(filho.id) == []


# ---------------------------------------------------------------- descarte


def test_o_descarte_que_falha_nao_apaga_nada(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    agents.start_execution(filho.id)
    agents.record_finding(filho.id, "achado importante", evidence=["calc.py:1"])
    session.commit()

    original = AgentService._set_execution_status

    def _explode(self, execution, target, error=None):
        if target == ExecutionStatus.DISCARDED:
            raise RuntimeError("falha ao descartar")
        return original(self, execution, target, error=error)

    AgentService._set_execution_status = _explode
    try:
        with pytest.raises(RuntimeError):
            agents.discard(filho.id)
    finally:
        AgentService._set_execution_status = original
    session.rollback()

    # Nada foi perdido: o agente continua com suas descobertas.
    recem = AgentService(session)
    assert recem.get(filho.id).status == AgentStatus.ACTIVE.value
    assert recem.findings(filho.id)[0]["text"] == "achado importante"


# -------------------------------------------- resultado e evidências


def test_resultado_e_evidencias_apos_suspender(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    task = session.get(TaskModel, arvore["tasks"]["filho"].id)
    task.consolidated_result_json = {"summary": "corrigido em calc.py"}
    session.add(
        EvidenceModel(
            task_id=task.id, verifier="pytest", passed=True, summary="3 testes passaram"
        )
    )
    session.flush()
    agents.start_execution(filho.id)
    agents.suspend(filho.id)

    assert session.get(TaskModel, task.id).consolidated_result_json["summary"] == (
        "corrigido em calc.py"
    )
    assert (
        session.query(EvidenceModel).filter(EvidenceModel.task_id == task.id).count() == 1
    )


def test_resultado_e_evidencias_apos_concluir(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    task = session.get(TaskModel, arvore["tasks"]["filho"].id)
    task.consolidated_result_json = {"summary": "corrigido em calc.py"}
    session.add(
        EvidenceModel(
            task_id=task.id, verifier="pytest", passed=True, summary="3 testes passaram"
        )
    )
    session.flush()
    agents.start_execution(filho.id)
    agents.complete_execution(filho.id)

    assert session.get(TaskModel, task.id).consolidated_result_json is not None
    assert (
        session.query(EvidenceModel).filter(EvidenceModel.task_id == task.id).count() == 1
    )
    assert agents.get(filho.id).status == AgentStatus.COMPLETED.value


def test_resultado_e_evidencias_apos_descartar(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    task = session.get(TaskModel, arvore["tasks"]["filho"].id)
    task.consolidated_result_json = {"summary": "corrigido em calc.py"}
    session.add(
        EvidenceModel(
            task_id=task.id, verifier="pytest", passed=True, summary="3 testes passaram"
        )
    )
    session.flush()
    agents.start_execution(filho.id)
    agents.record_finding(filho.id, "achado do neto", evidence=["calc.py:1"])
    agents.suspend(filho.id)

    agents.discard(filho.id, reason="não é mais necessário")

    # Tarefa, resultado e evidência continuam lá.
    assert session.get(TaskModel, task.id).consolidated_result_json["summary"] == (
        "corrigido em calc.py"
    )
    assert (
        session.query(EvidenceModel).filter(EvidenceModel.task_id == task.id).count() == 1
    )
    # O estado recuperável foi liberado; o conhecimento, não.
    assert agents.checkpoint(filho.id) == {}
    assert agents.findings(filho.id)[0]["text"] == "achado do neto"


def test_o_descarte_com_purge_apaga_o_agente_mas_nao_a_tarefa(session: Session, arvore):
    agents = AgentService(session)
    filho = arvore["agents"]["filho"]
    task_id = arvore["tasks"]["filho"].id
    agents.start_execution(filho.id)
    agents.discard(filho.id, purge=True)

    assert session.query(AgentModel).filter(AgentModel.id == filho.id).count() == 0
    assert session.get(TaskModel, task_id) is not None
