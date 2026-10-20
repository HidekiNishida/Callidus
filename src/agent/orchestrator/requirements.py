# src/agent/orchestrator/requirements.py — requisitos do objetivo original, cobertura por tarefa e estado por evidência
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.orchestrator.consolidation import superseded, verification_evidence_ok
from agent.persistence.models import EvidenceModel, TaskModel
from agent.services.contract_service import ContractService
from agent.verification.fingerprint import is_current

MANDATORY = "obrigatório"
APPLICABILITY = {MANDATORY, "não aplicável", "informativo", "bloqueado"}

_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
# Um requisito de **mudança** exige verificador (teste, sintaxe, arquivo); um de **resposta**
# aceita a resposta final verificada. "Rodar os testes e relatar" não é mudança: o entregável
# é o relatório. Por isso "teste" não é, sozinho, sinal de mudança — só o é quando o pedido
# cria, corrige ou acrescenta testes.
_CHANGE = re.compile(
    r"\b(arquiv|código|codigo|implement|cri[ae]|corrig|corrij|bug|refator|fun[cç]|classe|pasta|diret[oó]ri|"
    r"edit|escrev|script|módulo|modulo|site|p[aá]gina|html|adicion|remov|alter|deix|gere|build|compil|passand)",
    re.IGNORECASE,
)
# Trecho negado ("não altere nenhum arquivo") não conta como pedido de mudança: ele restringe.
_NEGATED_CLAUSE = re.compile(r"\b(?:n[ãa]o|sem|nunca)\b[^.;,]{0,40}", re.IGNORECASE)


def _items(text: str | None) -> list[str]:
    return [m.group(1) for line in (text or "").splitlines() if (m := _ITEM.match(line))]


def evidence_kind(text: str) -> str:
    """`change` exige verificador (teste, sintaxe, arquivo); `answer` aceita a resposta final verificada."""
    cleaned = _NEGATED_CLAUSE.sub(" ", text or "")
    return "change" if _CHANGE.search(cleaned) else "answer"


def derive_requirements(objective: str, acceptance_criteria: str | None = None) -> list[dict[str, Any]]:
    """Requisitos determinísticos a partir do texto: cada item enumerado do objetivo e cada linha dos
    critérios de aceite vira um requisito; sem itens, o objetivo inteiro é o requisito R1."""
    whole = " ".join((objective or "").split())
    kind = evidence_kind(whole)
    found: list[tuple[str, str]] = [(item, "objetivo") for item in _items(objective)]
    criteria = _items(acceptance_criteria) or [
        line.strip() for line in (acceptance_criteria or "").splitlines() if line.strip()
    ]
    found += [(item, "critérios de aceite") for item in criteria]
    if not found:
        found = [(whole[:500] or "objetivo vazio", "objetivo")]
    reqs = []
    for index, (text, origin) in enumerate(found, start=1):
        reqs.append(
            {
                "id": f"R{index}",
                "description": text,
                "origin": origin,
                "criterion": text if origin == "critérios de aceite" else f"Atendido com evidência: {text}",
                "applicability": MANDATORY,
                "evidence": "change" if kind == "change" or evidence_kind(text) == "change" else "answer",
                "refs": [],
            }
        )
    return reqs


def normalize_requirement(raw: dict[str, Any], index: int) -> dict[str, Any]:
    description = str(raw.get("description") or raw.get("text") or "").strip()
    applicability = raw.get("applicability") or (MANDATORY if raw.get("mandatory", True) else "informativo")
    return {
        "id": str(raw.get("id") or f"R{index}"),
        "description": description,
        "origin": raw.get("origin") or "contrato",
        "criterion": str(raw.get("criterion") or "").strip(),
        "applicability": applicability if applicability in APPLICABILITY else MANDATORY,
        "evidence": raw.get("evidence") if raw.get("evidence") in {"change", "answer"} else evidence_kind(description),
        "refs": list(raw.get("refs") or []),
        **({"blocked_reason": raw["blocked_reason"]} if raw.get("blocked_reason") else {}),
    }


def root_of(session: Session, task: TaskModel) -> TaskModel:
    seen: set[uuid.UUID] = set()
    while task.parent_id and task.parent_id not in seen:
        seen.add(task.id)
        parent = session.get(TaskModel, task.parent_id)
        if parent is None:
            break
        task = parent
    return task


def ensure_requirements(session: Session, root: TaskModel) -> list[dict[str, Any]]:
    """Lê os requisitos do contrato da raiz; se não houver, deriva do objetivo e grava, para os ids
    ficarem estáveis entre passos, replanejamentos e retomadas."""
    contracts = ContractService(session)
    row = contracts.get(root.id)
    acceptance = dict((row.acceptance_json if row else None) or {})
    stored = acceptance.get("requirements")
    if isinstance(stored, list) and stored:
        reqs = [normalize_requirement(r, i) for i, r in enumerate(stored, start=1) if isinstance(r, dict)]
        if reqs != stored:
            contracts.upsert(root.id, acceptance={**acceptance, "requirements": reqs})
        return reqs
    reqs = derive_requirements(root.objective, root.acceptance_criteria)
    contracts.upsert(root.id, acceptance={**acceptance, "requirements": reqs})
    return reqs


def load_requirements(session: Session, root: TaskModel) -> list[dict[str, Any]]:
    """Requisitos gravados, sem derivar nem gravar (leitura pura)."""
    row = ContractService(session).get(root.id)
    stored = ((row.acceptance_json if row else None) or {}).get("requirements")
    if not isinstance(stored, list):
        return []
    return [normalize_requirement(r, i) for i, r in enumerate(stored, start=1) if isinstance(r, dict)]


def normalize_covers(raw: Any) -> list[dict[str, Any]] | None:
    """`["R1", {"req": "R2", "partial": true, "part": "API"}]` → lista uniforme; `None` se não declarado."""
    if raw is None:
        return None
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append({"req": item.strip(), "partial": False, "part": ""})
        elif isinstance(item, dict) and item.get("req"):
            out.append({"req": str(item["req"]), "partial": bool(item.get("partial")), "part": str(item.get("part") or "")})
    return out


def siblings_declare_covers(session: Session, task: TaskModel) -> bool:
    if task.parent_id is None:
        return False
    rows = session.scalars(select(TaskModel).where(TaskModel.parent_id == task.parent_id)).all()
    return any(normalize_covers((t.metadata_json or {}).get("covers")) is not None for t in rows if t.id != task.id)


def effective_covers(session: Session, task: TaskModel, reqs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Cobertura declarada da tarefa. Sem declaração: se nenhuma irmã declara, herda a do pai (cobertura
    implícita); se alguma declara, a tarefa é apoio e não cobre nada, para uma etapa sem declaração não
    mascarar um requisito esquecido. A raiz cobre todos os requisitos."""
    declared = normalize_covers((task.metadata_json or {}).get("covers"))
    if declared is not None:
        return declared
    if task.parent_id is None:
        reqs = reqs if reqs is not None else load_requirements(session, task)
        return [{"req": r["id"], "partial": False, "part": ""} for r in reqs]
    if siblings_declare_covers(session, task):
        return []
    parent = session.get(TaskModel, task.parent_id)
    return effective_covers(session, parent, reqs) if parent is not None else []


def _subtree(session: Session, root: TaskModel) -> list[TaskModel]:
    tasks = list(session.scalars(select(TaskModel).where(TaskModel.project_id == root.project_id)).all())
    ids = {root.id}
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True
    return [t for t in tasks if t.id in ids]


def _passed_current(session: Session, task_id: uuid.UUID) -> list[EvidenceModel]:
    rows = session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == task_id)).all()
    return [r for r in rows if r.passed is True and is_current((r.detail_json or {}).get("artifacts"))]


def _answered(task: TaskModel) -> bool:
    result = task.consolidated_result_json or {}
    return bool(result.get("final_answer") and str(result.get("markdown") or "").strip())


def _verification_rejected(session: Session, task: TaskModel) -> bool:
    """A etapa **concluiu** e a verificação mais recente reprovou.

    Uma etapa concluída cujo verificador reprovou não pode "cobrir" um requisito como provado:
    houve uma checagem explícita do trabalho e ela disse que o trabalho não está bom. Uma etapa
    ainda em Retry (a verificação vai rodar de novo) não conta aqui: isso é "pendente".
    """
    if TaskStatus(task.status) != TaskStatus.COMPLETED:
        return False
    from agent.orchestrator.consolidation import collect_evidences

    evs = collect_evidences(session, task.id)
    return bool(evs) and evs[-1].get("passed") is False


def _unproven_by_superseded(
    session: Session,
    root: TaskModel,
    reqs: list[dict[str, Any]],
    req_id: str,
    live_coverers: list[TaskModel],
) -> bool:
    """Uma etapa substituída tinha uma verificação que reprovou e ninguém a refez.

    O trabalho pode até ter sido refeito, mas a verificação que o justificava **não** foi
    refeita com o mesmo verificador: aceitar a evidência implícita da escrita no lugar da
    checagem declarada seria declarar provado o que ninguém provou. O estado honesto é
    "sem comprovação" — e é ele que dispara a etapa de comprovação.
    """
    from agent.orchestrator.consolidation import collect_evidences

    for task in _subtree(session, root):
        if not superseded(task):
            continue
        evs = collect_evidences(session, task.id)
        if not evs or evs[-1].get("passed") is not False:
            continue
        covers = effective_covers(session, task, reqs)
        if not any(c["req"] == req_id for c in covers):
            continue
        verifier = str(evs[-1].get("verifier") or "")
        refez = any(
            str(ev.get("verifier") or "") == verifier
            and ev.get("passed") is True
            and is_current((ev.get("detail") or {}).get("artifacts"))
            for coverer in live_coverers
            for ev in collect_evidences(session, coverer.id)
        )
        if not refez:
            return True
    return False


def requirement_status(session: Session, root: TaskModel) -> list[dict[str, Any]]:
    """Estado de cada requisito pelas folhas que o cobrem (canceladas e substituídas não contam; raiz
    sem filhas é a própria folha):
    `uncovered` sem folha responsável; `failed`/`blocked` se uma delas parou; `pending` enquanto alguma
    não concluiu; `unverified` se todas concluíram mas falta evidência proporcional (mudança exige
    verificador aprovado e atual; resposta aceita a resposta final entregue); `satisfied` com evidência.
    Requisito não obrigatório devolve a própria aplicabilidade."""
    reqs = load_requirements(session, root)
    tasks = _subtree(session, root)
    parents = {t.parent_id for t in tasks if t.parent_id}
    live = [
        t
        for t in tasks
        if t.id not in parents
        and TaskStatus(t.status) != TaskStatus.CANCELLED
        and not superseded(t)
    ]
    covers_by_task = {t.id: effective_covers(session, t, reqs) for t in live}
    report = []
    for req in reqs:
        entry = {**req, "tasks": [], "partial": False, "evidence_ids": []}
        if req["applicability"] != MANDATORY:
            entry["status"] = req["applicability"].replace(" ", "_")
            report.append(entry)
            continue
        coverers = [t for t in live if any(c["req"] == req["id"] for c in covers_by_task[t.id])]
        entry["tasks"] = [str(t.id) for t in coverers]
        entry["partial"] = bool(coverers) and all(
            c["partial"] for t in coverers for c in covers_by_task[t.id] if c["req"] == req["id"]
        )
        statuses = {TaskStatus(t.status) for t in coverers}
        rejected = [t for t in coverers if _verification_rejected(session, t)]
        if not coverers:
            entry["status"] = "uncovered"
        elif TaskStatus.FAILED in statuses:
            entry["status"] = "failed"
        elif TaskStatus.BLOCKED in statuses:
            entry["status"] = "blocked"
        elif rejected:
            # Houve uma checagem do trabalho e ela reprovou: o requisito não está provado,
            # mesmo que outra etapa tenha produzido evidência. Sem isso, um replanejamento
            # que trocou a verificação por uma evidência mais fraca "aprovaria" o requisito.
            entry["status"] = "failed"
            entry["rejected_by"] = [str(t.id) for t in rejected]
        elif _unproven_by_superseded(session, root, reqs, req["id"], coverers):
            # A etapa substituída tinha uma verificação que reprovou e nenhuma etapa viva
            # refez **aquela** verificação: o requisito fica sem comprovação — e a etapa de
            # comprovação entra. Sem isso, um replanejamento trocaria a checagem declarada
            # por uma evidência mais fraca e o requisito seria dado por provado.
            entry["status"] = "unverified"
        else:
            evidence = [e for t in coverers for e in _passed_current(session, t.id)]
            if req["evidence"] == "change":
                evidence = [e for e in evidence if e.verifier != "final_answer"]
                ok = bool(evidence)
            else:
                ok = bool(evidence) or any(_answered(t) for t in coverers)
            entry["evidence_ids"] = [str(e.id) for e in evidence]
            # A verificação global é uma **porta**: enquanto ela não rodar, o requisito não está
            # aceito, mesmo que as etapas individuais tenham evidência. As outras etapas não
            # seguram o requisito: uma etapa de apoio ainda pendente não invalida a prova.
            gate_pending = any(
                (t.metadata_json or {}).get("global_verification_step")
                and TaskStatus(t.status) != TaskStatus.COMPLETED
                for t in coverers
            )
            if ok and not gate_pending:
                entry["status"] = "satisfied"
            elif statuses != {TaskStatus.COMPLETED} or not all(
                verification_evidence_ok(session, t) for t in coverers
            ):
                entry["status"] = "pending"
            else:
                entry["status"] = "unverified"
        report.append(entry)
    return report
