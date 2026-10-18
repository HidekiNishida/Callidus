# src/agent/orchestrator/stagnation.py — repetição por assinatura normalizada, diagnóstico e limites do run
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.orchestrator.progress import made_progress
from agent.persistence.models import ContextSnapshotModel, EventLogModel, ExecutionRunModel, OperationAttemptModel

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_HEX = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_QUOTED = re.compile(r"[\"'`«»“”]")
_SPACE = re.compile(r"\s+")

_STRATEGY_KEYS = ("tool", "tool_args", "mcp_tool", "mcp_args", "verification", "model_operation", "atomic", "atomize", "strategy")


def normalize_error(text: str) -> str:
    """Texto de erro sem o que muda entre tentativas idênticas (ids, números, tempos, aspas, espaços)."""
    out = (text or "").casefold()
    out = _UUID.sub("<id>", out)
    out = _HEX.sub("<hex>", out)
    out = _NUM.sub("#", out)
    out = _QUOTED.sub("", out)
    return _SPACE.sub(" ", out).strip()[:300]


def _digest(data: Any) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def error_signature(failure: dict[str, Any]) -> str:
    """Mesma categoria, causa e texto normalizado = mesmo erro, ainda que o texto bruto mude."""
    return _digest([failure.get("category"), failure.get("cause"), normalize_error(str(failure.get("detail") or ""))])


def strategy_signature(task: Any) -> str:
    """O que define a abordagem da tarefa: ferramenta e argumentos, verificação, modo de operação e
    objetivo. Mudar algum deles é mudança material; reenviar o mesmo pedido com outro texto de erro não é."""
    meta = task.metadata_json or {}
    return _digest([{k: meta.get(k) for k in _STRATEGY_KEYS}, " ".join((task.objective or "").split())])


def repeated_failures(failures: list[dict[str, Any]]) -> int:
    """Quantas falhas seguidas, a partir da última, têm a mesma assinatura de erro e a mesma estratégia."""
    if not failures or not failures[-1].get("signature"):
        return 0
    last = failures[-1]
    count = 0
    for item in reversed(failures):
        if item.get("signature") != last["signature"] or item.get("strategy") != last.get("strategy"):
            break
        count += 1
    return count


_KIND_BY_CAUSE = {
    "context_budget": "contexto",
    "truncated_output": "contexto",
    "invalid_plan": "planejamento",
    "repeated_prompt": "planejamento",
    "invalid_output": "implementação",
    "repeated_output": "implementação",
    "verification_failed": "verificação",
    "verification_inconclusive": "verificação",
    "stale_evidence": "verificação",
    "tool_error": "ferramenta",
    "tool_input": "ferramenta",
    "unknown_tool": "ferramenta",
    "missing_executable": "configuração",
    "feature_disabled": "configuração",
    "approval_required": "configuração",
    "path_outside_root": "configuração",
    "provider_unavailable": "configuração",
    "provider_error": "ferramenta",
    "timeout": "ferramenta",
    "dependency_failed": "dependência",
}

_ACTION_BY_KIND = {
    "contexto": ("reduzir o escopo: dividir a etapa em partes menores", True),
    "planejamento": ("revisar o plano do nível de cima com o diagnóstico", True),
    "implementação": ("trocar a abordagem: replanejar a etapa com o erro como hipótese a corrigir", True),
    "verificação": ("recuperar a evidência que falta e corrigir o que a verificação aponta, com outra abordagem", True),
    "ferramenta": ("trocar de ferramenta ou corrigir os argumentos; se persistir, pedir ajuda", True),
    "configuração": ("corrigir a configuração indicada (executável, aprovação, permissão) e retomar", False),
    "dependência": ("resolver a dependência que falhou antes de repetir esta etapa", False),
}


def diagnose(failure: dict[str, Any], count: int) -> dict[str, Any]:
    """Causa provável, tipo do problema e ação corretiva proporcional; `automatic` diz se o próprio agente
    pode seguir com uma estratégia justificável ou se precisa de ação de fora (pausa)."""
    kind = _KIND_BY_CAUSE.get(str(failure.get("cause")), "implementação")
    action, automatic = _ACTION_BY_KIND[kind]
    return {
        "kind": kind,
        "probable_cause": f"o mesmo erro se repetiu {count} vezes com a mesma estratégia: {str(failure.get('detail') or '')[:240]}",
        "action": action,
        "automatic": automatic,
    }


LIMIT_KEYS = {
    "attempts_per_strategy": "max_attempts_per_strategy",
    "steps_without_progress": "max_steps_without_progress",
    "seconds": "max_run_seconds",
    "model_calls": "max_model_calls_per_run",
    "tool_calls": "max_tool_calls_per_run",
    "tokens": "max_tokens_per_run",
    "replans": "max_replans_per_run",
}

LIMIT_LABELS = {
    "steps_without_progress": "passos seguidos sem progresso",
    "seconds": "tempo de execução (s)",
    "model_calls": "chamadas ao modelo",
    "tool_calls": "execuções de ferramentas e comandos",
    "tokens": "tokens estimados de contexto",
    "replans": "replanejamentos e decomposições",
}


def limits_for(settings: Settings, config: dict[str, Any]) -> dict[str, int]:
    """Limites do run: padrão em `Settings`, sobrescrito por `config.limits`; 0 desliga o limite."""
    custom = config.get("limits") if isinstance(config.get("limits"), dict) else {}
    out = {}
    for key, attr in LIMIT_KEYS.items():
        value = custom.get(key, getattr(settings, attr))
        try:
            out[key] = max(0, int(value))
        except (TypeError, ValueError):
            out[key] = int(getattr(settings, attr))
    return out


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def segment_start(session: Session, run: ExecutionRunModel) -> datetime:
    """Os contadores recomeçam na última retomada: retomar não reinicia o trabalho, só o orçamento."""
    resumed = session.scalars(
        select(EventLogModel.created_at)
        .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.resumed")
        .order_by(EventLogModel.created_at.desc())
    ).first()
    return _naive(resumed or run.created_at) or datetime.now(timezone.utc).replace(tzinfo=None)


def usage_since(session: Session, run: ExecutionRunModel) -> dict[str, int]:
    """Consumo do trecho atual do run (desde o início ou a última retomada)."""
    since = segment_start(session, run)
    attempts = [
        a
        for a in session.scalars(select(OperationAttemptModel).where(OperationAttemptModel.run_id == run.id)).all()
        if (_naive(a.created_at) or since) >= since
    ]
    events = [
        e
        for e in session.scalars(
            select(EventLogModel)
            .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "orchestrator.action")
            .order_by(EventLogModel.created_at, EventLogModel.id)
        ).all()
        if (_naive(e.created_at) or since) >= since
    ]
    snapshots = [
        s
        for s in session.scalars(select(ContextSnapshotModel).where(ContextSnapshotModel.run_id == run.id)).all()
        if (_naive(s.created_at) or since) >= since
    ]
    steps = 0
    last = None
    for e in events:
        state = (e.payload_json or {}).get("progress")
        if state is None:
            continue
        steps = 0 if last is not None and made_progress(last, state) else steps + 1
        last = state
    actions = [(e.payload_json or {}).get("action") for e in events]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "steps_without_progress": steps,
        "seconds": int((now - since).total_seconds()),
        "model_calls": sum(1 for a in attempts if a.kind == "model"),
        "tool_calls": sum(1 for a in attempts if a.kind == "tool"),
        "tokens": int(sum(s.estimated_tokens or 0 for s in snapshots)),
        "replans": sum(1 for a in actions if a in {"replanned", "decomposed"}),
    }


def limit_reached(session: Session, run: ExecutionRunModel, limits: dict[str, int]) -> dict[str, Any] | None:
    """Primeiro limite operacional atingido no trecho atual, com valor e máximo; `None` se nenhum."""
    used = usage_since(session, run)
    for key in ("steps_without_progress", "seconds", "model_calls", "tool_calls", "tokens", "replans"):
        cap = limits.get(key) or 0
        if cap and used[key] >= cap:
            return {"limit": key, "label": LIMIT_LABELS[key], "value": used[key], "max": cap, "usage": used}
    return None


def next_action_for_limit(run_id: uuid.UUID, hit: dict[str, Any]) -> str:
    if hit["limit"] == "steps_without_progress":
        return (
            "Veja as pendências e o último erro; ajuste a orientação ou corrija a causa e retome "
            f"(POST /runs/{run_id}/resume). O trabalho comprovado não será refeito."
        )
    return (
        f"Retome para continuar com um novo orçamento (POST /runs/{run_id}/resume; os contadores recomeçam) "
        f"ou aumente `config.limits.{hit['limit']}`. O trabalho comprovado não será refeito."
    )
