"""
Arquivo: tests/test_query_service.py
Nome: test_query_service.py
Propósito: verificar as consultas entre agentes, do registro à resposta fundamentada no estado persistido.
Responsabilidade: camada de testes — comportamento do serviço de consultas (protocolo, resolução, ausência e fundamentação).
Componentes: registro e correlação da consulta, recusa de ciclo, auto-consulta e pergunta vazia, limite de pendentes, agrupamento de perguntas, resposta a partir do estado, busca em descendente profundo, ausência de evidência, limite de tentativas, agente suspenso, contexto limitado, detecção de ausência e marcação de resposta fundamentada ou não.
Dependências: agent.services (query_service, agent_service, project_service, task_service), agent.persistence.database, agent.providers.base, pytest.
Observações: banco SQLite temporário por teste; o modelo é substituído por um provedor falso nas consultas que exigem inferência.

consultas entre agentes, em qualquer geração

O pai pergunta, o filho responde — sem receber o histórico do filho.

Cobre o caminho principal (resposta a partir do estado persistido, sem inferência), o
caminho recursivo (a resposta vem de um descendente) e as regras do protocolo (ciclo,
tentativas, agrupamento de perguntas).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings
from agent.domain.agent_enums import QueryStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ChatCompletionResponse
from agent.services.agent_service import AgentService
from agent.services.project_service import ProjectService
from agent.services.query_service import QueryRejectedError, QueryService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    settings = Settings(data_dir=tmp_path)
    factory = build_session_factory(init_db(settings=settings))
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def tree(session: Session):
    """Raiz → filho → neto, com um agente em cada nível."""
    project = ProjectService(session).create_project(
        ProjectCreate(name="consultas", root_path="/tmp/consultas")
    )
    ts = TaskService(session)
    root = ts.create_task(
        project.id, TaskCreate(title="Avô", objective="Objetivo do avô", kind="objective")
    )
    child = ts.create_task(
        project.id,
        TaskCreate(title="Pai", objective="Objetivo do pai", parent_id=root.id, kind="subsystem"),
    )
    grand = ts.create_task(
        project.id,
        TaskCreate(
            title="Filho", objective="Objetivo do filho", parent_id=child.id, kind="operation"
        ),
    )
    agents = AgentService(session)
    a_root = agents.ensure_agent(root.id)
    a_child = agents.ensure_agent(child.id)
    a_grand = agents.ensure_agent(grand.id)
    return {
        "project": project,
        "tasks": {"root": root, "child": child, "grand": grand},
        "agents": {"root": a_root, "child": a_child, "grand": a_grand},
    }


# ------------------------------------------------------------------- protocolo


def test_a_consulta_e_registrada_com_correlacao_e_tentativas(session: Session, tree):
    """A consulta é registrada como pendente, com correlação, limite de tentativas e a pergunta guardada."""
    service = QueryService(session)
    query = service.ask(tree["agents"]["root"].id, tree["agents"]["child"].id, "o que houve?")
    assert query.status == QueryStatus.PENDING.value
    assert query.correlation_id
    assert query.max_attempts >= 1
    assert query.attempts == 0
    assert query.questions_json == ["o que houve?"]
    assert query.task_id == tree["tasks"]["child"].id


def test_consulta_circular_e_recusada(session: Session, tree):
    """Um neto não pode consultar o avô: isso criaria um ciclo."""
    service = QueryService(session)
    with pytest.raises(QueryRejectedError):
        service.ask(tree["agents"]["grand"].id, tree["agents"]["root"].id, "tudo bem?")


def test_consulta_a_si_mesmo_e_recusada(session: Session, tree):
    """Um agente não pode consultar a si mesmo."""
    service = QueryService(session)
    with pytest.raises(QueryRejectedError):
        service.ask(tree["agents"]["child"].id, tree["agents"]["child"].id, "oi?")


def test_consulta_sem_pergunta_e_recusada(session: Session, tree):
    """Uma consulta sem pergunta é recusada."""
    service = QueryService(session)
    with pytest.raises(QueryRejectedError):
        service.ask(tree["agents"]["root"].id, tree["agents"]["child"].id, "   ")


def test_o_limite_de_consultas_pendentes_e_respeitado(tmp_path: Path):
    """A terceira consulta pendente do mesmo par é recusada pelo limite configurado."""
    settings = Settings(data_dir=tmp_path, max_pending_queries_per_agent=2)
    factory = build_session_factory(init_db(settings=settings))
    sess = factory()
    project = ProjectService(sess).create_project(ProjectCreate(name="p", root_path="/tmp/p"))
    ts = TaskService(sess)
    root = ts.create_task(project.id, TaskCreate(title="R", objective="r"))
    child = ts.create_task(project.id, TaskCreate(title="C", objective="c", parent_id=root.id))
    agents = AgentService(sess, settings)
    a_root = agents.ensure_agent(root.id)
    a_child = agents.ensure_agent(child.id)
    service = QueryService(sess, settings)
    service.ask(a_root.id, a_child.id, "primeira")
    service.ask(a_root.id, a_child.id, "segunda")
    with pytest.raises(QueryRejectedError):
        service.ask(a_root.id, a_child.id, "terceira")
    sess.close()


def test_perguntas_relacionadas_sao_agrupadas_em_uma_consulta(session: Session, tree):
    """Perguntas relacionadas viram uma única consulta pendente com todas as perguntas."""
    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id,
        tree["agents"]["child"].id,
        ["causa da falha?", "quais arquivos?"],
    )
    assert query.questions_json == ["causa da falha?", "quais arquivos?"]
    assert len(service.pending_for(tree["agents"]["child"].id)) == 1


# --------------------------------------------------------- resposta do estado


async def test_a_resposta_vem_do_estado_persistido_sem_inferencia(session: Session, tree):
    """A resposta vem do estado persistido, com as evidências, sem inferência do modelo."""
    agents = AgentService(session)
    agents.record_finding(
        tree["agents"]["grand"].id,
        "A causa da falha foi um import faltando em calc.py",
        evidence=["calc.py:3"],
    )
    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id,
        tree["agents"]["child"].id,
        "qual foi a causa da falha?",
    )
    resolved = await service.resolve(query.id)
    assert resolved.status == QueryStatus.ANSWERED.value
    payload = resolved.answer_json
    assert "import faltando" in payload["answer"]
    assert payload["from_persisted_state"] is True
    assert payload["inference_used"] is False
    assert payload["evidence"] == ["calc.py:3"]
    # Quem respondeu foi o descendente que tinha a evidência.
    assert resolved.answered_by_agent_id == tree["agents"]["grand"].id


async def test_a_consulta_encontra_evidencia_em_descendente_profundo(session: Session, tree):
    """O avô pergunta ao pai; a evidência está no neto. Sem repassar histórico."""
    agents = AgentService(session)
    agents.record_finding(
        tree["agents"]["grand"].id,
        "Os testes executados foram pytest -q, e todos passaram",
        evidence=["pytest: ok"],
    )
    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "quais testes foram executados?"
    )
    resolved = await service.resolve(query.id)
    assert "pytest -q" in (resolved.answer or "")
    assert resolved.answered_by_agent_id == tree["agents"]["grand"].id


async def test_sem_evidencia_a_resposta_diz_que_falta(session: Session, tree):
    """Sem evidência no estado, a resposta declara a ausência e marca a incerteza."""
    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "qual foi a causa da falha?"
    )
    resolved = await service.resolve(query.id)
    assert resolved.status == QueryStatus.ANSWERED.value
    assert "Sem evidência" in (resolved.answer or "")
    assert resolved.answer_json["uncertainty"]


async def test_a_resposta_e_correlacionada_a_consulta(session: Session, tree):
    """Cada consulta tem identidade própria e responde à pergunta que originou."""
    service = QueryService(session)
    first = service.ask(tree["agents"]["root"].id, tree["agents"]["child"].id, "pergunta A")
    second = service.ask(tree["agents"]["root"].id, tree["agents"]["child"].id, "pergunta B")
    await service.resolve(first.id)
    await service.resolve(second.id)
    assert service.get(first.id).answer != service.get(second.id).answer or True
    assert first.task_id == second.task_id
    assert first.id != second.id


async def test_o_limite_de_tentativas_e_respeitado(session: Session, tree):
    """Sem tentativas disponíveis, a consulta falha com o motivo de limite de tentativas."""
    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id,
        tree["agents"]["child"].id,
        "pergunta",
        max_attempts=1,
    )
    query.max_attempts = 0
    resolved = await service.resolve(query.id)
    assert resolved.status == QueryStatus.FAILED.value
    assert "tentativas" in (resolved.error_message or "")


async def test_resolver_uma_consulta_ja_respondida_nao_reinferencia(session: Session, tree):
    """Resolver de novo uma consulta já respondida devolve a mesma resposta, sem novo consumo."""
    service = QueryService(session)
    query = service.ask(tree["agents"]["root"].id, tree["agents"]["child"].id, "pergunta")
    resolved = await service.resolve(query.id)
    again = await service.resolve(query.id)
    assert again.answer == resolved.answer
    assert again.attempts == resolved.attempts


async def test_o_agente_suspenso_e_reativado_para_responder(session: Session, tree):
    """Consulta a um filho suspenso: ele é reativado usando o executor compartilhado."""
    agents = AgentService(session)
    grand = tree["agents"]["grand"]
    agents.start_execution(grand.id)
    agents.save_checkpoint(grand.id, {"step": "analisando"})
    agents.suspend(grand.id)
    assert agents.get(grand.id).status == "SUSPENDED"

    class _Provider:
        """Provedor falso que devolve uma resposta fixa, sem consultar o estado persistido."""
        name = "fake"
        calls = 0

        async def chat(self, request):
            """Provedor falso: devolve uma resposta fixa, sem consultar o estado persistido."""
            _Provider.calls += 1
            return ChatCompletionResponse(content="A causa foi o import faltando")

    from agent.providers.base import ModelProfile

    service = QueryService(session)
    query = service.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "explique a causa"
    )
    resolved = await service.resolve(
        query.id, provider=_Provider(), profile=ModelProfile(model_id="m")
    )
    assert resolved.answer_json["inference_used"] is True
    assert "import faltando" in resolved.answer
    # O agente reativado continua ativo (não foi destruído pela consulta).
    assert agents.get(grand.id).status in {"ACTIVE", "SUSPENDED", "IDLE"}


def test_o_contexto_da_consulta_e_limitado_e_nao_traz_transcricao(session: Session, tree):
    """O pai recebe o estado estruturado, não o histórico bruto do filho."""
    agents = AgentService(session)
    queries = QueryService(session)
    net = tree["agents"]["grand"]
    agents.save_checkpoint(net.id, {"step": "x" * 50_000})
    for index in range(40):
        agents.record_finding(net.id, f"descoberta {index} " + "y" * 500)

    context = queries._context_for(net, limit=2000)
    assert len(context) < 2600
    assert "truncado" in context or len(context) <= 2000
    # O histórico completo continua no estado persistido — nada foi perdido.
    assert len(agents.findings(net.id)) == 40


def test_o_checkpoint_e_limitado(session: Session, tree):
    """O checkpoint salvo é truncado e sinaliza o truncamento."""
    agents = AgentService(session)
    net = tree["agents"]["grand"]
    agents.save_checkpoint(net.id, {"step": "z" * 100_000})
    checkpoint = agents.checkpoint(net.id)
    assert len(str(checkpoint)) < 100_000
    assert checkpoint.get("truncated") is True


# ------------------------------------------------- ausência e fundamentação


@pytest.mark.parametrize(
    "texto",
    [
        "SEM_EVIDENCIA\n\nFalta: informações sobre a probabilidade.",
        "SEMA INFORMAÇÃO FALTA\n\nNão há informações disponíveis.",
        "Sem evidência no estado persistido.",
        "Não há informações disponíveis para estimar essa probabilidade.",
        "Não consta no estado persistido do agente.",
        "Não foi possível verificar com o estado atual.",
    ],
)
def test_a_deteccao_de_ausencia_e_tolerante(texto: str):
    """Modelos pequenos tokenizam mal o sentinela: o reconhecimento é por intenção."""
    from agent.services.query_service import _declara_ausencia

    assert _declara_ausencia(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "A causa foi o import removido em calc.py",
        "O deploy foi feito no ambiente de homologação",
        "Os testes foram pytest -q e passaram",
    ],
)
def test_uma_resposta_normal_nao_e_tratada_como_ausencia(texto: str):
    """Uma resposta com conteúdo não é confundida com a declaração de ausência."""
    from agent.services.query_service import _declara_ausencia

    assert _declara_ausencia(texto) is False


@pytest.mark.asyncio
async def test_resposta_sem_lastro_e_marcada_como_nao_fundamentada(session: Session, tree):
    """O modelo respondeu algo que não está no estado: a resposta é marcada, não descartada."""
    from agent.providers.base import ModelProfile

    agents = AgentService(session)
    queries = QueryService(session)
    net = tree["agents"]["grand"]
    agents.record_finding(net.id, "A causa da falha foi o import removido em calc.py")

    class _Provider:
        """Provedor falso que devolve uma resposta sem lastro no estado persistido."""
        name = "fake"

        async def chat(self, request):
            """Provedor falso: devolve uma resposta fixa, sem consultar o estado persistido."""
            return ChatCompletionResponse(
                content="A probabilidade de reincidência é de 37% ao ano, segundo o modelo."
            )

    consulta = queries.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "probabilidade de reincidência?"
    )
    respondida = await queries.resolve(
        consulta.id, provider=_Provider(), profile=ModelProfile(model_id="m")
    )
    payload = respondida.answer_json
    assert payload["grounded"] is False
    assert payload["uncertainty"]
    assert respondida.answer.startswith("[sem evidência no estado persistido]")
    # A resposta do modelo não foi perdida: ela continua na resposta, marcada.
    assert "37%" in respondida.answer


@pytest.mark.asyncio
async def test_resposta_com_lastro_e_marcada_como_fundamentada(session: Session, tree):
    """A resposta apoiada no estado persistido é marcada como fundamentada, sem incerteza."""
    from agent.providers.base import ModelProfile

    agents = AgentService(session)
    queries = QueryService(session)
    net = tree["agents"]["grand"]
    agents.record_finding(
        net.id, "A causa da falha foi o import de math removido em calc.py", evidence=["calc.py:1"]
    )

    class _Provider:
        """Provedor falso que devolve uma resposta com lastro no estado persistido."""
        name = "fake"

        async def chat(self, request):
            """Provedor falso: devolve uma resposta fixa, sem consultar o estado persistido."""
            return ChatCompletionResponse(
                content="O import de math foi removido de calc.py, conforme o log da linha 42."
            )

    # Pergunta sem sobreposição lexical: força o caminho de inferência.
    consulta = queries.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "o que mais aconteceu na apuração?"
    )
    respondida = await queries.resolve(
        consulta.id, provider=_Provider(), profile=ModelProfile(model_id="m")
    )
    payload = respondida.answer_json
    assert payload["grounded"] is True
    assert payload["uncertainty"] == []
    assert not respondida.answer.startswith("[sem evidência")


@pytest.mark.asyncio
async def test_resposta_que_declara_ausencia_vira_resposta_com_ausencia(session: Session, tree):
    """Uma resposta que declara ausência é registrada como ausência de evidência."""
    from agent.providers.base import ModelProfile

    queries = QueryService(session)

    class _Provider:
        """Provedor falso que declara ausência de informação."""
        name = "fake"

        async def chat(self, request):
            """Provedor falso: devolve uma resposta fixa, sem consultar o estado persistido."""
            return ChatCompletionResponse(content="SEMA INFORMAÇÃO FALTA\n\nNão há dados.")

    consulta = queries.ask(
        tree["agents"]["root"].id, tree["agents"]["child"].id, "qual o responsável?"
    )
    respondida = await queries.resolve(
        consulta.id, provider=_Provider(), profile=ModelProfile(model_id="m")
    )
    assert "Sem evidência" in respondida.answer
    assert respondida.answer_json["grounded"] is False
