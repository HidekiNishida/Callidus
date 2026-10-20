# src/agent/domain/failures.py — taxonomia de falhas do orquestrador
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    """O que fazer a seguir: cada categoria pede uma política diferente."""

    RECOVERABLE = "recoverable"
    CHANGE_STRATEGY = "change_strategy"
    BLOCKED_DEPENDENCY = "blocked_dependency"
    EXTERNAL_UNAVAILABLE = "external_unavailable"
    CONFIGURATION = "configuration"
    OPERATIONAL_LIMIT = "operational_limit"


class FailureCause(StrEnum):
    """Por que falhou: a causa concreta, para log, contexto da próxima tentativa e métricas."""

    CONTEXT_BUDGET = "context_budget"
    INVALID_OUTPUT = "invalid_output"
    EMPTY_OUTPUT = "empty_output"
    TRUNCATED_OUTPUT = "truncated_output"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    TOOL_INPUT = "tool_input"
    UNKNOWN_TOOL = "unknown_tool"
    PATH_OUTSIDE_ROOT = "path_outside_root"
    MISSING_EXECUTABLE = "missing_executable"
    FEATURE_DISABLED = "feature_disabled"
    APPROVAL_REQUIRED = "approval_required"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_INCONCLUSIVE = "verification_inconclusive"
    STALE_EVIDENCE = "stale_evidence"
    INVALID_PLAN = "invalid_plan"
    REPEATED_OUTPUT = "repeated_output"
    REPEATED_PROMPT = "repeated_prompt"
    DEPENDENCY_FAILED = "dependency_failed"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    STAGNATION = "stagnation"
    LIMIT_REACHED = "limit_reached"


@dataclass(frozen=True)
class Failure:
    category: FailureCategory
    cause: FailureCause
    detail: str = ""

    @property
    def retry_same_strategy(self) -> bool:
        """Só falha recuperável admite repetir a mesma abordagem (com o motivo no contexto)."""
        return self.category == FailureCategory.RECOVERABLE

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        data["cause"] = self.cause.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Failure | None:
        if not data:
            return None
        try:
            return cls(FailureCategory(data["category"]), FailureCause(data["cause"]), data.get("detail", ""))
        except (KeyError, ValueError):
            return None


_INPUT_ERRORS = (
    "obrigatório",
    "não encontrado",
    "inexistente",
    "trecho ambíguo",
    "old_string vazio",
    "offset além",
    "regex inválida",
    "já existe",
    "deve ser lista",
)
_DISABLED = ("navegador desligado", "memória indisponível")


_RETRY_HINTS: dict[FailureCause, str] = {
    FailureCause.INVALID_OUTPUT: "Responda apenas o objeto JSON pedido, sem texto, explicação ou cerca de código.",
    FailureCause.EMPTY_OUTPUT: (
        "A última resposta veio vazia. Não descreva o que você faria: devolva o objeto JSON pedido "
        "(path e content, ou path e old_string/new_string)."
    ),
    FailureCause.TRUNCATED_OUTPUT: (
        "A resposta foi cortada pelo limite de saída. Prefira editar um trecho curto "
        "(old_string/new_string) em vez de reescrever o arquivo inteiro."
    ),
    FailureCause.TOOL_INPUT: (
        "A gravação foi recusada pelos argumentos. Para editar, copie old_string exatamente como está "
        "no arquivo atual; para criar, informe path e content."
    ),
    FailureCause.TOOL_ERROR: "A execução falhou; corrija a causa indicada antes de repetir.",
    FailureCause.VERIFICATION_FAILED: "A verificação reprovou a mudança; corrija o que a saída da verificação aponta.",
    FailureCause.PROVIDER_ERROR: "A chamada anterior ao modelo falhou; responda de forma direta e curta.",
}


def retry_hint(failure: Failure) -> str:
    """Instrução para a próxima tentativa, conforme a causa. Vazia quando não há o que mudar no pedido."""
    return _RETRY_HINTS.get(failure.cause, "")


def describe_failures(history: list[dict[str, Any]], *, limit: int = 3, detail_chars: int = 400) -> str:
    """Resumo das últimas falhas para o contexto da próxima tentativa (motivo + o que fazer diferente)."""
    lines: list[str] = []
    for raw in history[-limit:]:
        failure = Failure.from_dict(raw)
        if failure is None:
            continue
        detail = " ".join(failure.detail.split())[:detail_chars]
        line = f"- {failure.cause.value}: {detail}" if detail else f"- {failure.cause.value}"
        hint = retry_hint(failure)
        lines.append(f"{line}\n  O que fazer diferente: {hint}" if hint else line)
    if not lines:
        return ""
    return "As tentativas anteriores desta etapa falharam. Não repita a mesma resposta.\n" + "\n".join(lines)


def classify_tool_result(out: dict[str, Any]) -> Failure | None:
    """Saída de ferramenta → falha categorizada; `None` quando deu certo."""
    if out.get("success"):
        return None
    error = str(out.get("error") or "")
    low = error.lower()
    if out.get("category") == FailureCategory.CONFIGURATION.value:
        return Failure(FailureCategory.CONFIGURATION, FailureCause.MISSING_EXECUTABLE, error)
    if error == "approval_required":
        return Failure(FailureCategory.EXTERNAL_UNAVAILABLE, FailureCause.APPROVAL_REQUIRED, error)
    if low.startswith("ferramenta desconhecida"):
        return Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.UNKNOWN_TOOL, error)
    if any(token in low for token in _DISABLED):
        return Failure(FailureCategory.CONFIGURATION, FailureCause.FEATURE_DISABLED, error)
    if "fora do" in low or "traversal" in low:
        return Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.PATH_OUTSIDE_ROOT, error)
    if low == "timeout":
        return Failure(FailureCategory.OPERATIONAL_LIMIT, FailureCause.TIMEOUT, error)
    if any(token in low for token in _INPUT_ERRORS):
        return Failure(FailureCategory.RECOVERABLE, FailureCause.TOOL_INPUT, error)
    detail = error or (str(out.get("stderr") or "")[-500:]) or f"exit_code={out.get('exit_code')}"
    return Failure(FailureCategory.RECOVERABLE, FailureCause.TOOL_ERROR, detail)


def classify_provider_error(message: str) -> Failure:
    """Mensagem de `ProviderError` → falha. Servidor fora do ar é configuração/ambiente, não estratégia."""
    low = message.lower()
    if "tempo esgotado" in low or "timeout" in low or "timed out" in low:
        return Failure(FailureCategory.OPERATIONAL_LIMIT, FailureCause.TIMEOUT, message)
    if "indisponível" in low or "connect" in low or "refused" in low:
        return Failure(FailureCategory.EXTERNAL_UNAVAILABLE, FailureCause.PROVIDER_UNAVAILABLE, message)
    return Failure(FailureCategory.RECOVERABLE, FailureCause.PROVIDER_ERROR, message)


def looks_truncated(content: str) -> bool:
    """Resposta que abriu JSON (ou cerca de código) e não fechou: o limite de saída cortou."""
    text = (content or "").strip()
    if not text:
        return False
    if text.count("```") % 2 == 1:
        return True
    start = text.find("{")
    return start >= 0 and text.count("{", start) > text.count("}", start)


def classify_model_output(
    content: str,
    parse_error: str | None,
    missing: list[str] | None = None,
    *,
    budget: int | None = None,
    used_tokens: int | None = None,
    reasoning: str | None = None,
) -> Failure | None:
    """Resposta do modelo que deveria ser JSON → falha, distinguindo corte de saída de JSON malformado.

    `budget`/`used_tokens` revelam o corte mesmo quando o texto chegou vazio (o modelo gastou
    todo o orçamento de saída pensando e não devolveu nada): nesse caso a saída foi truncada,
    não inválida — repetir o mesmo pedido não resolve, ampliar o orçamento resolve.

    `reasoning` (canal de raciocínio do modelo) separa o outro caso de resposta vazia: o modelo
    raciocinou e não devolveu nada. Repetir o mesmo pedido também não resolve — o modelo precisa
    responder de forma direta.
    """
    if not parse_error and not missing:
        return None
    exhausted = bool(budget and used_tokens is not None and used_tokens >= budget)
    if exhausted or looks_truncated(content):
        detail = parse_error or "resposta cortada"
        if exhausted and not content.strip():
            detail = f"resposta vazia: o modelo usou todo o orçamento de {budget} tokens"
        return Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.TRUNCATED_OUTPUT, detail)
    if not content.strip() and (reasoning or "").strip():
        thought = " ".join(reasoning.split())
        return Failure(
            FailureCategory.CHANGE_STRATEGY,
            FailureCause.EMPTY_OUTPUT,
            f"resposta vazia: o modelo raciocinou ({len(thought)} caracteres) e não devolveu conteúdo",
        )
    detail = parse_error or f"faltam campos: {', '.join(missing or [])}"
    return Failure(FailureCategory.RECOVERABLE, FailureCause.INVALID_OUTPUT, detail)


def classify_context_error(message: str) -> Failure:
    """Contexto obrigatório maior que o orçamento: repetir igual não resolve; é preciso reduzir ou dividir."""
    return Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.CONTEXT_BUDGET, message)


def classify_verification(passed: bool | None, summary: str, output: str = "") -> Failure | None:
    """Resultado de verificador → falha. Inconclusivo nunca conta como aprovado. O fim da saída do
    verificador entra no detalhe para a próxima tentativa saber o que corrigir."""
    if passed is True:
        return None
    if passed is None:
        return Failure(FailureCategory.EXTERNAL_UNAVAILABLE, FailureCause.VERIFICATION_INCONCLUSIVE, summary)
    tail = (output or "").strip()[-600:]
    detail = f"{summary}: {tail}" if tail else summary
    return Failure(FailureCategory.RECOVERABLE, FailureCause.VERIFICATION_FAILED, detail)
