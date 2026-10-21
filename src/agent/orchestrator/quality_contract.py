"""
Arquivo: src/agent/orchestrator/quality_contract.py
Nome: quality_contract.py
Propósito: contrato de qualidade da tarefa — o que é pedido, o que é padrão profissional e o que fica de fora.
Responsabilidade: camada de aplicação — refinamento determinístico da intenção, sem nova inferência.
Componentes: build_quality_contract, inherit_quality, attach_quality_contract, render_quality_for_prompt.
Dependências: agent.orchestrator.strategy, agent.services.contract_service, agent.persistence.models.
Observações: o contrato vive no aceite já persistido da tarefa; o metadado guarda só o recorte que desce na árvore.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from agent.orchestrator.strategy import ProfessionalStrategy, is_read_only_request
from agent.persistence.models import TaskModel
from agent.services.contract_service import ContractService

_PROTOTYPE = re.compile(
    r"\b(prot[oó]tipo|mvp|experimento|rascunho|s[oó] um exemplo|apenas um exemplo)\b",
    re.IGNORECASE,
)
_CHANGE_HINT = re.compile(r"\b(corri\w*|bug|implement\w*|cri[ae]\w*|edit\w*|escrev\w*|refator\w*|adicion\w*)\b", re.IGNORECASE)
_WEB = re.compile(r"\b(p[aá]gina|interface|html|css|formul[aá]rio|responsiv)\b", re.IGNORECASE)
_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
_UNCERTAIN = re.compile(
    r"\b(onde fica|onde est[aá]|n[ãa]o sei|qual arquivo|investig\w*|como funciona)\b",
    re.IGNORECASE,
)

# Critérios de piso. Cada perfil entrega só o que cabe no domínio; consulta não ganha barra de engenharia.
_PROFILES: dict[str, list[str]] = {
    "software_engineering": [
        "o comportamento pedido funciona no caso principal",
        "o que já existia não regride",
        "erro previsível é tratado sem esconder a causa",
    ],
    "debugging_and_root_cause": [
        "a falha é reproduzida ou a causa fica registrada com evidência",
        "a correção ataca a causa encontrada, não só o sintoma",
        "a verificação relevante é executada de novo",
    ],
    "refactoring": [
        "o comportamento externo observado permanece",
        "a mudança fica no recorte pedido",
    ],
    "documentation": [
        "o texto descreve o que o código faz",
        "há propósito e um exemplo quando o pedido pede uso",
    ],
    "quality_assurance": [
        "a verificação é executada e o código de saída fica registrado",
        "falha de ambiente não é apresentada como sucesso",
    ],
    "consultation": [],
    "web": [
        "a página tem hierarquia legível e estado vazio ou de erro quando há dados",
        "o fluxo pedido pode ser percorrido",
    ],
}


def _items(text: str) -> list[str]:
    """Itens enumerados do pedido, na ordem em que aparecem."""
    return [match.group(1).strip() for line in (text or "").splitlines() if (match := _ITEM.match(line))]


def _profile_for(domain: str, objective: str) -> tuple[str, list[str]]:
    """Escolhe o perfil de qualidade do domínio, com o perfil web quando o pedido é de interface."""
    if _WEB.search(objective or "") and domain not in {"documentation", "consultation", "quality_assurance"}:
        return "web", list(_PROFILES["web"])
    return domain, list(_PROFILES.get(domain, _PROFILES["software_engineering"]))


def build_quality_contract(objective: str, strategy: ProfessionalStrategy | dict[str, Any] | None) -> dict[str, Any]:
    """Monta o contrato de qualidade a partir do pedido e da estratégia já classificada.

    Requisitos explícitos vêm do texto do usuário. Critérios inferidos vêm do perfil do domínio
    e ficam marcados como inferidos. Premissas da estratégia não são tratadas como fatos.

    Args:
        objective: pedido original.
        strategy: estratégia profissional já calculada, em objeto ou dicionário.

    Returns:
        Contrato compacto, pronto para gravar no aceite da tarefa.
    """
    strat = strategy if isinstance(strategy, ProfessionalStrategy) else ProfessionalStrategy.from_dict(strategy or {})
    text = " ".join((objective or "").split())
    domain = strat.domain if strat is not None else "software_engineering"
    effort = strat.complexity if strat is not None else "moderate"
    profile, inferred_texts = _profile_for(domain, text)
    prototype = bool(_PROTOTYPE.search(text))
    read_only = is_read_only_request(text) or bool((strat.metadata if strat else {}).get("read_only"))
    explicit = _items(text) or ([text[:500]] if text else ["objetivo vazio"])
    constraints: list[str] = []
    exclusions = ["não criar capacidade que o pedido não pediu"]
    uncertainties: list[str] = []
    if read_only:
        constraints.append("somente leitura: não alterar arquivos")
    if strat is not None and strat.metadata.get("protect_tests"):
        constraints.append("não alterar testes, salvo se o pedido pedir isso")
    if prototype:
        constraints.append("teto de protótipo: demonstrar o pedido, sem infraestrutura extra")
        exclusions.append("endurecimento de produção, autenticação e cobertura ampla não pedidos")
        inferred_texts = ["demonstrar o fluxo pedido de ponta a ponta"]
    elif effort == "simple" and profile == "consultation":
        inferred_texts = []
        exclusions.append("não transformar a consulta em implementação")
    if read_only and _CHANGE_HINT.search(text):
        uncertainties.append("o texto pede mudança e também proíbe alterar; a proibição explícita prevalece")
    if _UNCERTAIN.search(text):
        uncertainties.append("falta localizar no projeto o ponto em que a mudança deve acontecer")
    premises = [
        {"text": item, "origin": "premissa"}
        for item in ((strat.assumptions if strat else None) or [])[:4]
    ]
    acceptance_lines = list((strat.acceptance_criteria if strat else None) or [])[:5]
    if not acceptance_lines:
        acceptance_lines = [f"atender: {explicit[0][:180]}"]
    method = "observação do resultado"
    if strat is not None and isinstance(strat.verification_strategy, dict):
        method = str(strat.verification_strategy.get("type") or method)
    verifiable = method not in {"", "acceptance_manual"}
    acceptance = [
        {
            "id": f"Q{index}",
            "text": line,
            "origin": "explícito" if line in explicit else "estratégia",
            "method": method,
            "verifiable": verifiable,
            "status": "pendente",
        }
        for index, line in enumerate(acceptance_lines, start=1)
    ]
    return {
        "objective": text[:500],
        "expected_result": acceptance_lines[0][:240],
        "profile": profile,
        "effort": effort,
        "scope_ceiling": "prototype" if prototype else "professional",
        "explicit": [{"text": item[:300], "origin": "explícito"} for item in explicit[:8]],
        "inferred": [{"text": item, "origin": "inferido"} for item in inferred_texts[:4]],
        "constraints": constraints,
        "premises": premises,
        "uncertainties": uncertainties,
        "exclusions": exclusions,
        "acceptance": acceptance,
        "verification": method,
        "history": [],
    }


def inherit_quality(parent: dict[str, Any] | None, child_objective: str) -> dict[str, Any] | None:
    """Recorte do contrato do pai que a etapa filha precisa ver.

    Não copia premissas nem o histórico. Leva restrições, exclusões e os critérios cujo
    texto conversa com o objetivo local; se nenhum conversar, leva o primeiro critério.

    Args:
        parent: contrato compacto gravado no pai.
        child_objective: objetivo da etapa filha.

    Returns:
        O recorte, ou `None` quando o pai não tem contrato.
    """
    if not isinstance(parent, dict) or not parent.get("objective"):
        return None
    child = (child_objective or "").casefold()
    words = {word for word in re.findall(r"\w{5,}", child)}

    def relevant(text: str) -> bool:
        """O critério compartilha uma palavra significativa com o objetivo da filha."""
        return bool(words & set(re.findall(r"\w{5,}", text.casefold())))

    chosen = [
        item for item in (parent.get("acceptance") or []) if isinstance(item, dict) and relevant(str(item.get("text") or ""))
    ]
    if not chosen and parent.get("acceptance"):
        first = parent["acceptance"][0]
        chosen = [first] if isinstance(first, dict) else []
    inferred = [
        item for item in (parent.get("inferred") or []) if isinstance(item, dict) and relevant(str(item.get("text") or ""))
    ][:2]
    return {
        "parent_objective": str(parent.get("objective") or "")[:180],
        "effort": parent.get("effort") or "moderate",
        "scope_ceiling": parent.get("scope_ceiling") or "professional",
        "constraints": list(parent.get("constraints") or [])[:4],
        "exclusions": list(parent.get("exclusions") or [])[:3],
        "acceptance": chosen[:3],
        "inferred": inferred,
        "uncertainties": list(parent.get("uncertainties") or [])[:2],
    }


def compact_quality(contract: dict[str, Any]) -> dict[str, Any]:
    """Versão do contrato que cabe no metadado da tarefa e desce para as filhas.

    Args:
        contract: contrato completo.

    Returns:
        O mesmo recorte usado na herança, mais os critérios inferidos do próprio nível.
    """
    inherited = inherit_quality(contract, str(contract.get("objective") or "")) or {}
    inherited["inferred"] = list(contract.get("inferred") or [])[:4]
    inherited["premises"] = list(contract.get("premises") or [])[:3]
    inherited["explicit_summary"] = str(contract.get("objective") or "")[:180]
    return inherited


def attach_quality_contract(session: Session, task: TaskModel, contract: dict[str, Any]) -> dict[str, Any]:
    """Grava o contrato no aceite da tarefa, preservando os requisitos que já estavam lá.

    Uma segunda gravação do mesmo objetivo não duplica histórico. Mudança de critérios
    ou de esforço registra uma linha curta no histórico do contrato.

    Args:
        session: sessão do banco.
        task: tarefa dona do contrato.
        contract: contrato produzido por `build_quality_contract`.

    Returns:
        O contrato gravado, com o histórico atualizado quando houve mudança material.
    """
    contracts = ContractService(session)
    row = contracts.get(task.id)
    acceptance = dict((row.acceptance_json if row else None) or {})
    previous = acceptance.get("quality") if isinstance(acceptance.get("quality"), dict) else None
    stored = dict(contract)
    if previous and previous.get("objective") == stored.get("objective"):
        changed = previous.get("acceptance") != stored.get("acceptance") or previous.get("inferred") != stored.get("inferred")
        history = list(previous.get("history") or [])
        if changed:
            history.append(
                {
                    "effort": previous.get("effort"),
                    "acceptance": [item.get("text") for item in (previous.get("acceptance") or []) if isinstance(item, dict)][:4],
                }
            )
        stored["history"] = history[-6:]
    acceptance["quality"] = stored
    contracts.upsert(task.id, acceptance=acceptance)
    return stored


def render_quality_for_prompt(metadata: dict[str, Any] | None) -> str:
    """Texto curto dos critérios herdados para o prompt da operação.

    Args:
        metadata: metadados da tarefa.

    Returns:
        O bloco de texto, ou vazio quando a tarefa não tem contrato.
    """
    quality = (metadata or {}).get("quality_contract")
    if not isinstance(quality, dict):
        return ""
    lines = ["Critérios desta etapa (não amplie o escopo):"]
    for item in (quality.get("constraints") or [])[:4]:
        lines.append(f"- restrição: {item}")
    for item in (quality.get("exclusions") or [])[:3]:
        lines.append(f"- fora de escopo: {item}")
    for item in (quality.get("acceptance") or [])[:3]:
        if isinstance(item, dict):
            lines.append(f"- critério: {item.get('text')}")
    for item in (quality.get("premises") or [])[:2]:
        if isinstance(item, dict):
            lines.append(f"- premissa, não confirmada: {item.get('text')}")
    for item in (quality.get("uncertainties") or [])[:2]:
        lines.append(f"- incerteza: {item}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)[:700]
