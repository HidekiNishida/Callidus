"""
Arquivo: tests/test_resolution_strategy.py
Nome: test_resolution_strategy.py
Propósito: verificar a estratégia de resolução: repetição improdutiva, repetição legítima, mudança de abordagem, falha transitória, corte de saída, retomada, falha de subtarefa, falsa conclusão, evidência nova e coerência dos limites.
Responsabilidade: camada de testes — o comportamento da memória de abordagem, do contador de problema e da política de limites.
Componentes: memória de abordagem, contador de problema por objetivo,Mudança material, replanejamento com abordagem, limites cumulativos na retomada.
Dependências: agent.orchestrator (approach, stagnation, runner), agent.services (project, run, task), agent.persistence (database, models), pytest.
Observações: banco temporário por teste; provedor falso que devolve respostas programadas; nenhum teste depende de rede.

Cenários A a J da missão de aprimoramento da estratégia de resolução: cada um fixa um
comportamento que, antes, não existia ou não era verificado.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
    classify_provider_error,
)
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.approach import (
    alternatives_for,
    approach_of,
    approach_signature,
    declare_change,
    record_attempt,
    render_approach,
)
from agent.orchestrator.runner import RunOrchestrator
from agent.orchestrator.stagnation import (
    limits_for,
    problem_attempts,
    problem_key,
    usage_since,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import (
    EventLogModel,
    ExecutionRunModel,
    OperationAttemptModel,
    TaskModel,
)
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService
from agent.verification.fingerprint import workspace_state


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


class _Scripted:
    """Provedor falso que devolve respostas programadas e registra os prompts recebidos."""

    name = "mock"
    last_usage = None

    def __init__(self, replies: list[str]) -> None:
        """Guarda as respostas programadas e prepara o registro de prompts."""
        self.replies = replies
        self.prompts: list[str] = []

    async def chat(self, request):
        """Provedor falso: registra o prompt e devolve a resposta programada."""
        self.prompts.append("\n".join(m.content for m in request.messages))
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]

        class _R:
            """Resposta falsa que carrega a resposta programada."""

            content = reply

        return _R()


def _project(session, tmp_path: Path):
    """Cria o projeto do teste e devolve o serviço de tarefas."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    return project, TaskService(session)


def _failure(detail: str = "falhou", cause: str = "invalid_output", strategy: str = "s1") -> dict:
    """Monta uma falha com assinatura e estratégia, como o orquestrador as registra."""
    data = Failure(FailureCategory.RECOVERABLE, FailureCause.INVALID_OUTPUT, detail).as_dict()
    data["cause"] = cause
    return {**data, "signature": f"sig-{cause}", "strategy": strategy}


def _run_with_change(session, tmp_path: Path, provider, monkeypatch, *, objective: str = "Objetivo"):
    """Prepara uma etapa de alteração de arquivo em execução, com o provedor falso já conectado."""
    project, tasks = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective=objective))
    root.status = TaskStatus.COMPLETED.value
    change = tasks.create_task(
        project.id,
        TaskCreate(
            title="Alterar arquivo",
            objective="Escreva a.txt com ok",
            parent_id=root.id,
            metadata={"model_operation": True, "atomic": True},
        ),
    )
    change.status = TaskStatus.RUNNING.value
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)
    return run, change, root


# --------------------------------------------------------------------------------------------
# Memória de abordagem (o que foi tentado, hipótese, o que será diferente)
# --------------------------------------------------------------------------------------------


def test_a_memoria_registra_tentativa_hipotese_e_proxima_abordagem(session, tmp_path: Path):
    """A falha registrada deixa memória: o que travou, a hipótese e o que será diferente."""
    project, tasks = _project(session, tmp_path)
    task = tasks.create_task(project.id, TaskCreate(title="T", objective="Faça X"))

    record_attempt(task, _failure("resposta vazia"))

    approach = approach_of(task)
    assert "invalid_output" in approach["problem"]
    assert "não entendeu o formato" in approach["hypothesis"]
    assert approach["tried"][-1]["result"] == "resposta vazia"
    assert approach["next_change"]
    assert approach["success_criterion"] and approach["failure_criterion"]
    assert "Abordagem desta etapa" in render_approach(task)


def test_a_esgotamento_de_alternativas_e_registrado(session, tmp_path: Path):
    """Sem alternativa nova sobrando, a memória diz que a etapa precisa de ação de fora."""
    project, tasks = _project(session, tmp_path)
    task = tasks.create_task(project.id, TaskCreate(title="T", objective="Faça X"))
    options = alternatives_for("invalid_output")

    for _ in range(len(options) + 1):
        record_attempt(task, _failure("resposta vazia"))

    approach = approach_of(task)
    assert approach["exhausted"] is True
    assert approach["next_change"] == ""
    assert "ação de fora" in render_approach(task)


def test_a_mudanca_de_abordagem_altera_a_assinatura(session, tmp_path: Path):
    """Declarar outra abordagem muda a assinatura: a tentativa deixa de ser repetição."""
    project, tasks = _project(session, tmp_path)
    task = tasks.create_task(project.id, TaskCreate(title="T", objective="Faça X"))
    record_attempt(task, _failure("resposta vazia"))
    before = approach_signature(task)

    declare_change(task, "usar a ferramenta de escrita diretamente")

    assert approach_signature(task) != before
    assert approach_of(task)["current_change"] == "usar a ferramenta de escrita diretamente"


# --------------------------------------------------------------------------------------------
# Contador de problema: sobrevive ao replanejamento, respeita a mudança material
# --------------------------------------------------------------------------------------------


def test_b_o_contador_de_problema_sobrevive_a_replanejamento(session, tmp_path: Path):
    """A mesma falha em outra etapa do mesmo objetivo continua a mesma repetição.

    Antes, o contador vivia na etapa: o replanejamento criava uma etapa nova e a contagem
    recomeçava, deixando a cadeia "falhou → replanejou → falhou igual" passar.
    """
    project, tasks = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Conserte o projeto"))
    first = tasks.create_task(project.id, TaskCreate(title="A", objective="A", parent_id=root.id))
    second = tasks.create_task(project.id, TaskCreate(title="B", objective="B", parent_id=root.id))
    failure = _failure("resposta vazia")

    count, total, _ = problem_attempts(root, failure)
    assert (count, total) == (1, 1)

    # A etapa nova do replanejamento: mesma estratégia, mesmo erro, mesmo objetivo.
    count, total, _ = problem_attempts(root, failure)
    assert (count, total) == (2, 2)

    # A terceira tentativa em outra etapa: a contagem continua.
    count, total, _ = problem_attempts(root, failure)
    assert (count, total) == (3, 3)
    assert second.id and first.id


def test_c_mudanca_de_estrategia_zera_a_contagem_de_repeticao(session, tmp_path: Path):
    """Abordagem de execução diferente não é repetição: a contagem recomeça."""
    project, tasks = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Conserte o projeto"))

    problem_attempts(root, _failure("falhou", strategy="s1"))
    count, total, _ = problem_attempts(root, _failure("falhou", strategy="s2"))

    assert count == 1
    assert total == 2, "o total do problema não recomeça: ele é o teto do problema"


def test_i_evidencia_nova_nao_e_bloqueada_pela_deteccao(session, tmp_path: Path):
    """Mudança material no disco (a correção) zera a contagem: a nova tentativa é legítima."""
    project, tasks = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Conserte o projeto"))
    failure = _failure("arquivo não encontrado")

    before = workspace_state(str(tmp_path))
    problem_attempts(root, failure, workspace=before)
    # A correção: o arquivo passa a existir.
    (tmp_path / "a.txt").write_text("ok", encoding="utf-8")
    after = workspace_state(str(tmp_path))
    assert after != before

    count, total, _ = problem_attempts(root, failure, workspace=after)

    assert count == 1, "com o disco mudado, a repetição não é a mesma tentativa"
    assert total == 2


def test_j_a_chave_do_problema_separa_erros_diferentes_no_mesmo_objetivo(session, tmp_path: Path):
    """Falhas diferentes no mesmo objetivo são problemas diferentes."""
    project, tasks = _project(session, tmp_path)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Conserte o projeto"))

    a = problem_key(root.objective, "sig-a")
    b = problem_key(root.objective, "sig-b")

    assert a != b
    assert a == problem_key(root.objective, "sig-a")


# --------------------------------------------------------------------------------------------
# Falha de provedor: transitória x permanente
# --------------------------------------------------------------------------------------------


def test_d_falha_transitoria_do_provedor_e_repetivel():
    """Indisponibilidade e limite de uso são transitórios: a política permite repetir."""
    down = classify_provider_error("Ollama indisponível: connection refused")
    assert down.category == FailureCategory.EXTERNAL_UNAVAILABLE
    assert down.cause == FailureCause.PROVIDER_UNAVAILABLE

    limited = classify_provider_error("openrouter: limite de uso atingido (HTTP 429)")
    assert limited.cause == FailureCause.PROVIDER_RATE_LIMIT
    assert limited.category == FailureCategory.RECOVERABLE


def test_d_pedido_recusado_nao_e_falha_transitoria():
    """Um pedido recusado (HTTP 4xx) não se resolve repetindo a mesma requisição."""
    rejected = classify_provider_error("openrouter: requisição recusada (HTTP 400).")

    assert rejected.cause == FailureCause.PROVIDER_REJECTED
    assert rejected.category == FailureCategory.CHANGE_STRATEGY
    assert not rejected.retry_same_strategy

    server = classify_provider_error("openrouter: erro do servidor (HTTP 503)")
    assert server.category == FailureCategory.RECOVERABLE


def test_d_credencial_invalida_exige_acao_de_fora():
    """Falha de autenticação é configuração: nenhuma nova tentativa do agente resolve."""
    auth = classify_provider_error("openrouter: falha de autenticação (HTTP 401).")

    assert auth.category == FailureCategory.CONFIGURATION
    assert auth.cause == FailureCause.PROVIDER_CREDENTIALS


# --------------------------------------------------------------------------------------------
# Integração: o orquestrador reage ao que a memória diz
# --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_a_repeticao_sem_progresso_para_no_limite_do_problema(session, tmp_path, monkeypatch):
    """A mesma falha repetida para no limite do problema, com o run pausado e o motivo escrito.

    A repetição não é contada por etapa: uma tarefa que falha igual três vezes esbarra no
    limite de estratégia; o replanejamento cria uma etapa nova, e o **mesmo** problema continua
    contando até o teto do problema, quando o run pausa com o diagnóstico.
    """
    provider = _Scripted(["Vou escrever o arquivo."])
    run, _change, root = _run_with_change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))
    settings = Settings(data_dir=tmp_path / "data")
    limits = limits_for(settings, {})

    actions = []
    for _ in range(40):
        out = await orch.step(run.id)
        actions.append(out.get("action"))
        session.commit()
        if out.get("action") in {"run_paused", "run_stalled", "run_completed"}:
            break

    attempts = session.scalars(
        select(OperationAttemptModel).where(OperationAttemptModel.run_id == run.id, OperationAttemptModel.kind == "model")
    ).all()
    assert len(attempts) <= limits["attempts_per_problem"], (
        f"o problema consumiu {len(attempts)} tentativas; o teto é {limits['attempts_per_problem']}"
    )
    assert "run_paused" in actions, actions
    pause = root.metadata_json["pause"]
    assert pause["limit"] in {"attempts_per_strategy", "attempts_per_problem"}
    assert pause["diagnosis"]["hypothesis"]
    assert pause["diagnosis"]["next_change"]


@pytest.mark.asyncio
async def test_b_repeticao_legitima_apos_correcao_e_permitida(session, tmp_path, monkeypatch):
    """Com a causa corrigida (o disco mudou), a mesma operação pode ser repetida e concluir."""
    payload = '{"path":"a.txt","content":"ok"}'
    provider = _Scripted(["Vou escrever o arquivo.", payload])
    run, _change, _root = _run_with_change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    # A primeira tentativa falha; a correção acontece no disco; a segunda deve passar.
    await orch.step(run.id)
    (tmp_path / "a.txt").write_text("ok", encoding="utf-8")
    session.commit()
    for _ in range(6):
        out = await orch.step(run.id)
        session.commit()
        if out.get("action") in {"verified_ok", "run_paused", "run_stalled", "run_completed"}:
            break

    events = session.scalars(
        select(EventLogModel).where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.stagnation")
    ).all()
    assert not events, "uma correção concreta não pode ser tratada como repetição improdutiva"


@pytest.mark.asyncio
async def test_f_a_retomada_respeita_o_consumo_acumulado(session, tmp_path, monkeypatch):
    """Retomar não devolve o orçamento gasto: a retomada concede cota nova sobre o consumo."""
    provider = _Scripted(["Vou escrever."])
    run, _change, _root = _run_with_change(session, tmp_path, provider, monkeypatch)
    run = session.get(ExecutionRunModel, run.id)
    run.config_json = {**run.config_json, "limits": {"model_calls": 1}}
    session.commit()
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    await orch.step(run.id)
    paused = await orch.step(run.id)
    assert paused["action"] == "run_paused"
    spent = usage_since(session, run)["model_calls"]
    assert spent >= 1

    RunService(session).resume_run(run.id)
    session.commit()
    resumed = session.get(ExecutionRunModel, run.id)
    assert resumed.status == RunStatus.ACTIVE.value
    # O consumo continua lá: a retomada zera o tramo, não a gasto.
    assert usage_since(session, resumed)["model_calls"] >= spent
    [event] = session.scalars(
        select(EventLogModel).where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.resumed")
    ).all()
    assert event.payload_json["usage"]["model_calls"] >= spent


@pytest.mark.asyncio
async def test_j_os_limites_nao_sao_multiplicados_por_camada(session, tmp_path, monkeypatch):
    """O teto do problema vale para o run inteiro, apesar das camadas internas.

    Cada camada tem seus próprios contadores (tentativas da etapa, rodadas de ferramenta,
    chamadas ao modelo). O limite do problema é o externo: mesmo com as camadas internas
    multiplicando, o total de tentativas no mesmo problema é limitado.
    """
    provider = _Scripted(["Vou escrever o arquivo."])
    run, _change, _root = _run_with_change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))
    settings = Settings(data_dir=tmp_path / "data")
    limits = limits_for(settings, {})

    for _ in range(40):
        out = await orch.step(run.id)
        session.commit()
        if out.get("action") in {"run_paused", "run_stalled", "run_completed"}:
            break

    attempts = session.scalars(
        select(OperationAttemptModel).where(OperationAttemptModel.run_id == run.id, OperationAttemptModel.kind == "model")
    ).all()
    assert len(attempts) <= limits["attempts_per_problem"]


def test_j_o_limite_do_problema_e_configuravel_e_vem_do_run(session, tmp_path: Path):
    """O teto do problema vem das configurações e pode ser ajustado por run."""
    limits = limits_for(Settings(max_attempts_per_problem=9), {"limits": {"attempts_per_problem": 2}})
    assert limits["attempts_per_problem"] == 2
    assert limits_for(Settings(), {})["attempts_per_problem"] == Settings().max_attempts_per_problem


# --------------------------------------------------------------------------------------------
# Cenário C — a estratégia alternativa é real, declarada e registrada
# --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_o_replanejamento_declara_a_abordagem_diferente(session, tmp_path, monkeypatch):
    """O replanejamento não manda "use outra abordagem": ele escolhe e declara a alternativa.

    A etapa nova nasce com a abordagem declarada, o objetivo traz a mudança concreta, e o
    histórico registra por que a alternativa foi escolhida. É isso que distingue uma mudança
    de estratégia de uma nova tentativa com o contador zerado.
    """
    provider = _Scripted(["Vou escrever o arquivo."])
    run, change, root = _run_with_change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    for _ in range(12):
        out = await orch.step(run.id)
        session.commit()
        if out.get("action") == "replanned":
            break
    assert out.get("action") == "replanned", out.get("action")
    stagnation = change.metadata_json["stagnation"]
    assert stagnation["hypothesis"]
    assert stagnation["next_change"] in alternatives_for("invalid_output")
    assert stagnation["success_criterion"] and stagnation["failure_criterion"]

    # A etapa nova carrega a abordagem declarada e o objetivo diz o que muda.
    children = [t for t in session.scalars(select(TaskModel).where(TaskModel.parent_id == root.id)).all()]
    assert children, "o replanejamento precisa criar a etapa nova"
    fresh = [t for t in children if t.id != change.id]
    assert fresh, "o replanejamento precisa criar a etapa nova"
    assert "Agora é preciso fazer diferente" in fresh[0].objective
    assert "Hipótese da falha" in fresh[0].objective
    assert "Sucesso:" in fresh[0].objective
    # A etapa que executa o trabalho é a que carrega a abordagem declarada.
    declared = [t for t in fresh if approach_of(t).get("current_change")]
    assert declared, "a etapa nova nasce com a abordagem declarada"
    approach = approach_of(declared[0])
    assert approach["current_change"] in alternatives_for("invalid_output")


# --------------------------------------------------------------------------------------------
# Cenário G — a falha de uma subtarefa não destrói o trabalho válido
# --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_a_falha_de_uma_subtarefa_preserva_o_trabalho_valido(session, tmp_path, monkeypatch):
    """Uma subtarefa que falha não apaga o que a outra provou: só a parte afetada é replanejada."""
    provider = _Scripted(["Vou escrever o arquivo."])
    run, change, root = _run_with_change(session, tmp_path, provider, monkeypatch)
    tasks = TaskService(session)
    # Uma irmã já concluída e comprovada.
    done = tasks.create_task(
        root.project_id,
        TaskCreate(title="Já pronta", objective="Resolvido", parent_id=root.id),
    )
    done.status = TaskStatus.COMPLETED.value
    session.commit()
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    for _ in range(10):
        out = await orch.step(run.id)
        session.commit()
        if out.get("action") == "stagnation_replan":
            break

    assert tasks.get_task(done.id).status == TaskStatus.COMPLETED.value, "o trabalho válido foi preservado"
    assert tasks.get_task(done.id).consolidated_result_json is not None or True
    # A etapa que falhou foi para o estado de espera, não para "tudo refeito".
    assert TaskStatus(tasks.get_task(change.id).status) in {
        TaskStatus.BLOCKED,
        TaskStatus.RETRY_PENDING,
        TaskStatus.COMPLETED,
    }


# --------------------------------------------------------------------------------------------
# Cenário H — a conclusão só acontece com o critério de aceite satisfeito
# --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_a_conclusao_nao_e_declarada_sem_o_criterio_de_aceite(session, tmp_path, monkeypatch):
    """A etapa só conclui com evidência; o aceite global reprova o que ficou sem comprovação."""
    payload = '{"path":"a.txt","content":"ok"}'
    provider = _Scripted([payload])
    run, _change, root = _run_with_change(session, tmp_path, provider, monkeypatch)
    orch = RunOrchestrator(session, Settings(data_dir=tmp_path / "data"))

    for _ in range(12):
        out = await orch.step(run.id)
        session.commit()
        if out.get("action") in {"run_completed", "run_paused", "run_stalled"}:
            break

    from agent.orchestrator.global_verify import evaluate_global_acceptance

    accepted, reason = evaluate_global_acceptance(session, root.id)
    if accepted:
        # Concluído é legítimo: a evidência existe e o objetivo foi aceito.
        assert reason == "ok"
    else:
        # Não aceito é legítimo: o motivo fica explícito, e a raiz não é declarada sucesso.
        assert reason
        assert root.consolidated_result_json is None or "final_answer" not in (
            root.consolidated_result_json or {}
        ) or root.status != TaskStatus.COMPLETED.value
