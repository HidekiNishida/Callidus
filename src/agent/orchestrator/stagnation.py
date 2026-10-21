"""
Arquivo: src/agent/orchestrator/stagnation.py
Nome: stagnation.py
Propósito: repetição por assinatura normalizada, diagnóstico e limites do run.
Responsabilidade: camada de aplicação.
Componentes: normalize_error, error_signature, strategy_signature, repeated_failures, diagnose, limits_for….
Dependências: agent.config, agent.orchestrator.progress, agent.persistence.models, __future__, datetime, hashlib….
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.

Duas noções convivem aqui, e a distinção é o ponto:

- **Erro**: o que a falha foi. Dois erros com a mesma assinatura são o mesmo erro.
- **Abordagem**: como a etapa age. A assinatura da abordagem **não** inclui o texto do objetivo:
  reescrever o mesmo objetivo com outras palavras não é outra abordagem. Incluí-lo fazia o
  replanejamento parecer uma novidade a cada vez — e é por isso que o contador de repetição
  voltava a zero depois de cada replanejamento.

A contagem de repetição é feita sobre o **problema**, não sobre a etapa: a mesma falha no mesmo
objetivo conta uma vez só, mesmo que o replanejamento tenha criado uma etapa nova. É o contador
que impede a cadeia "falhou → replanejou → falhou igual" de continuar.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
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
    """Calcula a impressão digital curta de um conteúdo qualquer.

    Args:
        data: estrutura a resumir; valores não serializáveis são convertidos em texto.

    Returns:
        O resumo hexadecimal de dezesseis caracteres.
    """
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def error_signature(failure: dict[str, Any]) -> str:
    """Mesma categoria, causa e texto normalizado = mesmo erro, ainda que o texto bruto mude."""
    return _digest([failure.get("category"), failure.get("cause"), normalize_error(str(failure.get("detail") or ""))])


def strategy_signature(task: Any) -> str:
    """O que define a **abordagem** da etapa: a ferramenta e os argumentos, a verificação, o modo de
    operação e a estratégia declarada.

    O texto do objetivo fica de fora de propósito. Duas etapas que pedem a mesma coisa com as
    mesmas ferramentas age da mesma forma, mesmo que o objetivo esteja escrito de outro jeito —
    e o replanejamento reescreve o objetivo a cada vez. Incluí-lo fazia cada replanejamento
    parecer uma abordagem nova e o contador de repetição recomeçava, forever.
    """
    meta = task.metadata_json or {}
    return _digest([{k: meta.get(k) for k in _STRATEGY_KEYS}])


def objective_signature(task: Any) -> str:
    """O que a etapa se propõe a fazer, sem as variações de escrita do mesmo pedido."""
    return _digest([" ".join((task.objective or "").split())])


def problem_key(objective: str, signature: str) -> str:
    """Identidade do problema: o mesmo erro, no mesmo objetivo.

    É a chave que amarra as tentativas entre si mesmo quando o replanejamento cria etapas
    novas. Sem ela, cada etapa nova começava a contagem do zero.
    """
    return _digest([" ".join((objective or "").split()), signature])


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


def problem_attempts(
    root: Any,
    failure: dict[str, Any],
    *,
    workspace: str | None = None,
    change: bool = False,
    approach: str = "",
) -> tuple[int, int, dict[str, Any]]:
    """Conta as tentativas do **mesmo problema** no objetivo inteiro, não só na etapa.

    A contagem mora na raiz da árvore, que sobrevive ao replanejamento (o replanejamento cria
    etapas novas) e à retomada (o estado está no banco). É isso que impede a cadeia
    "falhou → replanejou → falhou igual" de continuar indefinidamente.

    São dois contadores, porque são duas perguntas diferentes:

    - `count`:quantas vezes **a mesma abordagem** falhou com o mesmo erro. É o sinal de loop.
    - `total`: quantas vezes o problema foi atacado, com qualquer abordagem. É o teto do
      problema: mesmo que cada tentativa use uma abordagem nova, o problema não pode consumir
      o orçamento inteiro do run.

    Uma tentativa só continua a contagem de loop quando **nada mudou de material**: a mesma
    operação, a mesma abordagem, o mesmo estado do disco. Mudou qualquer um deles, é uma
    tentativa legítima (a causa foi corrigida, a abordagem mudou, o projeto avançou) e a
    contagem de loop recomeça. O total nunca recomeça.

    Args:
        root: tarefa raiz do objetivo; é onde a contagem é guardada.
        failure: falha registrada, com `signature` e `strategy`.
        workspace: impressão do estado do disco no momento da falha.
        change: quando `True`, houve mudança material declarada (nova abordagem escolhida).
        approach: impressão da abordagem em vigor na tentativa.

    Returns:
        O trio `(tentativas da mesma abordagem, tentativas totais do problema, registro)`.
    """
    meta = dict(root.metadata_json or {})
    ledger = meta.get("problem_ledger") if isinstance(meta.get("problem_ledger"), dict) else {}
    key = problem_key(root.objective or "", str(failure.get("signature") or ""))
    entry = ledger.get(key) if isinstance(ledger.get(key), dict) else {}
    same_approach = bool(entry) and entry.get("strategy") == failure.get("strategy")
    same_disk = workspace is None or not entry.get("workspace") or entry.get("workspace") == workspace
    same_plan = not approach or not entry.get("approach") or entry.get("approach") == approach
    material = bool(change) or not same_approach or not same_disk or not same_plan
    count = 1 if material else int(entry.get("count") or 0) + 1
    total = int(entry.get("total") or 0) + 1
    record = {
        "count": count,
        "total": total,
        "strategy": failure.get("strategy"),
        "approach": approach,
        "cause": failure.get("cause"),
        "category": failure.get("category"),
        "workspace": workspace,
        "changed": material,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    ledger = {**ledger, key: record}
    meta["problem_ledger"] = {k: v for k, v in list(ledger.items())[-12:]}
    root.metadata_json = meta
    return count, total, record


_KIND_BY_CAUSE = {
    "context_budget": "contexto",
    "truncated_output": "contexto",
    "invalid_plan": "planejamento",
    "repeated_prompt": "planejamento",
    "invalid_output": "implementação",
    "repeated_output": "implementação",
    "empty_output": "implementação",
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
    "provider_unavailable": "provedor",
    "provider_rejected": "provedor",
    "provider_rate_limit": "provedor",
    "provider_credentials": "provedor",
    "provider_error": "provedor",
    "timeout": "provedor",
    "dependency_failed": "dependência",
}

_ACTION_BY_KIND = {
    "contexto": ("reduzir o escopo: dividir a etapa em partes menores", True),
    "planejamento": ("revisar o plano do nível de cima com o diagnóstico", True),
    "implementação": ("trocar a abordagem: replanejar a etapa com o erro como hipótese a corrigir", True),
    "verificação": ("recuperar a evidência que falta e corrigir o que a verificação aponta, com outra abordagem", True),
    "ferramenta": ("trocar de ferramenta ou corrigir os argumentos; se persistir, pedir ajuda", True),
    "provedor": ("reformular o pedido ao provedor; uma chamada recusada ou indisponível não se resolve repetindo", True),
    "configuração": ("corrigir a configuração indicada (executável, aprovação, permissão) e retomar", False),
    "dependência": ("resolver a dependência que falhou antes de repetir esta etapa", False),
}


def diagnose(failure: dict[str, Any], count: int) -> dict[str, Any]:
    """Causa provável, tipo do problema e ação corretiva proporcional; `automatic` diz se o próprio agente
    pode seguir com uma estratégia justificável ou se precisa de ação de fora (pausa)."""
    cause = str(failure.get("cause"))
    kind = _KIND_BY_CAUSE.get(cause, "implementação")
    action, automatic = _ACTION_BY_KIND[kind]
    if cause in _NEEDS_OUTSIDE_ACTION:
        # Credencial e política não se resolvem com outra tentativa do agente.
        automatic = False
        action = _OUTSIDE_ACTION.get(cause, action)
    return {
        "kind": kind,
        "probable_cause": f"o mesmo erro se repetiu {count} vezes com a mesma estratégia: {str(failure.get('detail') or '')[:240]}",
        "action": action,
        "automatic": automatic,
    }


# Causas que dependem de ação de fora: nova tentativa do agente não muda o resultado.
_NEEDS_OUTSIDE_ACTION = frozenset({"provider_credentials", "missing_executable", "feature_disabled", "approval_required"})

_OUTSIDE_ACTION = {
    "provider_credentials": "corrigir a credencial do provedor; nenhuma nova tentativa resolve isso",
    "missing_executable": "instalar o executável ausente antes de tentar de novo",
    "feature_disabled": "ligar a funcionalidade na configuração antes de tentar de novo",
    "approval_required": "obter a aprovação da operação antes de tentar de novo",
}


LIMIT_KEYS = {
    "attempts_per_strategy": "max_attempts_per_strategy",
    "attempts_per_problem": "max_attempts_per_problem",
    "steps_without_progress": "max_steps_without_progress",
    "seconds": "max_run_seconds",
    "model_calls": "max_model_calls_per_run",
    "tool_calls": "max_tool_calls_per_run",
    "tokens": "max_tokens_per_run",
    "replans": "max_replans_per_run",
}

LIMIT_LABELS = {
    "attempts_per_strategy": "tentativas com a mesma estratégia",
    "attempts_per_problem": "tentativas no mesmo problema",
    "steps_without_progress": "passos seguidos sem progresso",
    "seconds": "tempo de execução (s)",
    "model_calls": "chamadas ao modelo",
    "tool_calls": "execuções de ferramentas e comandos",
    "tokens": "tokens contabilizados da execução",
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
    extra = 0
    grants = config.get("budget_grants") if isinstance(config.get("budget_grants"), list) else []
    for item in grants:
        if not isinstance(item, dict):
            continue
        try:
            extra += max(0, int(item.get("tokens") or 0))
        except (TypeError, ValueError):
            continue
    if extra:
        out["tokens"] = int(out.get("tokens") or 0) + extra
    return out


def _naive(value: datetime | None) -> datetime | None:
    """Converte um instante para UTC sem informação de fuso.

    Args:
        value: instante a converter; pode ser `None`.

    Returns:
        O instante em UTC sem fuso, ou `None` quando a entrada era `None`.

    Observações:
        A comparação entre instantes gravados no banco exige a mesma base de fuso para todos.
    """
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def segment_start(session: Session, run: ExecutionRunModel) -> datetime:
    """O instante em que o trecho atual do run começou (na última retomada)."""
    resumed = session.scalars(
        select(EventLogModel.created_at)
        .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.resumed")
        .order_by(EventLogModel.created_at.desc())
    ).first()
    return _naive(resumed or run.created_at) or datetime.now(timezone.utc).replace(tzinfo=None)


def resume_count(session: Session, run: ExecutionRunModel) -> int:
    """Quantas vezes o run foi retomado.

    Args:
        session: sessão do banco.
        run: run consultado.

    Returns:
        O número de eventos `run.resumed` do run.
    """
    return int(
        session.scalar(
            select(func.count())
            .select_from(EventLogModel)
            .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "run.resumed")
        )
        or 0
    )


def usage_since(session: Session, run: ExecutionRunModel) -> dict[str, Any]:
    """Consumo do run inteiro, com a exceção dos passos sem progresso.

    O consumo de chamadas, tokens e tempo é **cumulativo**: a retomada não devolve orçamento
    já gasto, senão o mesmo trecho de trabalho pode ser repetido indefinidamente, uma
    retomada por vez. O que a retomada concede é uma **nova cota** (uma unidade do limite
    base por retomada), registrada e auditável — não a devolução do que já foi usado.

    Já os passos sem progresso são contados no **trecho** atual: eles detectam travamento,
    e um trecho novo merece a chance de destravar.

    Returns:
        O consumo por indicador.
    """
    attempts = list(
        session.scalars(select(OperationAttemptModel).where(OperationAttemptModel.run_id == run.id)).all()
    )
    events = list(
        session.scalars(
            select(EventLogModel)
            .where(EventLogModel.run_id == run.id, EventLogModel.event_type == "orchestrator.action")
            .order_by(EventLogModel.created_at, EventLogModel.id)
        ).all()
    )
    snapshots = list(session.scalars(select(ContextSnapshotModel).where(ContextSnapshotModel.run_id == run.id)).all())
    since = segment_start(session, run)
    steps = 0
    last = None
    for e in events:
        state = (e.payload_json or {}).get("progress")
        if state is None:
            continue
        in_segment = (_naive(e.created_at) or since) >= since
        if not in_segment:
            last = state
            steps = 0
            continue
        steps = 0 if last is not None and made_progress(last, state) else steps + 1
        last = state
    actions = [(e.payload_json or {}).get("action") for e in events]
    started = _naive(run.created_at) or datetime.now(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from agent.orchestrator.ledger import run_spend

    accounted, source = run_spend(session, run.id)
    if accounted is None:
        # Execução antiga, anterior ao livro-razão: a soma dos snapshots é estimativa
        # de janela, não consumo processado. O campo `tokens_source` deixa isso explícito.
        tokens = int(sum(s.estimated_tokens or 0 for s in snapshots))
        tokens_source = "snapshot_estimate" if snapshots else "unavailable"
    else:
        tokens = int(accounted)
        tokens_source = source
    return {
        "steps_without_progress": steps,
        "seconds": int((now - started).total_seconds()),
        "model_calls": sum(1 for a in attempts if a.kind == "model"),
        "tool_calls": sum(1 for a in attempts if a.kind == "tool"),
        "tokens": tokens,
        "tokens_source": tokens_source,
        "replans": sum(1 for a in actions if a in {"replanned", "decomposed"}),
    }


def effective_cap(limits: dict[str, int], key: str, resumes: int, allowance: int = 1) -> int:
    """Cota efetiva de um limite, dada a quantidade de retomadas do run.

    Cada retomada concede uma unidade adicional do limite base. A cota cresce, mas o consumo
    já feito continua contando: retomar não devolve o que foi gasto.

    Args:
        limits: limites do run.
        key: identificador do limite.
        resumes: quantidade de retomadas.
        allowance: unidades concedidas por retomada.

    Returns:
        A cota efetiva; `0` quando o limite está desligado.
    """
    cap = int(limits.get(key) or 0)
    if not cap or key in {"steps_without_progress", "tokens"}:
        # O teto de tokens não cresce com a retomada. Autorização nova entra em
        # `config.budget_grants` e já está somada em `limits["tokens"]`.
        return cap
    return cap * (1 + max(0, int(allowance)) * max(0, int(resumes)))


def limit_reached(
    session: Session,
    run: ExecutionRunModel,
    limits: dict[str, int],
    *,
    allowance: int = 1,
) -> dict[str, Any] | None:
    """Primeiro limite operacional atingido no run, com valor e máximo; `None` se nenhum.

    Args:
        session: sessão do banco.
        run: run em curso.
        limits: limites do run.
        allowance: unidades de limite concedidas por retomada.

    Returns:
        A descrição do limite atingido, ou `None`.
    """
    used = usage_since(session, run)
    resumes = resume_count(session, run)
    for key in ("steps_without_progress", "seconds", "model_calls", "tool_calls", "tokens", "replans"):
        cap = effective_cap(limits, key, resumes, allowance)
        if cap and used[key] >= cap:
            return {
                "limit": key,
                "label": LIMIT_LABELS[key],
                "value": used[key],
                "max": cap,
                "resumes": resumes,
                "usage": used,
            }
    return None


def next_action_for_limit(run_id: uuid.UUID, hit: dict[str, Any]) -> str:
    """Diz o que fazer quando um limite operacional é atingido.

    Args:
        run_id: identificador da run, usado na orientação de retomada.
        hit: descrição do limite atingido, com chave, valor e máximo.

    Returns:
        Uma orientação em texto para o usuário, dirigido ao caminho de retomada da run.
    """
    if hit["limit"] == "steps_without_progress":
        return (
            "Veja as pendências e o último erro; ajuste a orientação ou corrija a causa e retome "
            f"(POST /runs/{run_id}/resume). O trabalho comprovado não será refeito."
        )
    if hit["limit"] == "tokens":
        return (
            "O consumo de tokens não é devolvido na retomada e o teto não aumenta sozinho. "
            f"Autorize um acréscimo explícito (POST /runs/{run_id}/budget-grant) ou reduza o escopo. "
            "O trabalho comprovado não será refeito."
        )
    return (
        f"Retome para continuar com uma nova cota (POST /runs/{run_id}/resume) "
        f"ou aumente `config.limits.{hit['limit']}`. O consumo já feito continua contando; "
        f"o trabalho comprovado não será refeito."
    )
