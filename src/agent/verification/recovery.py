# src/agent/verification/recovery.py — Ciclo de recuperação da verificação
#
# Uma verificação reprovada não é o fim do caminho: o agente diagnostica a falha,
# decide a correção e re-executa a verificação. Este módulo concentra a taxonomia
# do diagnóstico (puro e testável) para que o orquestrador aplique o ciclo
# diagnóstico → correção → re-verificação sem repetirprompt nem mascarar o sintoma.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Causas reconhecidas de uma verificação reprovada.
CAUSE_SYNTAX = "syntax_error"
CAUSE_TEST_FAILURE = "test_failure"
CAUSE_MISSING_ARTIFACT = "missing_artifact"
CAUSE_MISSING_DEPENDENCY = "missing_dependency"
CAUSE_ENVIRONMENT = "environment"
CAUSE_TIMEOUT = "timeout"
CAUSE_UNKNOWN = "unknown"

# Correções possíveis.
ACTION_FIX_SYNTAX = "fix_syntax"
ACTION_FIX_TESTS = "fix_tests"
ACTION_REGENERATE_ARTIFACT = "regenerate_artifact"
ACTION_INSTALL_DEPENDENCY = "install_dependency"
ACTION_RETRY = "retry"
ACTION_MANUAL_REVIEW = "manual_review"

_SYNTAX_HINTS = ("syntaxerror", "syntax error", "invalid syntax", "erro de sintaxe", "indentationerror")
_IMPORT_HINTS = ("modulenotfounderror", "importerror", "cannot import name", "no module named")
_MISSING_HINTS = ("no such file", "não existe", "not found", "does not exist", "filenotfounderror")
_TIMEOUT_HINTS = ("timeout", "timed out", "tempo esgotado")
_ENV_HINTS = ("permission denied", "no space left", "connection refused", "address already in use")
_TEST_HINTS = ("assertionerror", "assert ", "failed", "falhou", "failing", "error")


@dataclass
class RecoveryDiagnosis:
    """Diagnóstico de uma verificação reprovada e a correção a aplicar."""

    cause: str
    action: str
    automatic: bool
    guidance: str
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "action": self.action,
            "automatic": self.automatic,
            "guidance": self.guidance,
            "evidence": self.evidence,
        }


def _haystack(summary: str, detail: dict[str, Any] | None) -> str:
    parts = [summary or ""]
    detail = detail or {}
    for key in ("stdout", "stderr", "error", "reason", "syntax_error", "command"):
        value = detail.get(key)
        if isinstance(value, str):
            parts.append(value)
    problems = detail.get("problems")
    if isinstance(problems, dict):
        parts.extend(f"{path} {value}" for path, value in problems.items())
    return "\n".join(parts).lower()


def diagnose_verification_failure(
    *,
    verifier: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
) -> RecoveryDiagnosis:
    """Classifica a causa de uma verificação reprovada e a correção correspondente.

    Entradas: verificador usado, resumo da falha, detalhe estruturado e o spec pedido.
    Saída: `RecoveryDiagnosis` com causa, ação, se a ação é automática e a orientação
    textual handed ao modelo na próxima tentativa.
    """
    text = _haystack(summary, detail)
    spec = spec or {}
    evidence: list[str] = []
    if summary:
        evidence.append(summary.strip()[:300])

    if any(hint in text for hint in _SYNTAX_HINTS):
        return RecoveryDiagnosis(
            cause=CAUSE_SYNTAX,
            action=ACTION_FIX_SYNTAX,
            automatic=True,
            guidance=(
                "A verificação reprovou por erro de sintaxe. Corrija a sintaxe do arquivo "
                "indicado antes de qualquer outra mudança e rode a verificação de novo."
            ),
            evidence=evidence,
        )

    if any(hint in text for hint in _IMPORT_HINTS):
        return RecoveryDiagnosis(
            cause=CAUSE_MISSING_DEPENDENCY,
            action=ACTION_INSTALL_DEPENDENCY,
            automatic=False,
            guidance=(
                "A verificação reprovou por dependência ausente. Verifique se o módulo/arquivo "
                "existe no ambiente antes de reexecutar; não contorne a dependência com try/except."
            ),
            evidence=evidence,
        )

    if any(hint in text for hint in _TIMEOUT_HINTS):
        return RecoveryDiagnosis(
            cause=CAUSE_TIMEOUT,
            action=ACTION_RETRY,
            automatic=True,
            guidance=(
                "A verificação reprovou por tempo esgotado. Reduza o escopo do passo "
                "(arquivo por arquivo) e execute novamente."
            ),
            evidence=evidence,
        )

    if any(hint in text for hint in _MISSING_HINTS):
        path = str(spec.get("path") or "")
        return RecoveryDiagnosis(
            cause=CAUSE_MISSING_ARTIFACT,
            action=ACTION_REGENERATE_ARTIFACT,
            automatic=True,
            guidance=(
                f"A verificação reprovou porque o artefato esperado não existe"
                f"{f' ({path})' if path else ''}. Gere o artefato antes de reexecutar."
            ),
            evidence=evidence,
        )

    if any(hint in text for hint in _ENV_HINTS):
        return RecoveryDiagnosis(
            cause=CAUSE_ENVIRONMENT,
            action=ACTION_MANUAL_REVIEW,
            automatic=False,
            guidance=(
                "A verificação reprovou por condição do ambiente (permissão, disco, porta ocupada). "
                "Não é um defeito do código: reporte o bloqueio e aguarde a decisão do operador."
            ),
            evidence=evidence,
        )

    if verifier in {"pytest", "script", "command", "static_analysis", "file_contains", "syntax"} or any(
        hint in text for hint in _TEST_HINTS
    ):
        failures = _extract_failures(detail)
        return RecoveryDiagnosis(
            cause=CAUSE_TEST_FAILURE,
            action=ACTION_FIX_TESTS,
            automatic=True,
            guidance=(
                "A verificação reprovou por falha de teste. Leia a asserção que falhou, corrija "
                "a causa no código de produção e reexecute — nunca altere o teste para fazê-lo passar."
            ),
            evidence=evidence + failures,
        )

    return RecoveryDiagnosis(
        cause=CAUSE_UNKNOWN,
        action=ACTION_MANUAL_REVIEW,
        automatic=False,
        guidance=(
            "A causa da reprovação não foi determinada de forma confiável. "
            "Repita a verificação com mais contexto antes de alterar o código."
        ),
        evidence=evidence,
    )


def _extract_failures(detail: dict[str, Any] | None) -> list[str]:
    """Extrai linhas de asserção/erro do output do verificador."""
    detail = detail or {}
    raw = detail.get("stdout") or detail.get("stderr") or ""
    if not isinstance(raw, str):
        return []
    picked: list[str] = []
    for line in raw.splitlines():
        low = line.lower()
        if any(hint in low for hint in _TEST_HINTS) or line.strip().startswith("E "):
            clean = line.strip()
            if clean and clean not in picked:
                picked.append(clean[:200])
        if len(picked) >= 5:
            break
    return picked


def plan_recovery(
    diagnosis: RecoveryDiagnosis,
    *,
    attempt_count: int = 0,
    max_recoveries: int = 2,
) -> dict[str, Any]:
    """Decide o próximo passo do ciclo de recuperação.

    Entradas: diagnóstico e contadores de tentativa. Saída: dicionário com a ação
    (`fix_and_retry`, `reopen_task` ou `block`), se a nova tentativa é permitida e
    a orientação a ser gravada nos metadados da tarefa.
    """
    exhausted = attempt_count >= max_recoveries
    if exhausted or not diagnosis.automatic:
        return {
            "action": "block" if exhausted else "manual_review",
            "retry": False,
            "guidance": diagnosis.guidance,
            "cause": diagnosis.cause,
        }
    return {
        "action": "fix_and_retry",
        "retry": True,
        "guidance": diagnosis.guidance,
        "cause": diagnosis.cause,
        "evidence": diagnosis.evidence,
    }


def recovery_signature(diagnosis: RecoveryDiagnosis, detail: dict[str, Any] | None = None) -> str:
    """Assinatura estável da falha — ignora números, paths e hashes."""
    parts = [diagnosis.cause, diagnosis.action]
    for key in ("stdout", "stderr", "error"):
        value = (detail or {}).get(key)
        if isinstance(value, str):
            parts.append(value)
    text = " ".join(parts).lower()
    text = re.sub(r"\d+", "N", text)
    text = re.sub(r"0x[0-9a-f]+", "H", text)
    text = re.sub(r"\s+", " ", text)
    return text[:500]
