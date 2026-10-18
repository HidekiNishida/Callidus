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
_CHANGE = re.compile(
    r"\b(arquiv|código|codigo|implement|cri[ae]|corrig|bug|teste|refator|fun[cç]|classe|pasta|diret[oó]ri|"
    r"edit|escrev|script|módulo|modulo|site|p[aá]gina|html|adicion|remov|alter|gere|build|compil)",
    re.IGNORECASE,
)


def _items(text: str | None) -> list[str]:
    return [m.group(1) for line in (text or "").splitlines() if (m := _ITEM.match(line))]


def evidence_kind(text: str) -> str:
    """`change` exige verificador (teste, sintaxe, arquivo); `answer` aceita a resposta final verificada."""
    return "change" if _CHANGE.search(text or "") else "answer"


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


def effective_covers(session: Session, task: TaskModel, reqs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Cobertura declarada da tarefa; sem declaração, herda a do pai; a raiz cobre todos os requisitos."""
    declared = normalize_covers((task.metadata_json or {}).get("covers"))
    if declared is not None:
        return declared
    if task.parent_id is None:
        reqs = reqs if reqs is not None else load_requirements(session, task)
        return [{"req": r["id"], "partial": False, "part": ""} for r in reqs]
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


def requirement_status(session: Session, root: TaskModel) -> list[dict[str, Any]]:
    """Estado de cada requisito pelas folhas que o cobrem (canceladas e substituídas não contam):
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
        if t.id != root.id
        and t.id not in parents
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
        if not coverers:
            entry["status"] = "uncovered"
        elif TaskStatus.FAILED in statuses:
            entry["status"] = "failed"
        elif TaskStatus.BLOCKED in statuses:
            entry["status"] = "blocked"
        elif statuses != {TaskStatus.COMPLETED} or not all(verification_evidence_ok(session, t) for t in coverers):
            entry["status"] = "pending"
        else:
            evidence = [e for t in coverers for e in _passed_current(session, t.id)]
            if req["evidence"] == "change":
                evidence = [e for e in evidence if e.verifier != "final_answer"]
                ok = bool(evidence)
            else:
                ok = bool(evidence) or any(_answered(t) for t in coverers)
            entry["evidence_ids"] = [str(e.id) for e in evidence]
            entry["status"] = "satisfied" if ok else "unverified"
        report.append(entry)
    return report
