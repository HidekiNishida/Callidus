"""
Arquivo: src/agent/orchestrator/recovery_policy.py
Nome: recovery_policy.py
Propósito: decidir se uma falha segue, pede investigação, pausa ou para por impedimento real.
Responsabilidade: camada de aplicação — política de continuidade depois do diagnóstico já registrado.
Componentes: alternative_continuance, mark_open_investigation, root_should_recover, pause_next_action, narrate_failure, may_have_partial_effect.
Dependências: nenhuma além da memória de abordagem já gravada na tarefa.
Observações: não chama o modelo e não cria um segundo diagnóstico; só lê a abordagem e a categoria.
"""

from __future__ import annotations

from typing import Any

# Passo material usado uma vez quando a lista determinística de alternativas acaba.
# Não é uma redação nova da mesma operação: pede inspeção do estado antes de concluir.
INVESTIGATE_CHANGE = (
    "Inspecionar o estado atual e escolher um passo diferente das tentativas já registradas, "
    "sem repetir a mesma chamada."
)

# Causas em que a confirmação pode ter se perdido depois de um efeito externo.
PARTIAL_EFFECT_CAUSES = frozenset(
    {
        "timeout",
        "provider_unavailable",
        "provider_error",
        "provider_rate_limit",
    }
)

_OUTSIDE = frozenset(
    {
        "provider_credentials",
        "missing_executable",
        "feature_disabled",
        "approval_required",
    }
)


def alternative_continuance(approach: dict[str, Any] | None) -> str:
    """Diz o que fazer quando a lista de alternativas da causa chega ao fim.

    `continue` significa que ainda há alternativa declarada, ou que a etapa ainda não
    esgotou a lista. `investigate` significa que a lista acabou e ainda cabe uma
    inspeção do estado, diferente das tentativas já registradas. `pause` significa
    que essa inspeção já foi usada e também não abriu caminho: o orçamento ou uma
    condição externa decidem a parada, não a frase "não há alternativa".

    Args:
        approach: memória de abordagem da etapa. Ausente equivale a lista ainda não usada.

    Returns:
        `continue`, `investigate` ou `pause`.
    """
    data = approach or {}
    if not data.get("exhausted"):
        return "continue"
    if data.get("open_investigation"):
        return "pause"
    return "investigate"


def mark_open_investigation(task: Any) -> dict[str, Any]:
    """Registra na própria etapa a investigação que substitui a lista esgotada.

    O histórico `tried` permanece. `exhausted` volta a falso porque o passo novo é a
    inspeção, não a repetição da lista que acabou. A assinatura muda porque
    `current_change` muda.

    Args:
        task: etapa cuja memória de abordagem será atualizada.

    Returns:
        A memória de abordagem depois do registro.
    """
    meta = dict(getattr(task, "metadata_json", None) or {})
    current = meta.get("approach")
    approach = dict(current) if isinstance(current, dict) else {}
    approach["open_investigation"] = True
    approach["exhausted"] = False
    approach["current_change"] = INVESTIGATE_CHANGE
    approach["next_change"] = INVESTIGATE_CHANGE
    meta["approach"] = approach
    task.metadata_json = meta
    return approach


def root_should_recover(*, has_parent: bool, already_recovered: bool, replan: bool) -> bool:
    """A raiz sem pai recupera a própria falha uma vez, quando o replanejamento ainda cabe.

    Args:
        has_parent: a etapa parada tem tarefa pai.
        already_recovered: esta raiz já entrou em recuperação nesta falha.
        replan: a política de replanejamento ainda autoriza outro passo.

    Returns:
        `True` quando a própria raiz deve voltar a planejar.
    """
    return (not has_parent) and replan and (not already_recovered)


def pause_next_action(*, total: int, run_id: Any, probable_cause: str) -> str:
    """Texto da pausa quando o orçamento acaba sem prova de que o objetivo é impossível.

    Args:
        total: tentativas já consumidas pelo problema.
        run_id: execução que pode ser retomada.
        probable_cause: causa registrada no diagnóstico, já resumida.

    Returns:
        A próxima ação, incluindo o caminho de retomada.
    """
    cause = " ".join((probable_cause or "").split())[:180]
    return (
        f"o orçamento deste problema chegou a {total} tentativas ({cause}). "
        "A causa não está provada como insolúvel. O estado fica pausado para retomada "
        f"(POST /runs/{run_id}/resume)"
    )


def may_have_partial_effect(cause: str) -> bool:
    """Indica causas em que a operação pode ter produzido efeito antes de a resposta se perder.

    Args:
        cause: valor de `FailureCause`.

    Returns:
        `True` quando repetir às cegas pode duplicar um efeito externo.
    """
    return cause in PARTIAL_EFFECT_CAUSES


def narrate_failure(category: str, cause: str, detail: str) -> str:
    """Frase do feed para uma falha já classificada. Não anuncia correção nem sucesso.

    Args:
        category: valor de `FailureCategory`.
        cause: valor de `FailureCause`.
        detail: mensagem observada, já sem segredo quando possível.

    Returns:
        Uma frase curta com o que falhou e o próximo passo honesto.
    """
    text = " ".join((detail or "").split())[:180]
    if category == "configuration" or cause in _OUTSIDE and cause != "approval_required":
        return f"Não vou contornar esta dependência. O impedimento confirmado é: {text or cause}."
    if cause == "approval_required":
        extra = f" {text}" if text else ""
        return f"A operação exige autorização que não foi concedida.{extra}"
    if may_have_partial_effect(cause):
        extra = f" {text}" if text else ""
        return (
            f"A falha ({cause}) pode ser transitória e a resposta pode ter se perdido. "
            f"Não vou repetir uma escrita sem considerar o que já tiver sido produzido.{extra}"
        )
    if cause in {"invalid_output", "empty_output", "truncated_output"}:
        extra = f" {text}" if text else ""
        return (
            f"A resposta do modelo não cumpriu o contrato ({cause}). "
            f"Vou ajustar a próxima tentativa com essa evidência.{extra}"
        )
    if cause in {"tool_error", "tool_input", "unknown_tool"}:
        extra = f" {text}" if text else ""
        return (
            f"A ferramenta falhou ({cause}). "
            f"Vou usar o retorno para corrigir a chamada, sem repetir os mesmos argumentos.{extra}"
        )
    if cause in {"verification_failed", "repeated_output"}:
        extra = f" {text}" if text else ""
        return (
            "A verificação ou o resultado se repetiu sem mudança. "
            f"A contagem não prova que o problema é insolúvel; vou mudar a abordagem.{extra}"
        )
    if not cause:
        extra = f" {text}" if text else ""
        return f"A causa ainda não está classificada. Vou preservar o retorno e investigar.{extra}"
    extra = f" {text}" if text else ""
    return f"Uma operação falhou ({cause}). Vou usar o retorno para decidir o próximo passo.{extra}"
