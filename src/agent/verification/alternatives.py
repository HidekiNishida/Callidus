"""
Arquivo: src/agent/verification/alternatives.py
Nome: alternatives.py
Propósito: verificações complementares que ajudam a diagnosticar por que a primária reprovou.
Responsabilidade: camada de aplicação — seleção e execução de verificadores somente-leitura
diferentes do que reprovou; o resultado enriquece o diagnóstico, **nunca** aprova a etapa.
Componentes: AlternativeVerification, select_alternatives, run_alternative_verification.
Dependências: agent.verification.runner, agent.domain.enums, agent.verification.recovery.
Observações: não aciona o modelo nem executa código do projeto; uma verificação mais fraca que passa
não substitui a que reprovou (pytest reprovado com sintaxe válida continua reprovado).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.verification.recovery import RecoveryDiagnosis

from agent.verification.runner import (
    run_verification,
)

# Verificação primária → verificações complementares, todas somente-leitura (não executam
# código do projeto nem instalam nada). A ordem define a prioridade do diagnóstico.
_ALTERNATIVES_MAP: dict[str, list[str]] = {
    "pytest": ["syntax", "static_analysis"],
    "script": ["file_exists", "syntax"],
    "command": ["file_exists"],
    "file_contains": ["syntax", "file_exists"],
    "file_exists": ["syntax"],
    "syntax": ["static_analysis"],
    "static_analysis": ["syntax"],
    "run_script": ["file_exists", "syntax"],
    "run_command": ["file_exists"],
}

#: Únicos verificadores aceitos como complemento: nenhum deles roda código nem altera o disco.
_READ_ONLY_VERIFIERS = frozenset({"syntax", "static_analysis", "file_exists", "file_contains"})


@dataclass
class AlternativeVerification:
    """Resultado de uma verificação alternativa."""

    verifier: str
    passed: bool | None
    summary: str
    detail: dict[str, Any] | None = None
    is_alternative: bool = True


def select_alternatives(
    primary_verifier: str,
    diagnosis: RecoveryDiagnosis,
    attempted: list[str] | None = None,
) -> list[str]:
    """Seleciona verificadores alternativos para a recuperação.

    Args:
        primary_verifier: verificador que falhou.
        diagnosis: diagnóstico da falha.
        attempted: verificadores já tentados nesta recuperação.

    Returns:
        Lista de tipos de verificadores alternativos, na ordem de prioridade.
    """
    attempted = attempted or [primary_verifier]
    alternatives = _ALTERNATIVES_MAP.get(primary_verifier, [])

    # Filtra alternativas já tentadas
    candidates = [alt for alt in alternatives if alt not in attempted]

    # Prioriza por causa do diagnóstico
    cause = diagnosis.cause
    if cause == "syntax_error":
        # Se erro de sintaxe, prioriza sintaxe e análise estática
        priority = ["syntax", "static_analysis", "file_contains"]
    elif cause == "test_failure":
        # Se falha de teste, prioriza verificação de conteúdo e sintaxe
        priority = ["file_contains", "syntax", "static_analysis"]
    elif cause == "missing_artifact":
        # Se artefato ausente, prioriza existência de arquivo
        priority = ["file_exists", "file_contains"]
    elif cause == "timeout":
        # Se timeout, prioriza verificações mais rápidas
        priority = ["syntax", "file_exists", "file_contains"]
    elif cause == "environment":
        # Se problema de ambiente, não tenta alternativas automáticas
        return []
    else:
        priority = candidates

    # Ordena candidatos pela prioridade, mantendo os que não estão na prioridade no fim
    ordered = sorted(candidates, key=lambda x: priority.index(x) if x in priority else len(priority))
    return [alt for alt in ordered if alt in _READ_ONLY_VERIFIERS]


async def run_alternative_verification(
    *,
    project_root: str,
    spec: dict[str, Any],
    primary_verifier: str,
    diagnosis: RecoveryDiagnosis,
    attempted: list[str] | None = None,
    tool_args: dict[str, Any] | None = None,
    approved: bool = False,
) -> AlternativeVerification | None:
    """Executa verificações complementares até uma passar ou esgotar as opções.

    O resultado é **diagnóstico**: diz o que está certo (o arquivo existe, a sintaxe é válida),
    o que estreita a causa da reprovação. Quem chama não deve tratá-lo como aprovação.

    Args:
        project_root: raiz do projeto.
        spec: especificação original da verificação.
        primary_verifier: verificador primário que falhou.
        diagnosis: diagnóstico da falha.
        attempted: verificadores já tentados.
        tool_args: argumentos das ferramentas.
        approved: aprovação para ferramentas arriscadas.

    Returns:
        O resultado da primeira verificação complementar que passar, ou None se nenhuma passar.
    """
    alternatives = select_alternatives(primary_verifier, diagnosis, attempted)
    if not alternatives:
        return None

    for alt_verifier in alternatives:
        # Adapta o spec para o verificador alternativo
        alt_spec = _adapt_spec_for_verifier(spec, alt_verifier, diagnosis)
        if alt_spec is None:
            continue

        result = await run_verification(
            project_root=project_root,
            spec=alt_spec,
            tool_args=tool_args,
            approved=approved,
        )

        alt_result = AlternativeVerification(
            verifier=alt_verifier,
            passed=result.passed,
            summary=result.summary,
            detail=result.detail,
            is_alternative=True,
        )

        if result.passed is True:
            return alt_result

    return None


def _adapt_spec_for_verifier(
    spec: dict[str, Any],
    verifier: str,
    diagnosis: RecoveryDiagnosis,
) -> dict[str, Any] | None:
    """Adapta a especificação para um verificador alternativo.

    Args:
        spec: especificação original.
        verifier: tipo do verificador alternativo.
        diagnosis: diagnóstico da falha.

    Returns:
        Nova especificação adaptada, ou None se não for aplicável.
    """
    base = dict(spec)
    base["type"] = verifier

    # Remove campos específicos do verificador original
    for key in ["path", "contains", "command", "cwd", "timeout", "verification"]:
        if key not in _RELEVANT_FIELDS.get(verifier, set()):
            base.pop(key, None)

    # Adiciona campos relevantes baseados no diagnóstico
    cause = diagnosis.cause

    if verifier == "file_contains" and "contains" not in base:
        # Tenta extrair do diagnóstico o que deveria estar no arquivo
        if cause == "missing_artifact":
            base["contains"] = ""
        elif cause == "test_failure":
            # Para falha de teste, verifica se o arquivo de teste existe
            base["contains"] = "def test_"

    elif (verifier == "file_exists" and "path" not in base) or (verifier == "syntax" and "path" not in base):
        base["path"] = spec.get("path", "")

    elif verifier == "static_analysis" and "path" not in base:
        base["path"] = spec.get("path", ".")


    # Valida se o spec tem os campos mínimos necessários
    required = _REQUIRED_FIELDS.get(verifier, set())
    if not all(base.get(k) for k in required):
        return None

    return base


_RELEVANT_FIELDS: dict[str, set[str]] = {
    "pytest": {"path"},
    "script": {"path"},
    "run_script": {"path"},
    "command": {"command", "cwd", "timeout"},
    "run_command": {"command", "cwd", "timeout"},
    "file_contains": {"path", "contains"},
    "file_exists": {"path", "min_bytes"},
    "syntax": {"path"},
    "static_analysis": {"path"},
    "acceptance_manual": set(),
}

_REQUIRED_FIELDS: dict[str, set[str]] = {
    "pytest": {"path"},
    "script": {"path"},
    "run_script": {"path"},
    "command": {"command"},
    "run_command": {"command"},
    "file_contains": {"path", "contains"},
    "file_exists": {"path"},
    "syntax": {"path"},
    "static_analysis": {"path"},
    "acceptance_manual": set(),
}
