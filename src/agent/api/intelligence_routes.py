"""
Arquivo: src/agent/api/intelligence_routes.py
Nome: intelligence_routes.py
Propósito: rotas unificadas de inteligência e observabilidade (métricas, telemetria, grafo cognitivo, benchmarks, diagnósticos).
Responsabilidade: camada de apresentação/transport — valida, delega e serializa; a regra de negócio vive nos serviços de inteligência.
Componentes: router, metrics_overview, metrics_run, metrics_project, metrics_models, metrics_timeline, telemetry_events, telemetry_event_detail, run_snapshot_telemetry, graph_architecture, graph_run, graph_run_history, benchmarks_list, benchmarks_create, benchmarks_get, benchmarks_run, benchmarks_results, benchmarks_compare, diagnostics_list, diagnostics_get.
Dependências: agent.api.deps, agent.intelligence.*, agent.persistence.models, fastapi, uuid.
Observações: todos os endpoints consomem serviços de inteligência, nunca o frontend diretamente.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agent.api.deps import db_session, read_settings
from agent.config import Settings
from agent.intelligence import (
    AnalyticsService,
    BenchmarkEngine,
    CognitiveGraph,
    DiagnosticEngine,
    TelemetryService,
)
from agent.learning.calibration import (
    CalibrationDecision,
    CalibrationMetrics,
    create_calibration_engine,
    create_calibration_store,
)
from agent.learning.capability_discovery import discover_capabilities
from agent.learning.profiles import create_profile_catalog, ProfileLimit
from agent.persistence.models import (
    BenchmarkExecutionModel,
    BenchmarkScenarioModel,
    ExecutionRunModel,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


def _calibration_store(settings: Settings):
    """Armazenamento de calibração ligado ao banco aditivo `data/calibration.db`."""
    return create_calibration_store(str(settings.data_dir / "calibration.db"))


# ── Capacidades e perfis ────────────────────────────────────────────────────

@router.get("/capabilities")
def capabilities(
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Capacidades observadas do provedor conectado e do ambiente.

    Campos não verificáveis são reportados como `desconhecido`/`None`; nada é
    presumido a partir da configuração declarada.
    """
    return discover_capabilities(settings).to_dict()


@router.get("/profiles")
def profiles(
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Perfis operacionais disponíveis e seus limites (após aplicação dos globais)."""
    catalog = create_profile_catalog(settings)
    return {
        "work_types": catalog.work_types(),
        "profiles": {
            work_type: {
                "description": catalog.profile_for(work_type).description,
                "requires_model": catalog.profile_for(work_type).requires_model,
                "deterministic_first": catalog.profile_for(work_type).deterministic_first,
                "limit": {
                    "context_budget": catalog.profile_for(work_type).limit.context_budget,
                    "output_reserve": catalog.profile_for(work_type).limit.output_reserve,
                    "decomposition_granularity": catalog.profile_for(
                        work_type
                    ).limit.decomposition_granularity,
                    "max_recursion_depth": catalog.profile_for(
                        work_type
                    ).limit.max_recursion_depth,
                    "max_attempts": catalog.profile_for(work_type).limit.max_attempts,
                    "max_inspections": catalog.profile_for(work_type).limit.max_inspections,
                    "max_tool_iterations": catalog.profile_for(
                        work_type
                    ).limit.max_tool_iterations,
                    "max_tool_calls": catalog.profile_for(work_type).limit.max_tool_calls,
                    "verification_intensity": catalog.profile_for(
                        work_type
                    ).limit.verification_intensity,
                    "skills_selected": catalog.profile_for(
                        work_type
                    ).limit.skills_selected,
                    "max_model_calls": catalog.profile_for(work_type).limit.max_model_calls,
                    "timeout_sec": catalog.profile_for(work_type).limit.timeout_sec,
                },
            }
            for work_type in catalog.work_types()
        },
    }


# ── Calibração adaptativa ───────────────────────────────────────────────────

class CalibrationChangeIn(BaseModel):
    work_type: str
    parameter: str
    previous_value: Any
    new_value: Any
    origin: str = "manual"
    justification: str
    hypothesis: str
    scenario: str | None = None
    version: int = 1


class CalibrationEvaluateIn(BaseModel):
    change_id: str
    champion: CalibrationMetrics
    challenger: CalibrationMetrics
    samples: int
    reason: str | None = None


@router.get("/calibration/history")
def calibration_history(
    work_type: str | None = Query(default=None),
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Histórico de mudanças e decisões de calibração (campeão/desafiador)."""
    engine = create_calibration_engine(_calibration_store(settings))
    return engine.history(work_type=work_type)


@router.post("/calibration/change")
def calibration_change(
    payload: CalibrationChangeIn,
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Registra uma mudança candidata de calibração."""
    from uuid import uuid4

    from agent.learning.calibration import CalibrationChange

    change = CalibrationChange(
        id=str(uuid4()),
        work_type=payload.work_type,
        parameter=payload.parameter,
        previous_value=payload.previous_value,
        new_value=payload.new_value,
        origin=payload.origin,
        justification=payload.justification,
        hypothesis=payload.hypothesis,
        scenario=payload.scenario,
        version=payload.version,
    )
    engine = create_calibration_engine(_calibration_store(settings))
    engine.register_change(change)
    return {"id": change.id, "work_type": change.work_type, "active": change.active}


@router.post("/calibration/evaluate")
def calibration_evaluate(
    payload: CalibrationEvaluateIn,
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Avalia se o desafiador substitui o campeão (promover / reverter / manter / bloquear)."""
    engine = create_calibration_engine(_calibration_store(settings))
    record = engine.evaluate(
        change_id=payload.change_id,
        champion=payload.champion,
        challenger=payload.challenger,
        samples=payload.samples,
        reason=payload.reason,
    )
    return {
        "id": record.id,
        "change_id": record.change_id,
        "decision": record.decision,
        "confidence": record.confidence,
        "improvement": record.improvement,
        "regression": record.regression,
        "samples": record.samples,
        "applied_at": record.applied_at,
        "reason": record.reason,
    }


@router.post("/calibration/rollback/{change_id}")
def calibration_rollback(
    change_id: str,
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Desativa uma mudança de calibração (rollback ao campeão anterior)."""
    engine = create_calibration_engine(_calibration_store(settings))
    ok = engine.rollback(change_id)
    if not ok:
        raise HTTPException(status_code=404, detail="mudança de calibração não encontrada")
    return {"change_id": change_id, "rolled_back": True}


# ── Painel de desempenho consolidado ────────────────────────────────────────

@router.get("/dashboard")
def dashboard(
    project_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
    settings: Settings = Depends(read_settings),
) -> dict[str, Any]:
    """Painel consolidado de desempenho: qualidade, eficiência, recursos e autonomia.

    Responde às questões: está melhorando? qual é o principal gargalo? qual estratégia
    produz melhores resultados? qual perfil é mais eficiente? quais falhas são mais
    frequentes? quais ajustes automáticos foram aplicados e com qual impacto? como está
    o desempenho do modelo de referência?
    """
    analytics = AnalyticsService(session)
    overview = analytics.overview(project_id=project_id)
    inference = overview.get("inference", {})
    efficiency = overview.get("efficiency", {})
    resources = overview.get("resources", {})
    models_used = overview.get("models_used", {})

    # Gargalo principal: maior taxa de erro/timeout entre provedores e maior latência.
    by_provider = inference.get("by_provider", {})
    bottleneck_provider = None
    bottleneck_metric = None
    if by_provider:
        worst = max(
            by_provider.items(),
            key=lambda item: item[1]["error_rate"] + item[1]["timeout_rate"],
        )
        bottleneck_provider, bottleneck_metric = worst

    # Falhas mais frequentes via diagnóstico (quando há diagnósticos criados).
    diag_engine = DiagnosticEngine(session)
    diag_summary = diag_engine.get_summary(run_id=None)

    # Histórico de calibração: ajustes aplicados e impacto.
    cal_engine = create_calibration_engine(_calibration_store(settings))
    cal_history = cal_engine.history()
    applied = [
        r
        for r in cal_history["records"]
        if r["decision"] == CalibrationDecision.PROMOTE
    ]

    return {
        "project_id": str(project_id) if project_id else None,
        "melhorando": {
            "taxa_conclusao": overview.get("completion_rate"),
            "runs_concluidas": overview.get("runs_completed"),
            "runs_falharam": overview.get("runs_failed"),
            "runs_ativas": overview.get("runs_active"),
        },
        "gargalo_principal": {
            "provedor": bottleneck_provider,
            "taxa_erro": bottleneck_metric["error_rate"] if bottleneck_metric else None,
            "taxa_timeout": bottleneck_metric["timeout_rate"] if bottleneck_metric else None,
            "latencia_p95_ms": inference.get("duration_ms", {}).get("p95"),
            "categoria_diagnostico_mais_frequente": (
                max(diag_summary.get("by_category", {}).items(), key=lambda i: i[1])[0]
                if diag_summary.get("by_category")
                else None
            ),
        },
        "estrategia_mais_eficiente": {
            "tokens_por_tarefa_concluida": efficiency.get("tokens_per_completed_task"),
            "chamadas_por_tarefa_concluida": efficiency.get("calls_per_completed_task"),
            "taxa_progresso": efficiency.get("progress_rate"),
            "chamadas_sem_progresso": efficiency.get("calls_without_progress"),
            "recuperacoes": efficiency.get("recovery_count"),
        },
        "perfil_configuracao": {
            "provedor_padrao": settings.default_provider,
            "modelo_padrao": settings.default_model_id,
            "modelos_usados": models_used,
            "inferencias_concorrentes": settings.max_concurrent_inferences,
        },
        "falhas_mais_frequentes": {
            "diagnosticos_por_categoria": diag_summary.get("by_category", {}),
            "diagnosticos_por_severidade": diag_summary.get("by_severity", {}),
            "taxa_erro_inferencia": inference.get("error_rate"),
            "taxa_timeout_inferencia": inference.get("timeout_rate"),
        },
        "ajustes_automaticos": {
            "aplicados": len(applied),
            "historico": [
                {
                    "mudanca": r["change_id"],
                    "decisao": r["decision"],
                    "confianca": r["confidence"],
                    "melhoria_relativa": r["improvement"],
                    "regressao": r["regression"],
                    "amostras": r["samples"],
                    "aplicado_em": r["applied_at"],
                    "motivo": r["reason"],
                }
                for r in applied
            ],
        },
        "desempenho_modelo_referencia": {
            "modelo": settings.default_model_id,
            "provedor": settings.default_provider,
            "chamadas": inference.get("calls"),
            "concluidas": inference.get("completed"),
            "falhas": inference.get("failed"),
            "timeouts": inference.get("timed_out"),
            "latencia_p50_ms": inference.get("duration_ms", {}).get("p50"),
            "latencia_p95_ms": inference.get("duration_ms", {}).get("p95"),
            "tokens_por_segundo_p50": inference.get("tokens_per_second", {}).get("p50"),
            "tokens_por_segundo_p95": inference.get("tokens_per_second", {}).get("p95"),
            "qualidade_medicao": "estimada",
        },
        "recursos": {
            "cpu_percent_medio": resources.get("cpu_percent", {}).get("avg"),
            "ram_mb_maximo": resources.get("ram_mb", {}).get("max"),
            "vram_mb_maximo": resources.get("vram_mb", {}).get("max"),
            "amostras": resources.get("samples"),
        },
    }



# ── Pydantic schemas ──────────────────────────────────────────────────────

class BenchmarkScenarioIn(BaseModel):
    id: str
    version: int = 1
    name: str
    description: str | None = None
    category: str
    difficulty: str
    prompt: str
    context_initial: dict[str, Any] | None = None
    tools_allowed: list[str] | None = None
    token_budget: int | None = None
    time_limit_sec: int | None = None
    acceptance_criteria: list[str] | None = None
    validation_tests: list[str] | None = None
    expected_result: dict[str, Any] | None = None
    is_active: bool = True


class BenchmarkRunIn(BaseModel):
    scenario_id: str
    provider: str
    model_id: str | None = None
    config: dict[str, Any] | None = None


class DiagnosticIn(BaseModel):
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    category: str
    severity: str = "media"
    state: str = "open"
    evidence: dict[str, Any] | None = None
    metric_affected: str | None = None
    observed_period: dict[str, str] | None = None
    probable_cause: str | None = None
    confidence_level: str = "medio"
    recommendation: str | None = None
    recommendation_state: str = "pendente"
    kind: str = "hipotese"


# ── Helpers ───────────────────────────────────────────────────────────────

def _run_or_404(session: Session, run_id: uuid.UUID) -> ExecutionRunModel:
    run = session.get(ExecutionRunModel, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrada")
    return run


def _scenario_or_404(session: Session, scenario_id: str) -> BenchmarkScenarioModel:
    stmt = select(BenchmarkScenarioModel).where(BenchmarkScenarioModel.scenario_id == scenario_id)
    row = session.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=404, detail="cenário não encontrado")
    return row


from sqlalchemy import select  # noqa: E402


# ── Metrics ───────────────────────────────────────────────────────────────

@router.get("/metrics/overview")
def metrics_overview(
    project_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Visão geral agregada: runs recentes, taxa de conclusão, tokens, modelos, recursos."""
    analytics = AnalyticsService(session)
    return analytics.overview(project_id=project_id)


@router.get("/metrics/runs/{run_id}")
def metrics_run(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Métricas detalhadas de uma run: tokens, contexto, inferência, recursos, eficiência."""
    _run_or_404(session, run_id)
    analytics = AnalyticsService(session)
    return {
        "run_id": str(run_id),
        "tokens": analytics.token_metrics(run_id=run_id),
        "context": analytics.context_metrics(run_id=run_id),
        "inference": analytics.inference_metrics(run_id=run_id),
        "resources": analytics.resource_metrics(run_id=run_id),
        "efficiency": analytics.efficiency_metrics(run_id=run_id),
    }


@router.get("/metrics/projects/{project_id}")
def metrics_project(
    project_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Métricas agregadas de um projeto."""
    analytics = AnalyticsService(session)
    return analytics.overview(project_id=project_id)


@router.get("/metrics/models")
def metrics_models(
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Uso de modelos por run: contagem e distribuição."""
    analytics = AnalyticsService(session)
    # Usa o overview sem filtro de projeto e extrai modelos usados.
    overview_data = analytics.overview()
    return {"models_used": overview_data.get("models_used", {})}


@router.get("/metrics/timeline")
def metrics_timeline(
    run_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Linha do tempo de métricas agregadas por período."""
    analytics = AnalyticsService(session)
    return {
        "run_id": str(run_id) if run_id else None,
        "project_id": str(project_id) if project_id else None,
        "tokens": analytics.token_metrics(run_id=run_id, project_id=project_id),
        "inference": analytics.inference_metrics(run_id=run_id, project_id=project_id),
        "context": analytics.context_metrics(run_id=run_id, project_id=project_id),
        "resources": analytics.resource_metrics(run_id=run_id, project_id=project_id),
        "efficiency": analytics.efficiency_metrics(run_id=run_id, project_id=project_id),
    }


# ── Telemetry ─────────────────────────────────────────────────────────────

@router.get("/events")
def telemetry_events(
    run_id: uuid.UUID | None = Query(default=None),
    after: int = Query(default=0),
    limit: int = Query(default=200, le=1000),
    types: str | None = Query(default=None),
    task_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Eventos de telemetria persistidos, paginados, com filtro por tipo e tarefa."""
    from agent.observability.snapshot import events_page

    if run_id is not None:
        _run_or_404(session, run_id)
    return events_page(
        session,
        run_id=run_id or uuid.UUID(int=0),
        after=after,
        limit=limit,
        types=types.split(",") if types else None,
        task_id=task_id,
    )


@router.get("/events/{event_id}")
def telemetry_event_detail(
    event_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Detalhe de um evento de telemetria pelo identificador."""
    from agent.persistence.models import EventLogModel

    row = session.get(EventLogModel, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="evento não encontrado")
    from agent.observability.contracts import envelope_from_row

    return envelope_from_row(row)


@router.get("/runs/{run_id}/snapshot")
def run_snapshot_telemetry(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Foto completa do estado de uma run (run, tarefas, eventos, operações ao vivo)."""
    _run_or_404(session, run_id)
    from agent.observability.snapshot import run_snapshot

    return run_snapshot(session, run_id)


# ── Cognitive Graph ───────────────────────────────────────────────────────

@router.get("/graph/architecture")
def graph_architecture(
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Topologia de componentes do grafo cognitivo (sem execução específica)."""
    graph = CognitiveGraph(session, run_id=None)
    return graph.to_dict()


@router.get("/graph/runs/{run_id}")
def graph_run(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Grafo cognitivo de uma run específica, com estados e arestas percorridas."""
    _run_or_404(session, run_id)
    graph = CognitiveGraph(session, run_id=run_id)
    return graph.to_dict()


@router.get("/graph/runs/{run_id}/history")
def graph_run_history(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Histórico de eventos do grafo cognitivo de uma run."""
    _run_or_404(session, run_id)
    graph = CognitiveGraph(session, run_id=run_id)
    return {
        "run_id": str(run_id),
        "event_history": graph.event_history,
        "nodes": [n.to_dict() for n in graph.nodes.values()],
        "edges": [e.to_dict() for e in graph.edges.values()],
    }


# ── Benchmarks ────────────────────────────────────────────────────────────

@router.get("/benchmarks")
def benchmarks_list(
    active_only: bool = Query(default=True),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Lista cenários de benchmark disponíveis."""
    engine = BenchmarkEngine(session)
    scenarios = engine.list_scenarios(active_only=active_only)
    return {
        "scenarios": [
            {
                "id": s.id,
                "version": s.version,
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "difficulty": s.difficulty,
                "is_active": s.is_active,
            }
            for s in scenarios
        ],
        "count": len(scenarios),
    }


@router.post("/benchmarks")
def benchmarks_create(
    payload: BenchmarkScenarioIn,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Cria ou atualiza um cenário de benchmark."""
    from agent.intelligence.benchmarks import BenchmarkScenario

    scenario = BenchmarkScenario(
        id=payload.id,
        version=payload.version,
        name=payload.name,
        description=payload.description or "",
        category=payload.category,
        difficulty=payload.difficulty,
        prompt=payload.prompt,
        context_initial=payload.context_initial,
        tools_allowed=payload.tools_allowed,
        token_budget=payload.token_budget,
        time_limit_sec=payload.time_limit_sec,
        acceptance_criteria=payload.acceptance_criteria or [],
        validation_tests=payload.validation_tests or [],
        expected_result=payload.expected_result,
        is_active=payload.is_active,
    )
    engine = BenchmarkEngine(session)
    engine.create_scenario(scenario)
    return {"id": scenario.id, "version": scenario.version, "name": scenario.name}


@router.get("/benchmarks/{benchmark_id}")
def benchmarks_get(
    benchmark_id: str,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Detalhe de um cenário de benchmark."""
    engine = BenchmarkEngine(session)
    scenario = engine.get_scenario(benchmark_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="cenário não encontrado")
    return {
        "id": scenario.id,
        "version": scenario.version,
        "name": scenario.name,
        "description": scenario.description,
        "category": scenario.category,
        "difficulty": scenario.difficulty,
        "prompt": scenario.prompt,
        "context_initial": scenario.context_initial,
        "tools_allowed": scenario.tools_allowed,
        "token_budget": scenario.token_budget,
        "time_limit_sec": scenario.time_limit_sec,
        "acceptance_criteria": scenario.acceptance_criteria,
        "validation_tests": scenario.validation_tests,
        "expected_result": scenario.expected_result,
        "is_active": scenario.is_active,
    }


@router.post("/benchmarks/{benchmark_id}/run")
def benchmarks_run(
    benchmark_id: str,
    payload: BenchmarkRunIn,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Executa um cenário de benchmark com um modelo/configuração."""
    engine = BenchmarkEngine(session)
    scenario = engine.get_scenario(benchmark_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="cenário não encontrado")

    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    result = loop.run_until_complete(
        engine.run_scenario(
            scenario_id=benchmark_id,
            provider=payload.provider,
            model_id=payload.model_id,
            config=payload.config,
        )
    )
    return result.to_dict()


@router.get("/benchmarks/{benchmark_id}/results")
def benchmarks_results(
    benchmark_id: str,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Resultados de todas as execuções de um cenário de benchmark."""
    engine = BenchmarkEngine(session)
    executions = engine.list_executions(scenario_id=benchmark_id)
    return {
        "scenario_id": benchmark_id,
        "executions": [
            {
                "execution_id": e.id,
                "provider": e.provider,
                "model_id": e.model_id,
                "status": e.status,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                "duration_sec": e.duration_sec,
                "error": e.error,
            }
            for e in executions
        ],
    }


@router.get("/benchmarks/compare")
def benchmarks_compare(
    scenario_id: str = Query(default=...),
    execution_ids: str | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Compara múltiplas execuções de um mesmo cenário."""
    engine = BenchmarkEngine(session)
    ids = execution_ids.split(",") if execution_ids else None
    return engine.compare(scenario_id=scenario_id, execution_ids=ids)


# ── Diagnostics ───────────────────────────────────────────────────────────

@router.get("/diagnostics")
def diagnostics_list(
    run_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    state: str | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Lista diagnósticos com filtros opcionais."""
    engine = DiagnosticEngine(session)
    diagnostics = engine.list_diagnostics(
        run_id=run_id, category=category, severity=severity, state=state
    )
    return {
        "diagnostics": [d.to_dict() for d in diagnostics],
        "count": len(diagnostics),
    }


@router.get("/diagnostics/summary")
def diagnostics_summary(
    run_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Resumo dos diagnósticos por categoria, severidade e estado."""
    engine = DiagnosticEngine(session)
    return engine.get_summary(run_id=run_id)


@router.get("/diagnostics/{diagnostic_id}")
def diagnostics_get(
    diagnostic_id: str,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Detalhe de um diagnóstico."""
    engine = DiagnosticEngine(session)
    diagnostic = engine.get_diagnostic(diagnostic_id)
    if diagnostic is None:
        raise HTTPException(status_code=404, detail="diagnóstico não encontrado")
    return diagnostic.to_dict()


@router.post("/diagnostics")
def diagnostics_create(
    payload: DiagnosticIn,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Cria um novo diagnóstico manualmente."""
    from agent.intelligence.diagnostics import Diagnostic

    diagnostic = Diagnostic(
        id=f"diag-{uuid.uuid4().hex[:12]}",
        run_id=payload.run_id,
        task_id=payload.task_id,
        category=payload.category,
        severity=payload.severity,
        state=payload.state,
        evidence=payload.evidence or {},
        metric_affected=payload.metric_affected,
        observed_period=payload.observed_period,
        probable_cause=payload.probable_cause,
        confidence_level=payload.confidence_level,
        recommendation=payload.recommendation,
        recommendation_state=payload.recommendation_state,
        kind=payload.kind,
    )
    engine = DiagnosticEngine(session)
    engine.create_diagnostic(diagnostic)
    return diagnostic.to_dict()


@router.post("/diagnostics/runs/{run_id}/analyze")
def diagnostics_analyze_run(
    run_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Executa diagnóstico determinístico sobre uma run."""
    _run_or_404(session, run_id)
    engine = DiagnosticEngine(session)
    diagnostics = engine.analyze_run(run_id)
    return {
        "run_id": str(run_id),
        "diagnostics": [d.to_dict() for d in diagnostics],
        "count": len(diagnostics),
    }