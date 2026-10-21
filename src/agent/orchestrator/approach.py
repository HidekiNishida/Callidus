"""
Arquivo: src/agent/orchestrator/approach.py
Nome: approach.py
Propósito: memória operacional da etapa — o que foi tentado, a hipótese atual e o que será diferente.
Responsabilidade: camada de aplicação — registra e recupera a abordagem de uma etapa que falha.
Componentes: alternatives_for, record_attempt, approach_of, render_approach, approach_signature.
Dependências: agent.domain.failures, __future__, hashlib, json, typing.
Observações: a memória é pequena e estruturada; o histórico bruto continua no diário de falhas.

Por que existe: o orquestrador detectava repetição, mas não guardava **por que** a tentativa
anterior falhou nem **o que** seria diferente na próxima. O replanejamento mandava "use outra
abordagem" — uma frase sem conteúdo, que o modelo local cumpre repetindo a mesma chamada. Este
módulo fecha a lacuna: para cada causa de falha há uma hipótese declarada e uma lista de
alternativas concretas; a etapa registra qual alternativa está em uso, e o replanejamento só
pode avançar para a próxima.

A hipótese e as alternativas são **determinísticas**: vêm da causa da falha, não do humor do
modelo. O modelo continua decidindo *como* executar dentro da alternativa escolhida, que é o
espaço em que ele agrega valor; ele não decide *se* há alternativa.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

# Hipótese por causa: o que a falha sugere, em uma frase. É a explicação que a etapa registra
# antes de tentar outra coisa.
HYPOTHESIS_BY_CAUSE: dict[str, str] = {
    "invalid_output": "o modelo não entendeu o formato pedido e devolveu outra coisa",
    "empty_output": "o modelo raciocinou e não chegou a produzir a entrega",
    "truncated_output": "a resposta era maior do que o orçamento de saída permitia",
    "context_budget": "o contexto obrigatório é maior do que a janela do modelo aceita",
    "timeout": "a chamada estourou o tempo antes de responder",
    "provider_unavailable": "o provedor estava fora do ar no momento da chamada",
    "provider_rejected": "o provedor recusou o pedido; o pedido, não a rede, está errado",
    "provider_error": "a chamada ao provedor falhou por um erro do lado dele",
    "tool_error": "a ferramenta falhou ao executar",
    "tool_input": "os argumentos da ferramenta não batem com o que a ferramenta espera",
    "unknown_tool": "a ferramenta pedida não existe no registro",
    "path_outside_root": "o caminho pedido está fora da raiz do projeto",
    "missing_executable": "o executável necessário não existe no ambiente",
    "feature_disabled": "a funcionalidade necessária está desligada na configuração",
    "approval_required": "a operação exige aprovação que ninguém deu",
    "verification_failed": "a verificação mediu o resultado e reprovou",
    "verification_inconclusive": "a verificação não conseguiu medir nada",
    "stale_evidence": "os arquivos mudaram depois da verificação; a evidência ficou velha",
    "invalid_plan": "o plano das filhas não é executável",
    "repeated_output": "a etapa devolveu o mesmo resultado da tentativa anterior",
    "repeated_prompt": "o pedido ao modelo seria idêntico ao de uma tentativa anterior",
    "dependency_failed": "uma dependência desta etapa falhou antes dela",
    "attempts_exhausted": "o orçamento de tentativas desta etapa acabou",
    "stagnation": "a mesma falha se repetiu sem mudança material",
    "policy": "a política do projeto impede esta operação",
    "limit_reached": "o limite operacional do run foi atingido",
}

# Alternativas concretas por causa: o que fazer **em vez de** repetir a mesma operação.
# A ordem importa — a primeira alternativa é a mais próxima do que já falhou, a última é a
# mais radical (dividir, reduzir, pedir ajuda). O replanejamento consome uma por vez.
ALTERNATIVES_BY_CAUSE: dict[str, list[str]] = {
    "invalid_output": [
        "pedir a alteração de um trecho só (old_string/new_string), em vez do arquivo inteiro",
        "usar a ferramenta de escrita diretamente, sem passar pelo JSON",
        "reler o trecho exato do arquivo antes de responder de novo",
    ],
    "empty_output": [
        "pedir a resposta de forma direta e curta, sem passo de raciocínio",
        "dividir a etapa: primeiro peça a leitura do arquivo, depois a alteração",
        "usar a ferramenta de escrita diretamente",
    ],
    "truncated_output": [
        "alterar só um trecho do arquivo em vez de reescrevê-lo",
        "reduzir o tamanho da resposta pedida (um arquivo, um trecho)",
        "dividir a etapa em partes menores",
    ],
    "context_budget": [
        "dividir a etapa em partes menores",
        "reduzir o contexto: leia só o que a etapa precisa",
        "liberar o cache de contexto e tentar de novo",
    ],
    "timeout": [
        "reduzir o tamanho do pedido ao provedor",
        "dividir a etapa em partes menores",
    ],
    "provider_unavailable": [
        "aguardar e repetir a mesma chamada (falha transitória)",
        "verificar se o provedor está acessível e repetir depois",
    ],
    "provider_rejected": [
        "reformular o pedido: reduzir o contexto e reenviar em formato menor",
        "verificar o formato e os campos que o provedor exige",
    ],
    "provider_error": [
        "repetir a chamada (falha transitória do servidor)",
        "reduzir o tamanho do pedido antes de reenviar",
    ],
    "tool_error": [
        "verificar se o ambiente mudou e se há razão válida para repetir",
        "obter a mesma informação por outra ferramenta",
        "reproduzir o problema com um caso mínimo",
    ],
    "tool_input": [
        "corrigir os argumentos: copiar o trecho antigo exatamente como está no arquivo",
        "reler o arquivo para obter o trecho exato",
    ],
    "unknown_tool": [
        "usar uma ferramenta que exista no registro",
    ],
    "path_outside_root": [
        "gravar dentro da raiz do projeto",
    ],
    "missing_executable": [
        "corrigir a configuração (executável ausente) antes de repetir",
    ],
    "feature_disabled": [
        "corrigir a configuração (funcionalidade desligada) antes de repetir",
    ],
    "approval_required": [
        "pedir a aprovação explícita da operação",
    ],
    "verification_failed": [
        "ler a saída completa do verificador e localizar a primeira causa relevante",
        "reproduzir o problema com um caso mínimo antes de corrigir",
        "conferir se a alteração foi realmente aplicada no disco",
    ],
    "verification_inconclusive": [
        "repetir a verificação sobre o estado atual do disco",
    ],
    "stale_evidence": [
        "re-verificar com o estado atual dos arquivos",
        "reaplicar a alteração que a evidência cobria",
    ],
    "invalid_plan": [
        "replanejar só a parte afetada, preservando o que já está pronto",
        "listar a raiz do projeto para confirmar a estrutura antes de planejar",
    ],
    "repeated_output": [
        "mudar a abordagem: o resultado anterior não serve como evidência",
    ],
    "repeated_prompt": [
        "reformular o pedido de forma objetiva, com o resultado esperado explícito",
    ],
    "dependency_failed": [
        "resolver a dependência que falhou antes de repetir esta etapa",
    ],
    "attempts_exhausted": [
        "parar e pedir intervenção: o orçamento desta etapa acabou",
    ],
    "stagnation": [
        "mudar de abordagem usando a evidência do diagnóstico",
    ],
    "policy": [
        "parar e pedir revisão da política",
    ],
    "limit_reached": [
        "parar e pedir revisão do limite",
    ],
}

# Critérios de sucesso e de fracasso por tentativa: o que diria que a nova abordagem resolveu,
# e o que diria que a hipótese também está errada.
CRITERIA_BY_CAUSE: dict[str, tuple[str, str]] = {
    "verification_failed": (
        "a verificação passa com evidência válida sobre o estado atual",
        "a mesma verificação reprova com a mesma causa",
    ),
    "stale_evidence": (
        "existe evidência nova e atual sobre os arquivos alterados",
        "a evidência fica desatualizada de novo",
    ),
    "invalid_output": (
        "a resposta do modelo é a entrega pedida, no formato pedido",
        "a resposta volta a não ser a entrega pedida",
    ),
    "empty_output": (
        "a resposta do modelo vem preenchida com a entrega",
        "a resposta volta a vir vazia",
    ),
    "truncated_output": (
        "a resposta cabe no orçamento e vem completa",
        "a resposta é cortada de novo",
    ),
    "tool_error": (
        "a ferramenta executa e devolve o resultado",
        "a ferramenta falha com a mesma causa",
    ),
    "provider_rejected": (
        "o provedor aceita o pedido reformulado",
        "o provedor recusa o pedido de novo",
    ),
}

_DEFAULT_CRITERIA = (
    "a etapa conclui a entrega pedida e a verificação comprova",
    "a mesma falha volta a aparecer sem mudança material",
)

_MAX_TRIED = 5


def _now() -> str:
    """Instante atual em ISO-8601 (UTC), para marcar quando a abordagem foi registrada.

    Returns:
        A marca de tempo no formato ISO-8601 com sufixo UTC.
    """
    return datetime.now(UTC).isoformat()


def alternatives_for(cause: str) -> list[str]:
    """Alternativas concretas para uma causa de falha.

    Args:
        cause: causa da falha, como valor de `FailureCause`.

    Returns:
        A lista de alternativas, da mais próxima à mais radical. Lista vazia quando a causa
        não tem alternativa conhecida — o caso em que a etapa precisa de ação de fora.
    """
    return list(ALTERNATIVES_BY_CAUSE.get(str(cause), []))


def hypothesis_for(cause: str, detail: str = "") -> str:
    """Hipótese declarada para a falha: por que ela aconteceu, em uma frase.

    Args:
        cause: causa da falha.
        detail: detalhe da falha, usado para completar a frase quando é curto.

    Returns:
        A hipótese em texto.
    """
    base = HYPOTHESIS_BY_CAUSE.get(str(cause), "a causa da falha não está determinada")
    short = " ".join((detail or "").split())[:160]
    return f"{base}: {short}" if short else base


def criteria_for(cause: str) -> tuple[str, str]:
    """Critério de sucesso e de fracasso da próxima tentativa.

    Args:
        cause: causa da falha que a tentativa precisa enfrentar.

    Returns:
        O par `(sucesso, fracasso)`.
    """
    return CRITERIA_BY_CAUSE.get(str(cause), _DEFAULT_CRITERIA)


def approach_of(task: Any) -> dict[str, Any]:
    """Memória de abordagem registrada na etapa.

    Args:
        task: etapa consultada.

    Returns:
        O dicionário de abordagem; dicionário vazio quando a etapa ainda não falhou.
    """
    meta = getattr(task, "metadata_json", None) or {}
    approach = meta.get("approach")
    return dict(approach) if isinstance(approach, dict) else {}


def record_attempt(
    task: Any,
    failure: dict[str, Any],
    *,
    alternatives: list[str] | None = None,
) -> dict[str, Any]:
    """Registra a tentativa que falhou e prepara a próxima abordagem.

    A memória passa a dizer, de forma explícita: o que foi tentado, o que aconteceu, por que a
    tentativa não resolveu, qual hipótese explica a falha, o que será diferente na próxima
    abordagem e qual resultado diz que a hipótese falhou.

    Args:
        task: etapa que falhou (o objeto recebe a memória em `metadata_json`).
        failure: falha registrada, com `cause` e `detail`.
        alternatives: alternativas a considerar; quando ausente, vêm da causa.

    Returns:
        A memória de abordagem depois do registro.
    """
    meta = dict(getattr(task, "metadata_json", None) or {})
    approach = meta.get("approach") if isinstance(meta.get("approach"), dict) else {}
    cause = str(failure.get("cause") or "")
    detail = str(failure.get("detail") or "")
    options = list(alternatives if alternatives is not None else alternatives_for(cause))
    tried = list(approach.get("tried") or [])

    # `current_change` é a abordagem **em vigor** na tentativa que falhou; ela só muda quando
    # alguém declara outra abordagem (o replanejamento). O texto de guidance da próxima
    # tentativa (`next_change`) é distinto de propósito: guidance nova não é estratégia nova,
    # e a detecção de repetição não pode se confundir com a narração.
    attempted = str(approach.get("current_change") or "")
    tried.append(
        {
            "what": attempted or "a mesma operação",
            "result": " ".join(detail.split())[:240],
            "outcome": "falhou",
            "cause": cause,
            "at": _now(),
        }
    )
    if cause == "stagnation":
        # A marca de estagnação **não é uma tentativa nova**: ela não consome alternativa nem
        # troca a hipótese. Sem esta ressalva, o registro da estagnação esvaziaria a lista de
        # alternativas e o replanejamento seguinte seria recusado por falta de abordagem.
        approach = {
            **approach,
            "tried": tried[-_MAX_TRIED:],
            "attempts": int(approach.get("attempts") or 0) + 1,
            "updated_at": _now(),
        }
        meta["approach"] = approach
        task.metadata_json = meta
        return approach

    used = int(approach.get("alternatives_used") or 0)
    # A alternativa seguinte é a primeira que ainda não foi tentada. Sem alternativa nova,
    # a etapa precisa de ação de fora — e a memória registra isso explicitamente.
    change = options[used] if used < len(options) else ""
    success, failure_criterion = criteria_for(cause)

    approach = {
        **approach,
        "cause": cause,
        "problem": f"{cause}: {' '.join(detail.split())[:200]}",
        "hypothesis": hypothesis_for(cause, detail),
        "tried": tried[-_MAX_TRIED:],
        "attempts": int(approach.get("attempts") or 0) + 1,
        "alternatives": options,
        "alternatives_used": used + 1,
        "current_change": attempted,
        "next_change": change,
        "success_criterion": success,
        "failure_criterion": failure_criterion,
        "exhausted": not change,
        "updated_at": _now(),
    }
    meta["approach"] = approach
    task.metadata_json = meta
    return approach


def declare_change(task: Any, description: str) -> dict[str, Any]:
    """Registra que a etapa vai passar a fazer outra coisa.

    Usado quando a mudança vem de fora do ciclo de falha — o replanejamento, por exemplo, que
    escolhe a alternativa seguinte. O registro torna a mudança **auditável**: a detecção de
    repetição compara a abordagem declarada, não a intenção.

    Args:
        task: etapa que muda de abordagem.
        description: o que passa a ser feito.

    Returns:
        A memória de abordagem depois do registro.
    """
    meta = dict(getattr(task, "metadata_json", None) or {})
    approach = meta.get("approach") if isinstance(meta.get("approach"), dict) else {}
    approach = {
        **approach,
        "current_change": description,
        "next_change": description,
        "changed_at": _now(),
        "exhausted": False,
    }
    meta["approach"] = approach
    task.metadata_json = meta
    return approach


def approach_signature(task: Any) -> str:
    """Impressão da abordagem vigente da etapa: o que está sendo feito, não o que se pediu.

    A assinatura responde "a etapa age do mesmo jeito?". Ela não inclui o texto do objetivo:
    reescrever o mesmo objetivo com outras palavras não é outra abordagem, e incluí-lo fazia o
    replanejamento parecer uma mudança a cada vez. Também não inclui o detalhe do erro: ele
    muda a cada tentativa (o orçamento ampliado, o número da linha) sem que a abordagem mude.

    Args:
        task: etapa consultada.

    Returns:
        A impressão hexadecimal da abordagem; cadeia vazia quando não há abordagem registrada.
    """
    approach = approach_of(task)
    if not approach:
        return ""
    payload = [
        approach.get("cause") or "",
        approach.get("current_change") or "",
    ]
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


def render_approach(task: Any) -> str:
    """Texto da memória de abordagem para o prompt da etapa.

    O modelo recebe o que já foi tentado, por que falhou e o que precisa ser diferente agora.
    A informação é curta e estruturada: a etapa precisa saber o essencial, não reler a
    transcrição das tentativas anteriores.

    Args:
        task: etapa em execução.

    Returns:
        O bloco de abordagem; string vazia quando a etapa ainda não falhou.
    """
    approach = approach_of(task)
    if not approach:
        return ""
    lines = ["## Abordagem desta etapa"]
    problem = str(approach.get("problem") or "").strip()
    if problem:
        lines.append(f"O que travou: {problem}")
    hypothesis = str(approach.get("hypothesis") or "").strip()
    if hypothesis:
        lines.append(f"Hipótese: {hypothesis}")
    tried = approach.get("tried") or []
    if tried:
        lines.append("Já foi tentado:")
        for item in tried[-3:]:
            what = str(item.get("what") or "a mesma operação")
            result = str(item.get("result") or "")
            lines.append(f"- {what} → {result}" if result else f"- {what}")
    change = str(approach.get("current_change") or "").strip()
    pending = str(approach.get("next_change") or "").strip()
    if change:
        lines.append(f"Abordagem em vigor: {change}")
    if pending:
        lines.append(f"Agora é preciso fazer diferente: {pending}")
    elif approach.get("exhausted"):
        lines.append("Não há abordagem nova disponível: esta etapa precisa de ação de fora.")
    success = str(approach.get("success_criterion") or "").strip()
    failure = str(approach.get("failure_criterion") or "").strip()
    if success:
        lines.append(f"Sucesso: {success}")
    if failure:
        lines.append(f"Falha da hipótese: {failure}")
    return "\n".join(lines)
