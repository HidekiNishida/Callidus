"""
Arquivo: src/agent/orchestrator/budget_gate.py
Nome: budget_gate.py
Propósito: decidir, antes de cada inferência, se o orçamento da execução ainda comporta a chamada.
Responsabilidade: camada de aplicação — previsão, reserva de conclusão e pausa segura.
Componentes: BudgetDecision, BudgetExhausted, assess_inference, grant_budget, use_budget_settings.
Dependências: agent.config, agent.orchestrator.ledger, agent.orchestrator.stagnation, agent.persistence.models.
Observações: a janela de contexto do modelo e o orçamento acumulado da execução são limites diferentes.
A retomada não aumenta o teto de tokens; isso exige uma autorização gravada.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.orchestrator.inference_usage import estimate_cost
from agent.orchestrator.ledger import records_for, run_spend
from agent.orchestrator.stagnation import effective_cap, limits_for, resume_count
from agent.persistence.models import EventLogModel, ExecutionRunModel, InferenceRecordModel

_SETTINGS: ContextVar[Settings | None] = ContextVar("budget_settings", default=None)

PROTECTED_PURPOSES = frozenset(
    {"final_answer", "verify", "verification", "consolidation", "closing", "checkpoint", "summary"}
)


@contextmanager
def use_budget_settings(settings: Settings) -> Iterator[None]:
    """Fixa as configurações usadas pelo controlador durante um passo da execução.

    Args:
        settings: configurações da execução, inclusive as de teste.

    Yields:
        Nada. O controlador lê estas configurações em vez do ambiente global.
    """
    token = _SETTINGS.set(settings)
    try:
        yield
    finally:
        _SETTINGS.reset(token)


def active_settings() -> Settings:
    """Configurações do passo atual, ou as do processo quando não há passo.

    Returns:
        O objeto de configuração a usar nos limites.
    """
    return _SETTINGS.get() or get_settings()


@dataclass
class BudgetDecision:
    """Resultado da consulta feita antes da inferência.

    Atributos:
        action: `allow`, `warn`, `reduce` ou `pause`.
        level: faixa de consumo (`normal`, `elevated`, `reduce`, `stop`).
        reason: frase que explica a decisão.
        spent: consumo já contabilizado.
        authorized: teto de tokens da execução, com autorizações explícitas.
        reserve: parcela protegida para concluir.
        ceiling: teto das inferências que não são de conclusão.
        estimate: tamanho previsto desta chamada.
        measurement: qualidade do consumo já contabilizado.
        limit_key: limite que motivou uma pausa.
        label: nome legível desse limite.
        resumes: retomadas já feitas; não aumentam o teto de tokens.
        usage: consumo auxiliar (chamadas, segundos).
        next_action: o que o usuário pode fazer para continuar.
    """

    action: str
    level: str
    reason: str
    spent: int
    authorized: int
    reserve: int
    ceiling: int
    estimate: int
    measurement: str
    limit_key: str
    label: str
    resumes: int
    usage: dict[str, Any]
    next_action: str


class BudgetExhausted(RuntimeError):
    """A próxima inferência não essencial estouraria o orçamento autorizado."""

    def __init__(self, decision: BudgetDecision) -> None:
        """Guarda a decisão que impediu a chamada.

        Args:
            decision: decisão do controlador, com o motivo e a próxima ação.
        """
        super().__init__(decision.reason)
        self.decision = decision

    def as_hit(self) -> dict[str, Any]:
        """Formato que a pausa do run já sabe gravar.

        Returns:
            O dicionário do limite atingido.
        """
        return {
            "limit": self.decision.limit_key,
            "label": self.decision.label,
            "value": self.decision.spent,
            "max": self.decision.ceiling or self.decision.authorized,
            "resumes": self.decision.resumes,
            "usage": self.decision.usage,
            "reserve": self.decision.reserve,
            "level": self.decision.level,
        }

    @property
    def next_action(self) -> str:
        """Orientação gravada junto com a pausa."""
        return self.decision.next_action

    @property
    def reason(self) -> str:
        """Motivo curto da pausa."""
        return str(self.decision.reason)


def _ratio(value: Any, default: float) -> float:
    """Lê uma fração de configuração, caindo no padrão quando o valor é inválido.

    Args:
        value: valor informado.
        default: fração usada quando o valor não é um número utilizável.

    Returns:
        A fração entre 0 e 1, ou o padrão.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0 or number >= 1:
        return default
    return number


def policy_ratios(settings: Settings, config: dict[str, Any]) -> dict[str, float]:
    """Faixas e reserva. Valores fora de ordem voltam ao ponto de partida.

    Args:
        settings: configurações do processo.
        config: configuração da execução; a chave `budget` sobrescreve as faixas.

    Returns:
        `warn`, `reduce`, `stop` e `reserve`.
    """
    custom = config.get("budget") if isinstance(config.get("budget"), dict) else {}
    warn = _ratio(custom.get("warn", settings.budget_warn_ratio), 0.70)
    reduce = _ratio(custom.get("reduce", settings.budget_reduce_ratio), 0.85)
    stop = _ratio(custom.get("stop", settings.budget_stop_ratio), 0.90)
    reserve = _ratio(custom.get("reserve", settings.budget_reserve_ratio), 0.10)
    if not (warn < reduce < stop):
        warn, reduce, stop = 0.70, 0.85, 0.90
    if reserve >= 1 - stop:
        reserve = round(1 - stop, 4)
    return {"warn": warn, "reduce": reduce, "stop": stop, "reserve": reserve}


def _allowance(settings: Settings, config: dict[str, Any]) -> int:
    """Unidades de cota que cada retomada concede aos limites que não são de token.

    Args:
        settings: configurações do processo.
        config: configuração da execução.

    Returns:
        A permissão de retomada, no mínimo zero.
    """
    raw = config.get("resume_limit_allowance", settings.resume_limit_allowance)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return max(0, int(settings.resume_limit_allowance))


def assess_inference(
    session: Session,
    run_id: uuid.UUID,
    *,
    purpose: str,
    estimated_prompt: int,
    estimated_completion: int,
    provider: str = "",
) -> BudgetDecision:
    """Prevê a chamada e escolhe permitir, alertar, compactar ou pausar.

    Args:
        session: sessão do banco.
        run_id: execução que pagaria a chamada.
        purpose: finalidade da inferência.
        estimated_prompt: estimativa local da entrada.
        estimated_completion: reserva prevista de saída.
        provider: provedor, usado só na estimativa de custo.

    Returns:
        A decisão. `pause` impede a chamada antes de ela acontecer.
    """
    settings = active_settings()
    run = session.get(ExecutionRunModel, run_id)
    config = dict((run.config_json if run else None) or {})
    limits = limits_for(settings, config)
    ratios = policy_ratios(settings, config)
    resumes = resume_count(session, run) if run is not None else 0
    allowance = _allowance(settings, config)
    spent, measurement = run_spend(session, run_id)
    spent_value = int(spent or 0)
    authorized = int(limits.get("tokens") or 0)
    reserve = int(authorized * ratios["reserve"]) if authorized else 0
    ceiling = max(0, authorized - reserve) if authorized else 0
    estimate = max(0, int(estimated_prompt or 0)) + max(0, int(estimated_completion or 0))
    rows = records_for(session, run_id=run_id)
    calls = len(rows)
    call_cap = effective_cap(limits, "model_calls", resumes, allowance)
    seconds_cap = effective_cap(limits, "seconds", resumes, allowance)
    started = run.created_at if run is not None else None
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = int((datetime.now(timezone.utc) - started).total_seconds()) if started else 0
    prices = config.get("prices") if isinstance(config.get("prices"), dict) else {}
    known_cost = 0.0
    cost_known = False
    for row in rows:
        if row.cost_usd is not None:
            known_cost += float(row.cost_usd)
            cost_known = True
    projected_cost, _ = estimate_cost(prices, provider, estimated_prompt, estimated_completion)
    cost_cap = config.get("max_cost_usd")
    try:
        cost_cap = float(cost_cap) if cost_cap is not None else None
    except (TypeError, ValueError):
        cost_cap = None
    protected = purpose in PROTECTED_PURPOSES
    usage = {
        "tokens": spent_value,
        "tokens_measurement": measurement,
        "model_calls": calls,
        "seconds": elapsed,
    }
    base = dict(
        spent=spent_value,
        authorized=authorized,
        reserve=reserve,
        ceiling=ceiling,
        estimate=estimate,
        measurement=measurement,
        resumes=resumes,
        usage=usage,
        next_action=(
            "O consumo acumulado continua valendo. Para novas inferências de trabalho, "
            f"autorize um teto explícito (POST /runs/{run_id}/budget-grant) ou reduza o escopo e retome. "
            "Retomar não devolve tokens nem aumenta o teto sozinho."
        ),
    )

    def decide(action: str, level: str, reason: str, *, limit_key: str = "tokens", label: str = "orçamento de tokens") -> BudgetDecision:
        """Monta a decisão com o motivo informado."""
        return BudgetDecision(action=action, level=level, reason=reason, limit_key=limit_key, label=label, **base)

    if seconds_cap and elapsed >= seconds_cap and not protected:
        return decide(
            "pause",
            "stop",
            f"o tempo autorizado da execução acabou ({elapsed}s de {seconds_cap}s)",
            limit_key="seconds",
            label="tempo de execução (s)",
        )
    if call_cap and calls >= call_cap and not protected:
        return decide(
            "pause",
            "stop",
            f"o número de chamadas ao modelo chegou ao teto ({calls} de {call_cap})",
            limit_key="model_calls",
            label="chamadas ao modelo",
        )
    if cost_cap is not None and cost_known and not protected:
        future = known_cost + float(projected_cost or 0)
        if future >= cost_cap:
            return decide(
                "pause",
                "stop",
                f"o custo conhecido ({future:.4f}) atingiria o teto de {cost_cap:.4f}",
                limit_key="cost",
                label="custo monetário",
            )
    if not authorized:
        return decide("allow", "normal", "não há teto de tokens para esta execução")
    projected = spent_value + estimate
    ratio = spent_value / authorized if authorized else 0
    if protected:
        if projected > authorized:
            return decide(
                "pause",
                "stop",
                "nem a reserva de conclusão cobre esta chamada; o teto autorizado foi atingido",
            )
        return decide("allow", "normal", "chamada de conclusão usando a reserva protegida")
    if ratio >= ratios["stop"] or projected > ceiling:
        return decide(
            "pause",
            "stop",
            "o orçamento operacional acabou; a reserva de conclusão não será gasta em implementação",
        )
    if ratio >= ratios["reduce"]:
        return decide(
            "reduce",
            "reduce",
            "consumo alto: a próxima montagem de contexto deve compactar o que for dispensável",
        )
    if ratio >= ratios["warn"]:
        return decide("warn", "elevated", "consumo elevado da execução")
    return decide("allow", "normal", "orçamento folgado para esta chamada")


def mark_pressure(session: Session, task_id: uuid.UUID | None, level: str) -> None:
    """Anota na tarefa que a próxima montagem de contexto deve compactar.

    Args:
        session: sessão do banco.
        task_id: tarefa corrente.
        level: faixa aplicada (`reduce` ou `elevated`).
    """
    if task_id is None:
        return
    from agent.persistence.models import TaskModel

    task = session.get(TaskModel, task_id)
    if task is None:
        return
    meta = dict(task.metadata_json or {})
    meta["context_pressure"] = level
    task.metadata_json = meta


def grant_budget(session: Session, run: ExecutionRunModel, *, tokens: int, reason: str) -> dict[str, Any]:
    """Autoriza mais tokens para a execução. A autorização fica no histórico do run.

    Args:
        session: sessão do banco.
        run: execução que recebe o teto adicional.
        tokens: quantidade adicional, maior que zero.
        reason: motivo informado por quem autoriza.

    Returns:
        O teto resultante e a lista de autorizações.

    Raises:
        ValueError: quando a quantidade ou o motivo não servem para auditoria.
    """
    amount = int(tokens)
    motive = (reason or "").strip()
    if amount <= 0:
        raise ValueError("a autorização de orçamento precisa ser maior que zero")
    if not motive:
        raise ValueError("a autorização de orçamento precisa de um motivo")
    config = dict(run.config_json or {})
    grants = list(config.get("budget_grants") or [])
    entry = {
        "tokens": amount,
        "reason": motive,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    grants.append(entry)
    config["budget_grants"] = grants
    run.config_json = config
    session.add(
        EventLogModel(
            project_id=run.project_id,
            run_id=run.id,
            task_id=run.root_task_id,
            event_type="budget.granted",
            payload_json=entry,
        )
    )
    session.flush()
    limits = limits_for(active_settings(), config)
    return {"run_id": str(run.id), "grant": entry, "authorized_tokens": int(limits.get("tokens") or 0)}


def latest_record(session: Session, task_id: uuid.UUID) -> InferenceRecordModel | None:
    """Última inferência da tarefa, para o painel da chamada corrente.

    Args:
        session: sessão do banco.
        task_id: tarefa consultada.

    Returns:
        O registro mais recente, ou `None`.
    """
    rows = records_for(session, task_id=task_id)
    return rows[-1] if rows else None
