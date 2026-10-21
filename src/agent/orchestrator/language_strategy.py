"""
Arquivo: src/agent/orchestrator/language_strategy.py
Nome: language_strategy.py
Propósito: escolher o idioma operacional sem perder o pedido original nem o idioma da interface.
Responsabilidade: camada de aplicação — contrato linguístico determinístico, reutilizado no ciclo.
Componentes: build_language_contract, render_operational_for_prompt, inherit_language, switch_language, explain_language, fidelity_gaps.
Dependências: agent.i18n.locale.detect_language.
Observações: não chama o modelo. Uma representação em inglês que omite literal, número ou restrição volta ao pedido original.
"""

from __future__ import annotations

import re
from typing import Any

from agent.i18n.locale import detect_language

MODES = frozenset({"auto", "native", "english_operational"})
_LANGS = frozenset({"pt", "en", "es"})

_PATH = re.compile(
    r"(?:[\w.-]+/)+[\w.-]+\.\w+|[\w.-]+\.(?:py|js|mjs|ts|tsx|json|md|css|html|yml|yaml|toml|sql|sh)\b"
)
_BACKTICK = re.compile(r"`([^`]+)`")
_URL = re.compile(r"https?://\S+")
_ENV = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_CONSTRAINT = re.compile(
    r"\b(não|nao|nunca|sem alterar|do not|don't|never|without)\b",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(
    r"\b(ou|talvez|não sei|nao sei|maybe|either|não está claro|nao esta claro)\b",
    re.IGNORECASE,
)
_TECHNICAL = re.compile(
    r"\b(bug|teste|testes|pytest|função|funcao|arquivo|código|codigo|implement|corrig|refator|api|json|import|def )\b|"
    r"`|/",
    re.IGNORECASE,
)
_PROSE = re.compile(
    r"\b(escreva um texto|redija|artigo|e-mail|email|documento)\b",
    re.IGNORECASE,
)
_PRESENTATION = {"pt": "português", "en": "English", "es": "español"}
_SWITCH_CAUSES = frozenset({"invalid_output", "empty_output"})


def extract_literals(text: str) -> list[str]:
    """Caminhos, trechos entre crases, URLs e identificadores que não podem mudar.

    Args:
        text: pedido original.

    Returns:
        Os literais, sem repetir, na ordem em que aparecem.
    """
    found: list[str] = []
    for pattern in (_URL, _BACKTICK, _PATH, _ENV):
        for match in pattern.findall(text or ""):
            item = str(match).strip().strip(".,);\"'")
            if item and item not in found:
                found.append(item)
    return found[:12]


def extract_numbers(text: str) -> list[str]:
    """Números e limites do pedido, na grafia original.

    Args:
        text: pedido original.

    Returns:
        Os números encontrados, sem repetir.
    """
    found: list[str] = []
    for match in _NUMBER.findall(text or ""):
        if match not in found:
            found.append(match)
    return found[:12]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [part.strip(" -\t") for part in parts if part.strip()]


def extract_constraints(text: str) -> list[str]:
    """Frases que restringem o trabalho, copiadas do pedido.

    Args:
        text: pedido original.

    Returns:
        As restrições literais.
    """
    found: list[str] = []
    for sentence in _sentences(text):
        if _CONSTRAINT.search(sentence) and sentence not in found:
            found.append(sentence[:240])
    return found[:8]


def extract_ambiguities(text: str) -> list[str]:
    """Frases ambíguas que a estratégia não resolve sozinha.

    Args:
        text: pedido original.

    Returns:
        As frases, ainda sem escolha.
    """
    found: list[str] = []
    for sentence in _sentences(text):
        if _AMBIGUOUS.search(sentence) and sentence not in found:
            found.append(sentence[:240])
    return found[:4]


def fidelity_gaps(original: str, operational: str) -> list[str]:
    """O que a representação operacional perdeu em relação ao pedido.

    Args:
        original: texto do usuário.
        operational: texto que seria enviado ao modelo.

    Returns:
        Literais, números ou restrições ausentes. Lista vazia quando a cópia é fiel.
    """
    gaps: list[str] = []
    blob = operational or ""
    for item in [*extract_literals(original), *extract_numbers(original), *extract_constraints(original)]:
        if item not in blob and item not in gaps:
            gaps.append(item[:80])
    return gaps


def select_applied(
    mode: str,
    *,
    input_language: str,
    objective: str,
    profile: dict[str, Any] | None = None,
) -> str:
    """Escolhe `native` ou `english_operational` sem tratar o inglês como regra universal.

    No modo `auto`, o inglês operacional é candidato para pedido técnico que não está
    em inglês. Pedido já em inglês, prosa sem marca técnica e perfil que prefere o
    idioma original ficam em `native`. Sem essas pistas, o automático também fica
    no idioma original.

    Args:
        mode: `auto`, `native` ou `english_operational`.
        input_language: idioma detectado do pedido.
        objective: pedido original.
        profile: preferência opcional do modelo (`preferred`).

    Returns:
        A estratégia aplicada.
    """
    requested = mode if mode in MODES else "auto"
    if requested == "native":
        return "native"
    if requested == "english_operational":
        return "english_operational"
    preferred = str((profile or {}).get("preferred") or "")
    if preferred in {"native", "english_operational"}:
        return preferred
    if input_language == "en":
        return "native"
    if _PROSE.search(objective or "") and not _TECHNICAL.search(objective or ""):
        return "native"
    if _TECHNICAL.search(objective or ""):
        return "english_operational"
    return "native"


def build_language_contract(
    objective: str,
    *,
    mode: str = "auto",
    presentation: str = "auto",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Monta o contrato linguístico da raiz. O pedido original não é reescrito aqui.

    A representação operacional em inglês, quando escolhida, é um quadro de instrução
    mais o próprio pedido. Se esse quadro não puder carregar um literal, um número ou
    uma restrição, a estratégia aplicada volta para `native` e o texto enviado continua
    sendo o pedido.

    Args:
        objective: solicitação original.
        mode: modo configurado.
        presentation: `auto` ou um idioma explícito (`pt`, `en`, `es`).
        profile: preferência opcional por modelo.

    Returns:
        O contrato compacto, sem uma segunda cópia do prompt.
    """
    text = objective or ""
    input_language = detect_language(text)
    presentation_language = presentation if presentation in _LANGS else input_language
    chosen = select_applied(mode, input_language=input_language, objective=text, profile=profile)
    literals = extract_literals(text)
    constraints = extract_constraints(text)
    ambiguities = extract_ambiguities(text)
    applied = "native"
    operational_language = input_language
    fallback = ""
    if chosen == "english_operational":
        # O quadro operacional carrega o pedido inteiro. Se uma versão futura
        # trouxer só a tradução, a mesma checagem devolve o original.
        _kept, fallback = apply_operational_text(text, f"{text}\n" + "\n".join(constraints))
        if not fallback:
            applied = "english_operational"
            operational_language = "en"
    return {
        "input_language": input_language,
        "presentation_language": presentation_language,
        "operational_language": operational_language,
        "requested_mode": mode if mode in MODES else "auto",
        "applied": applied,
        "fallback": fallback,
        "requirements_kept": True,
        "literals": literals,
        "constraints": constraints,
        "ambiguities": ambiguities,
        "revision": 1,
        "validated": not fallback,
    }


def render_operational_for_prompt(metadata: dict[str, Any] | None) -> str:
    """Quadro curto para o modelo quando a etapa usa inglês operacional.

    O objetivo da etapa já está no prompt. Este quadro não traduz o pedido de novo:
    repete restrições e literais e fixa o idioma visível ao usuário.

    Args:
        metadata: metadados da etapa, com a chave `language` quando houver contrato.

    Returns:
        O quadro, ou vazio quando a etapa permanece no idioma original.
    """
    contract = (metadata or {}).get("language") if isinstance(metadata, dict) else None
    if not isinstance(contract, dict) or contract.get("applied") != "english_operational":
        return ""
    presentation = _PRESENTATION.get(str(contract.get("presentation_language") or "pt"), "português")
    lines = [
        "Operational instructions are in English.",
        f"User-visible titles, explanations and the final answer stay in {presentation}.",
        "Do not translate paths, commands, identifiers, code, error text or quoted literals.",
        "Do not add a requirement that is not in the original request.",
    ]
    constraints = contract.get("constraints") or []
    if constraints:
        lines.append("Constraints, verbatim:")
        lines.extend(f"- {item}" for item in constraints[:6])
    literals = contract.get("literals") or []
    if literals:
        lines.append("Unchanged literals: " + ", ".join(str(item) for item in literals[:8]))
    ambiguities = contract.get("ambiguities") or []
    if ambiguities:
        lines.append("Unresolved ambiguities, verbatim:")
        lines.extend(f"- {item}" for item in ambiguities[:4])
    return "\n".join(lines)


def inherit_language(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """Cópia do contrato para uma etapa filha, sem traduzir de novo.

    Args:
        contract: contrato da etapa pai.

    Returns:
        O recorte herdado, ou `None` quando não há contrato.
    """
    if not isinstance(contract, dict) or not contract.get("applied"):
        return None
    keys = (
        "input_language",
        "presentation_language",
        "operational_language",
        "requested_mode",
        "applied",
        "fallback",
        "literals",
        "constraints",
        "ambiguities",
        "revision",
        "validated",
        "switched_from",
        "switch_reason",
    )
    return {key: contract[key] for key in keys if key in contract}


def switch_language(metadata: dict[str, Any] | None, cause: str) -> dict[str, Any] | None:
    """Troca o inglês operacional pelo idioma original uma vez, depois de saída inválida.

    A troca é uma hipótese: a saída não cumpriu o contrato. Não volta para o inglês
    na falha seguinte, para não alternar idioma sem uma evidência nova.

    Args:
        metadata: metadados atuais da etapa.
        cause: causa da falha já classificada.

    Returns:
        O contrato atualizado, ou `None` quando não cabe trocar.
    """
    contract = (metadata or {}).get("language") if isinstance(metadata, dict) else None
    if not isinstance(contract, dict):
        return None
    if cause not in _SWITCH_CAUSES:
        return None
    if contract.get("applied") != "english_operational":
        return None
    if contract.get("switched_from"):
        return None
    updated = dict(contract)
    updated["switched_from"] = "english_operational"
    updated["switch_reason"] = cause
    updated["applied"] = "native"
    updated["operational_language"] = str(contract.get("input_language") or "pt")
    updated["revision"] = int(contract.get("revision") or 1) + 1
    return updated


def explain_language(contract: dict[str, Any] | None) -> str:
    """Frase do feed no idioma de apresentação. Vazia quando não houve mudança operacional.

    Args:
        contract: contrato linguístico.

    Returns:
        A frase, ou vazia no modo nativo.
    """
    if not isinstance(contract, dict) or contract.get("applied") != "english_operational":
        return ""
    presentation = str(contract.get("presentation_language") or "pt")
    if presentation == "en":
        return (
            "I will use an English operational specification for this technical step, "
            "keeping file names, commands and the original criteria unchanged."
        )
    if presentation == "es":
        return (
            "Voy a usar una especificación operativa en inglés para esta etapa técnica, "
            "conservando archivos, comandos y los criterios originales."
        )
    return (
        "Vou usar uma especificação operacional em inglês nesta etapa técnica, "
        "preservando arquivos, comandos e os critérios originais."
    )


def apply_operational_text(original: str, translated: str | None) -> tuple[str, str]:
    """Aceita um texto operacional só quando ele conserva literal, número e restrição.

    Args:
        original: pedido do usuário.
        translated: candidato já produzido. Vazio significa usar o original.

    Returns:
        O texto que deve seguir e o motivo do fallback, vazio quando o candidato serve.
    """
    if not (translated or "").strip():
        return original, ""
    gaps = fidelity_gaps(original, translated or "")
    if gaps:
        return original, f"fidelidade: {gaps[0]}"
    return translated or original, ""


def compare_strategies(objective: str) -> dict[str, str]:
    """Aplica os três modos ao mesmo pedido, para comparação estrutural sem modelo.

    Args:
        objective: pedido original.

    Returns:
        O modo aplicado por `native`, `english_operational` e `auto`.
    """
    return {
        name: str(build_language_contract(objective, mode=name)["applied"])
        for name in ("native", "english_operational", "auto")
    }
