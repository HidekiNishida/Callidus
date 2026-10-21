"""
Arquivo: tests/test_token_budget.py
Nome: test_token_budget.py
Propósito: verificar a contabilização por inferência, o teto da execução e a memória operacional.
Responsabilidade: camada de testes — ciclos de ferramentas, ausência de uso, reserva, retomada e compactação.
Componentes: livro-razão, controlador de orçamento, memória operacional e demonstrativo.
Dependências: agent.orchestrator (ledger, budget_gate, inference_usage), agent.memory.operational, agent.context.budget, agent.persistence.
Observações: banco temporário e provedor falso; nenhuma chamada de rede.
"""
from __future__ import annotations

import pytest

from agent.config import Settings
from agent.context.budget import compact_for_pressure, estimate_tokens
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.memory.operational import child_summary, recall, render_for_prompt, upsert_operational
from agent.observability.emitter import observe
from agent.orchestrator.atomizer import should_decompose_further
from agent.orchestrator.budget_gate import assess_inference, grant_budget, use_budget_settings
from agent.orchestrator.execution.providers import apply_provider_usage
from agent.orchestrator.inference_usage import fold_usage, usage_from_response
from agent.orchestrator.ledger import record_inference, run_spend
from agent.orchestrator.stagnation import effective_cap, limits_for
from agent.orchestrator.usage import remember_usage
from agent.orchestrator.usage_report import build_usage_view
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, InferenceRecordModel
from agent.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    LLMProvider,
    ModelProfile,
    ProviderCapabilities,
    ProviderTimeoutError,
)
from agent.providers.observed import observed_chat
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


def _world(tmp_path, *, tokens: int = 1000):
    """Cria projeto, tarefa e run com um teto de tokens pequeno."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="orcamento", root_path=str(tmp_path)))
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(title="Etapa", objective="corrigir o cálculo", acceptance_criteria="o resultado é 4"),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=task.id,
            config={"provider": "mock", "limits": {"tokens": tokens, "model_calls": 20}},
        ),
    )
    session.commit()
    return settings, session, project, task, run


class _CountingProvider(LLMProvider):
    """Provedor falso que informa um uso diferente a cada chamada."""

    name = "fake"
    supports_streaming = False

    def __init__(self, script: list[dict]):
        self._script = list(script)
        self.usage_log = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=False, usage_reporting=True)

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def _chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        step = self._script.pop(0)
        if step.get("error"):
            raise step["error"]
        response = ChatCompletionResponse(
            content=step.get("content", "ok"),
            prompt_tokens_estimate=step.get("prompt"),
            completion_tokens_estimate=step.get("completion"),
            raw=step.get("raw"),
            finish_reason=step.get("finish"),
            model="fake-model",
        )
        remember_usage(self, response.prompt_tokens_estimate, response.completion_tokens_estimate)
        return response


def test_missing_usage_is_not_zero():
    """Uso ausente não vira zero e não se soma ao total como se tivesse sido medido."""
    parsed = usage_from_response(
        ChatCompletionResponse(content="ok"),
        usage_reporting=True,
        estimated_prompt=12,
        estimated_completion=4,
    )
    assert parsed.measurement == "unavailable"
    assert parsed.prompt_tokens is None
    assert parsed.completion_tokens is None
    folded = fold_usage([])
    assert folded["prompt"]["value"] is None
    assert folded["spend"]["value"] is None


def test_cache_and_reasoning_stay_out_of_the_total():
    """Cache e raciocínio aparecem à parte e não são somados de novo na entrada ou na saída."""
    parsed = usage_from_response(
        ChatCompletionResponse(
            content="ok",
            prompt_tokens_estimate=100,
            completion_tokens_estimate=20,
            raw={
                "usage": {
                    "prompt_tokens_details": {"cached_tokens": 40},
                    "completion_tokens_details": {"reasoning_tokens": 15},
                }
            },
        ),
        usage_reporting=True,
        estimated_prompt=90,
        estimated_completion=20,
    )
    assert parsed.measurement == "exact"
    assert parsed.cache_read_tokens == 40
    assert parsed.reasoning_tokens == 15
    assert parsed.prompt_tokens == 100
    assert parsed.completion_tokens == 20


def test_partial_usage_keeps_the_missing_side(tmp_path):
    """Quando só a saída chega, a entrada continua ausente e a medição é parcial."""
    settings, session, _project, task, run = _world(tmp_path)
    record_inference(
        session,
        idempotency_key="parcial-1",
        run_id=run.id,
        task_id=task.id,
        project_id=task.project_id,
        purpose="operation",
        provider="fake",
        model_id="fake-model",
        status="completed",
        measurement="partial",
        prompt_tokens=None,
        completion_tokens=8,
        estimated_prompt_tokens=30,
        estimated_completion_tokens=8,
    )
    session.commit()
    from agent.orchestrator.ledger import records_for

    rows = records_for(session, run_id=run.id)
    folded = fold_usage(rows)
    assert folded["prompt"]["value"] is None
    assert folded["prompt"]["measurement"] == "unavailable"
    assert folded["completion"]["value"] == 8
    assert folded["spend"]["measurement"] == "partial"
    session.close()
    del settings


def test_same_key_is_not_counted_twice(tmp_path):
    """Repetir a gravação da mesma chamada não dobra o consumo."""
    _settings, session, _project, task, run = _world(tmp_path)
    fields = dict(
        run_id=run.id,
        task_id=task.id,
        project_id=task.project_id,
        purpose="operation",
        provider="fake",
        model_id="fake-model",
        status="completed",
        measurement="exact",
        prompt_tokens=50,
        completion_tokens=5,
        estimated_prompt_tokens=50,
        estimated_completion_tokens=5,
    )
    record_inference(session, idempotency_key="mesma-chamada", **fields)
    record_inference(session, idempotency_key="mesma-chamada", **fields)
    session.commit()
    spent, quality = run_spend(session, run.id)
    assert spent == 55
    assert quality == "exact"
    from agent.orchestrator.ledger import records_for

    assert len(records_for(session, run_id=run.id)) == 1
    session.close()


@pytest.mark.asyncio
async def test_tool_loop_keeps_every_model_call(tmp_path):
    """Três inferências no mesmo ciclo somam as três; a última não substitui as anteriores."""
    settings, session, _project, task, run = _world(tmp_path)
    provider = _CountingProvider(
        [
            {"prompt": 100, "completion": 10, "raw": {"usage": {"prompt_tokens_details": {"cached_tokens": 1}}}},
            {"prompt": 180, "completion": 12},
            {"prompt": 220, "completion": 9},
        ]
    )
    profile = ModelProfile(model_id="fake-model", context_limit=8192, input_budget=6000, output_reserve=128)
    request = ChatCompletionRequest(messages=[ChatMessage(role="user", content="olá")], profile=profile)
    with use_budget_settings(settings):
        with observe(session, run_id=run.id, project_id=task.project_id, task_id=task.id, agent="worker"):
            for _ in range(3):
                await observed_chat(provider, request, purpose="operation", stream=False)
    apply_provider_usage(task, provider)
    session.commit()
    usage = task.metadata_json["usage"]
    assert usage["prompt"] == 500
    assert usage["completion"] == 31
    assert usage["calls"] == 3
    assert usage["total"] == 531
    assert provider.last_usage is None
    spent, _quality = run_spend(session, run.id)
    assert spent == 531
    session.close()


@pytest.mark.asyncio
async def test_timeout_persists_without_inventing_tokens(tmp_path):
    """Timeout grava a chamada com uso indisponível, não com zero."""
    settings, session, _project, task, run = _world(tmp_path)
    provider = _CountingProvider([{"error": ProviderTimeoutError("demorou")}])
    profile = ModelProfile(model_id="fake-model", context_limit=8192, input_budget=6000, output_reserve=64)
    request = ChatCompletionRequest(messages=[ChatMessage(role="user", content="olá")], profile=profile)
    with use_budget_settings(settings):
        with observe(session, run_id=run.id, project_id=task.project_id, task_id=task.id):
            with pytest.raises(ProviderTimeoutError):
                await observed_chat(provider, request, purpose="operation", stream=False)
    from agent.orchestrator.ledger import records_for

    rows = records_for(session, run_id=run.id)
    assert len(rows) == 1
    assert rows[0].status == "timeout"
    assert rows[0].prompt_tokens is None
    assert rows[0].measurement == "unavailable"
    assert rows[0].estimated_prompt_tokens is not None
    session.close()


def test_resume_does_not_raise_the_token_cap(tmp_path):
    """Retomada não aumenta o teto de tokens. Só uma autorização explícita aumenta."""
    settings, session, _project, task, run = _world(tmp_path, tokens=1000)
    limits = limits_for(settings, run.config_json or {})
    assert effective_cap(limits, "tokens", resumes=3) == 1000
    session.add(
        EventLogModel(
            project_id=task.project_id,
            run_id=run.id,
            task_id=task.id,
            event_type="run.resumed",
            payload_json={},
        )
    )
    record_inference(
        session,
        idempotency_key="antes-da-retomada",
        run_id=run.id,
        task_id=task.id,
        project_id=task.project_id,
        purpose="operation",
        provider="fake",
        model_id="fake-model",
        status="completed",
        measurement="exact",
        prompt_tokens=800,
        completion_tokens=50,
        estimated_prompt_tokens=800,
        estimated_completion_tokens=50,
    )
    session.commit()
    with use_budget_settings(settings):
        blocked = assess_inference(
            session,
            run.id,
            purpose="operation",
            estimated_prompt=100,
            estimated_completion=20,
            provider="fake",
        )
        closing = assess_inference(
            session,
            run.id,
            purpose="final_answer",
            estimated_prompt=40,
            estimated_completion=20,
            provider="fake",
        )
    assert blocked.action == "pause"
    assert closing.action == "allow"
    granted = grant_budget(session, run, tokens=500, reason="continuar a etapa que faltou")
    session.commit()
    assert granted["authorized_tokens"] == 1500
    with use_budget_settings(settings):
        after = assess_inference(
            session,
            run.id,
            purpose="operation",
            estimated_prompt=100,
            estimated_completion=20,
            provider="fake",
        )
    assert after.authorized == 1500
    assert after.action != "pause"
    session.close()


def test_completion_reserve_blocks_implementation(tmp_path):
    """Implementação para na reserva; a conclusão ainda pode usar essa parcela."""
    settings, session, _project, task, run = _world(tmp_path, tokens=1000)
    record_inference(
        session,
        idempotency_key="quase-no-teto",
        run_id=run.id,
        task_id=task.id,
        project_id=task.project_id,
        purpose="operation",
        provider="fake",
        model_id="fake-model",
        status="completed",
        measurement="exact",
        prompt_tokens=860,
        completion_tokens=0,
        estimated_prompt_tokens=860,
        estimated_completion_tokens=10,
    )
    session.commit()
    with use_budget_settings(settings):
        work = assess_inference(
            session, run.id, purpose="operation", estimated_prompt=50, estimated_completion=10, provider="fake"
        )
        final = assess_inference(
            session, run.id, purpose="final_answer", estimated_prompt=50, estimated_completion=10, provider="fake"
        )
    assert work.action == "pause"
    assert work.reserve == 100
    assert final.action == "allow"
    session.close()


def test_pressure_keeps_acceptance_criteria():
    """A compactação por pressão não corta o critério de aceite e encolhe log dispensável."""
    criteria = "Critério único de aceite: " + ("abcde " * 200)
    kept = compact_for_pressure("critérios", criteria)
    assert "Critério único de aceite" in kept
    assert "caracteres" not in kept
    log = "\n".join(f"linha de log {index} com detalhe repetido demais" for index in range(80))
    shortened = compact_for_pressure("inspeção-anterior", log, limit=200)
    assert "caracteres" in shortened
    assert len(shortened) < len(log)
    assert estimate_tokens(shortened) < estimate_tokens(log)


def test_operational_memory_is_selective(tmp_path):
    """O prompt leva o resumo; o detalhe e o artefato só voltam na busca."""
    _settings, session, _project, task, _run = _world(tmp_path)
    child = TaskService(session).create_task(
        task.project_id,
        TaskCreate(title="Filha", objective="ajustar calc.py", parent_id=task.id, acceptance_criteria="retorna 4"),
    )
    from agent.memory.operational import remember_artifact, remember_detail

    upsert_operational(session, child, status_note="li calc.py")
    remember_detail(
        session,
        child,
        title="Decisão sobre calc.py",
        body="A função soma dois inteiros e o teste espera 4.",
        facts={"file": "calc.py", "state": "confirmado"},
    )
    remember_artifact(
        session,
        child,
        title="Log da verificação",
        ref="snapshot:abc",
        summary="pytest passou em test_calc",
    )
    session.commit()
    prompt = render_for_prompt(session, child)
    assert "ajustar calc.py" in prompt
    assert "pytest passou" not in prompt
    found = recall(session, project_id=task.project_id, file="calc.py")
    assert any(row.kind == "task_detail" for row in found)
    summary = child_summary(session, child)
    assert "Filha" in summary
    assert "pytest passou" not in summary
    assert "memory:" in summary
    session.close()


def test_simple_task_is_not_split_just_because_metadata_grew():
    """Metadado inchado não divide uma etapa de um único resultado."""
    meta = {f"chave-{index}": index for index in range(12)}
    meta["usage"] = {"prompt": 10, "completion": 2, "total": 12}
    assert not should_decompose_further(
        objective="corrigir um nome",
        metadata=meta,
        kind="OBJECTIVE",
        attempt_count=0,
        has_children=False,
    )


def test_usage_view_separates_estimate_and_reported(tmp_path):
    """O demonstrativo não apresenta a estimativa de janela como uso informado."""
    _settings, session, _project, task, run = _world(tmp_path)
    record_inference(
        session,
        idempotency_key="vista-1",
        run_id=run.id,
        task_id=task.id,
        project_id=task.project_id,
        purpose="operation",
        provider="fake",
        model_id="fake-model",
        status="completed",
        measurement="exact",
        prompt_tokens=40,
        completion_tokens=6,
        reasoning_tokens=2,
        estimated_prompt_tokens=35,
        estimated_completion_tokens=8,
        agent="worker",
    )
    session.commit()
    view = build_usage_view(session, run_id=run.id, task_id=task.id)
    assert view["call"]["reported_input_tokens"]["value"] == 40
    assert view["call"]["reported_input_tokens"]["measurement"] == "exact"
    assert view["accumulated"]["prompt_tokens"]["value"] == 40
    assert view["accumulated"]["reasoning_tokens"]["value"] == 2
    assert view["accumulated"]["spend"]["value"] == 46
    assert view["budget"]["authorized_tokens"] == 1000
    assert view["consistency"]["match"] is True
    by_purpose = {item["key"]: item for item in view["accumulated"]["by_purpose"]}
    assert by_purpose["operation"]["calls"] == 1
    session.close()


def test_migration_keeps_rows_and_adds_the_ledger(tmp_path):
    """Reinicializar o banco não apaga inferências e a coluna nova do snapshot existe."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="mig", root_path=str(tmp_path)))
    task = TaskService(session).create_task(project.id, TaskCreate(title="t", objective="o"))
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=task.id, config={"provider": "mock"})
    )
    record_inference(
        session,
        idempotency_key="mig-1",
        run_id=run.id,
        task_id=task.id,
        project_id=project.id,
        purpose="operation",
        provider="mock",
        status="completed",
        measurement="exact",
        prompt_tokens=3,
        completion_tokens=1,
    )
    session.commit()
    run_id = run.id
    session.close()
    engine.dispose()

    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    from sqlalchemy import select

    found = list(session.scalars(select(InferenceRecordModel)).all())
    assert len(found) == 1
    assert found[0].prompt_tokens == 3
    assert run_spend(session, run_id)[0] == 4
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(context_snapshots)")}
    assert "categories_json" in cols
    session.close()
