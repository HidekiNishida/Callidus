"""
Arquivo: src/agent/orchestrator/final_review.py
Nome: final_review.py
Propósito: antes de dar um pedido de conclusão por pronto, revisar o estado final do projeto atrás de defeitos de comportamento e transformar cada defeito em requisito a corrigir.
Responsabilidade: camada de aplicação — uma chamada de revisão por run, normalização dos defeitos e gravação no contrato da raiz.
Componentes: needs_final_review, review_prompt, final_review.
Dependências: agent.orchestrator.gap_analysis (retrato do projeto, limpeza), agent.orchestrator.decomposition (gravação no contrato), agent.providers.
Observações: roda uma vez por raiz (marca `final_review` na raiz); sem defeito apontado, o aceite segue como estava.

Por que existe
--------------
Visto com o `qwen3-vl:8b` em "termine a calculadora e abra para eu ver": todos os requisitos
saíram "comprovados" e o run concluiu, mas o botão "Calculate" sempre dividia (cópia do método
`divide`) e dividir por zero mostrava "entrada inválida". A prova da interface clica nos botões e
só acusa exceção; resultado errado não lança exceção. Um olhar de revisor sobre o código final —
o mesmo modelo, com outro papel e o estado real — pega esse tipo de defeito.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent.orchestrator.gap_analysis import _clean, project_snapshot, wants_completion
from agent.persistence.models import TaskModel
from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    LLMProvider,
    ModelProfile,
)
from agent.util.json_parse import parse_json_object

_ORIGIN = "revisão final"


def needs_final_review(root: TaskModel, requirements: list[dict[str, Any]]) -> bool:
    """Diz se a raiz pede revisão final: pedido de conclusão (ou lacunas analisadas) e ainda não revisada.

    Args:
        root: tarefa raiz do run.
        requirements: requisitos atuais do contrato.

    Returns:
        Verdadeiro uma única vez por raiz, para pedidos de terminar/melhorar um projeto existente.
    """
    if (root.metadata_json or {}).get("final_review"):
        return False
    from_gaps = any(r.get("origin") == "lacuna do pedido" for r in requirements)
    return from_gaps or wants_completion(root.objective or "")


def review_prompt(objective: str, done: list[str], snapshot: str) -> str:
    """Pedido de revisão: defeitos de comportamento no estado final, com o que já foi feito como contexto."""
    feitos = "\n".join(f"- {d}" for d in done[:10]) or "- (nada registrado)"
    return (
        "Você é revisor de qualidade. O usuário pediu:\n"
        f"«{objective}»\n\n"
        f"Já foi feito:\n{feitos}\n\n"
        f"Este é o código final:\n{snapshot}\n\n"
        "Procure DEFEITOS reais de comportamento: botão ou comando que não faz o que o rótulo diz, "
        "função copiada que faz a operação errada, mensagem de erro que não corresponde ao erro, "
        "exceção que nunca é capturada por ter o tipo errado, entrada comum que quebra o programa. "
        "Leia o código com atenção antes de responder. Liste no máximo 4 defeitos, cada um como frase "
        "imperativa curta que começa citando o arquivo a mudar ('em main.py, ...'). Não proponha "
        "melhorias opcionais nem mudanças em testes. Se não houver defeito real, devolva lista vazia. "
        'Responda SOMENTE JSON: {"defeitos": ["..."]}'
    )


async def final_review(
    session: Session,
    root: TaskModel,
    *,
    provider: LLMProvider,
    profile: ModelProfile,
    project_root: str,
) -> list[dict[str, Any]]:
    """Revisa o estado final e grava os defeitos como requisitos novos da raiz.

    Args:
        session: sessão do banco.
        root: tarefa raiz (recebe a marca `final_review`, haja defeito ou não).
        provider: modelo do run.
        profile: perfil do modelo.
        project_root: pasta de trabalho do projeto.

    Returns:
        Os requisitos acrescentados (vazio quando a revisão não achou defeito ou falhou).
    """
    from agent.orchestrator.decomposition import _store_added_requirements
    from agent.orchestrator.requirements import ensure_requirements

    current = ensure_requirements(session, root)
    if not needs_final_review(root, current):
        return []
    root.metadata_json = {**(root.metadata_json or {}), "final_review": {"defects": 0}}
    session.flush()
    snapshot = project_snapshot(project_root)
    if not snapshot:
        return []
    done = [r["description"] for r in current]
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=review_prompt(root.objective or "", done, snapshot))],
        profile=profile,
    )
    from agent.providers.observed import observed_chat

    try:
        resp = await observed_chat(provider, request, purpose="plan")
    except Exception:  # noqa: BLE001 — revisão que falha não pode impedir a entrega
        return []
    data, _err = parse_json_object(resp.content or "")
    defects = _clean((data or {}).get("defeitos") or (data or {}).get("defects")) if isinstance(data, dict) else []
    known = {r["description"].lower() for r in current}
    defects = [d for d in defects if d.lower() not in known][:4]
    if not defects:
        return []
    start = len(current) + 1
    added = [
        {
            "id": f"R{start + index}",
            "description": text,
            "origin": _ORIGIN,
            "criterion": f"Atendido com evidência: {text}",
            "applicability": "obrigatório",
            "evidence": "change",
            "refs": [],
        }
        for index, text in enumerate(defects)
    ]
    _store_added_requirements(session, root, added)
    root.metadata_json = {**(root.metadata_json or {}), "final_review": {"defects": len(added), "items": defects}}
    session.flush()
    return added
