"""
Arquivo: src/agent/domain/work_flow.py
Nome: work_flow.py
Propósito: etapas do fluxo de trabalho (Kanban), portões de qualidade G0–G4 e a avaliação da entrega em cinco dimensões, calculados a partir de um retrato da tarefa.
Responsabilidade: camada de domínio — regras puras de aprovação organizacional, sem I/O.
Componentes: WorkStage, GateVerdict, WorkSnapshot, evaluate_gates, stage_for, evaluate_delivery.
Dependências: agent.domain.enums, agent.domain.organization, dataclasses, enum.
Observações: não é uma segunda máquina de estados — a etapa é **derivada** do `TaskStatus` e dos
portões; e os portões não verificam nada sozinhos: leem as evidências que o `VerificationGate`
gravou e as revisões registradas. Falha eliminatória reprova; não há média que esconda falha.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent.domain.enums import TaskStatus
from agent.domain.organization import reviewer_allowed


class WorkStage(StrEnum):
    """Etapa organizacional da tarefa, derivada do status e dos portões."""

    INBOX = "INBOX"
    ANALYSIS = "ANALYSIS"
    ARCHITECTURE_REVIEW = "ARCHITECTURE_REVIEW"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    IMPLEMENTATION_COMPLETE = "IMPLEMENTATION_COMPLETE"
    QA_REVIEW = "QA_REVIEW"
    TECHNICAL_AUDIT = "TECHNICAL_AUDIT"
    READY_FOR_INTEGRATION = "READY_FOR_INTEGRATION"
    INTEGRATED = "INTEGRATED"
    DONE = "DONE"
    REWORK = "REWORK"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Ordem das etapas do fluxo principal (as de exceção ficam fora).
STAGE_ORDER: tuple[WorkStage, ...] = (
    WorkStage.INBOX,
    WorkStage.ANALYSIS,
    WorkStage.ARCHITECTURE_REVIEW,
    WorkStage.READY,
    WorkStage.IN_PROGRESS,
    WorkStage.IMPLEMENTATION_COMPLETE,
    WorkStage.QA_REVIEW,
    WorkStage.TECHNICAL_AUDIT,
    WorkStage.READY_FOR_INTEGRATION,
    WorkStage.INTEGRATED,
    WorkStage.DONE,
)

PASSED = "passed"
FAILED = "failed"
PENDING = "pending"
NOT_APPLICABLE = "not_applicable"


@dataclass
class GateVerdict:
    """Veredito de um portão: estado, verificações feitas e motivos de reprovação."""

    id: str
    name: str
    state: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON) do veredito."""
        return {"id": self.id, "name": self.name, "state": self.state,
                "checks": list(self.checks), "blocking": list(self.blocking)}


@dataclass
class WorkSnapshot:
    """Retrato da tarefa usado pelos portões. Montado do estado persistido pelo serviço.

    Atributos:
        status: `TaskStatus` atual.
        objective: objetivo da tarefa.
        acceptance: critério de aceite textual.
        requirements: requisitos registrados (texto).
        assignment: atribuição organizacional (`Assignment.to_dict()`), quando houver.
        allowed_files: escopo de escrita da tarefa (vazio = sem restrição declarada).
        changed_files: arquivos alterados com sucesso.
        evidences: evidências em ordem cronológica, cada uma com `verifier`, `passed` e `id`.
        reviews: revisões registradas (`role`, `decision`, `reason`).
        read_only: a etapa só lê.
        is_root: tarefa raiz (objetivo do usuário).
        children: status das tarefas filhas.
        blocked_reason: motivo de bloqueio registrado.
        verification_attempts: verificações executadas.
    """

    status: str
    objective: str = ""
    acceptance: str = ""
    requirements: list[str] = field(default_factory=list)
    assignment: dict[str, Any] | None = None
    allowed_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    evidences: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    read_only: bool = False
    is_root: bool = False
    children: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    verification_attempts: int = 0


_EXECUTED = frozenset({TaskStatus.VERIFYING, TaskStatus.COMPLETED, TaskStatus.RETRY_PENDING, TaskStatus.FAILED})


def _norm(path: str) -> str:
    """Caminho comparável: barras normais, sem `./`."""
    clean = str(path).replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean.lstrip("/")


def out_of_scope(snapshot: WorkSnapshot) -> list[str]:
    """Arquivos alterados fora do escopo declarado (nada quando o escopo não foi declarado)."""
    if not snapshot.allowed_files:
        return []
    allowed = {_norm(p) for p in snapshot.allowed_files}
    folders = tuple(p if p.endswith("/") else p + "/" for p in allowed)
    return [p for p in snapshot.changed_files if _norm(p) not in allowed and not _norm(p).startswith(folders)]


def _check(name: str, ok: bool | None, detail: str = "", *, eliminatory: bool = True) -> dict[str, Any]:
    """Uma verificação de portão; `ok=None` quer dizer ainda não verificável."""
    return {"name": name, "ok": ok, "detail": detail, "eliminatory": eliminatory}


def _state(checks: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Estado do portão: reprova se uma eliminatória falhou, pendente se alguma não é verificável."""
    blocking = [c["name"] + (f": {c['detail']}" if c["detail"] else "") for c in checks
                if c["ok"] is False and c["eliminatory"]]
    if blocking:
        return FAILED, blocking
    if any(c["ok"] is None and c["eliminatory"] for c in checks):
        return PENDING, []
    return PASSED, []


def _independent_reviews(snapshot: WorkSnapshot) -> list[dict[str, Any]]:
    """Revisões feitas por papel que pode revisar o executor (nunca o próprio executor)."""
    executor = (snapshot.assignment or {}).get("role", "")
    return [r for r in snapshot.reviews if reviewer_allowed(executor, str(r.get("role") or ""))]


def evaluate_gates(snapshot: WorkSnapshot) -> list[GateVerdict]:
    """Avalia os cinco portões da tarefa.

    G0 planejamento, G1 implementação, G2 QA (veredito do portão de verificação único),
    G3 auditoria técnica (independência, área protegida, revisão registrada) e G4 integração.

    Args:
        snapshot: retrato da tarefa.

    Returns:
        Os vereditos na ordem G0…G4.
    """
    status = TaskStatus(snapshot.status)
    assignment = snapshot.assignment or {}
    executed = status in _EXECUTED
    verdicts: list[GateVerdict] = []

    g0 = [
        _check("objetivo", bool(snapshot.objective.strip()), "" if snapshot.objective.strip() else "vazio"),
        _check("critério de aceite ou requisitos", bool(snapshot.acceptance.strip() or snapshot.requirements)),
        _check("responsável", bool(assignment.get("role")), assignment.get("role", "sem atribuição")),
        _check("revisor independente", bool(assignment.get("reviewer_role"))
               and assignment.get("reviewer_role") != assignment.get("role")),
        _check("confiança da atribuição", not assignment.get("needs_investigation", False),
               "investigar antes de executar" if assignment.get("needs_investigation") else "", eliminatory=False),
        _check("risco classificado", bool(assignment.get("risk")), str(assignment.get("risk") or ""), eliminatory=False),
    ]
    verdicts.append(_verdict("G0", "Planejamento", g0))

    scope_leak = out_of_scope(snapshot)
    g1 = [
        _check("executada", True if executed else None),
        _check("escopo respeitado", (not scope_leak) if executed else None, ", ".join(scope_leak[:5])),
        _check("alteração registrada", (bool(snapshot.changed_files) or snapshot.read_only or snapshot.is_root)
               if executed else None, eliminatory=False),
    ]
    verdicts.append(_verdict("G1", "Implementação", g1))

    last = snapshot.evidences[-1] if snapshot.evidences else None
    if last is None:
        qa_ok: bool | None = None if status not in {TaskStatus.COMPLETED, TaskStatus.FAILED} else False
        qa_detail = "sem evidência de verificação"
    else:
        qa_ok = last.get("passed")
        qa_detail = f"{last.get('verifier')}: {str(last.get('summary') or '')[:160]}"
    failed_before = sum(1 for e in snapshot.evidences[:-1] if e.get("passed") is False)
    g2 = [
        _check("verificação independente aprovou", qa_ok, qa_detail),
        _check("aprovada na primeira verificação", failed_before == 0 if last else None,
               f"{failed_before} reprovação(ões) antes" if failed_before else "", eliminatory=False),
    ]
    verdicts.append(_verdict("G2", "QA", g2))

    reviews = _independent_reviews(snapshot)
    rejected = [r for r in reviews if r.get("decision") == "rejected"]
    approved = [r for r in reviews if r.get("decision") == "approved"]
    needs_review = bool(assignment.get("protected_files")) or bool(assignment.get("shared_contracts"))
    self_review = [r for r in snapshot.reviews if r.get("role") == assignment.get("role")]
    g3 = [
        _check("QA aprovado", True if qa_ok else (None if qa_ok is None else False)),
        _check("nenhuma revisão independente reprovou", not rejected,
               "; ".join(str(r.get("reason") or "")[:120] for r in rejected)),
        _check("sem autoaprovação", not self_review,
               "o executor tentou aprovar o próprio trabalho" if self_review else ""),
        # Sem revisão ainda é espera, não reprovação: a reprovação vem da revisão que reprova.
        _check("revisão de área protegida ou contrato", ((True if approved else None) if needs_review else True)
               if qa_ok else None,
               "exige revisão registrada do papel de coordenação" if needs_review and not approved else ""),
    ]
    verdicts.append(_verdict("G3", "Auditoria técnica", g3))

    open_children = [s for s in snapshot.children if s not in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value}]
    previous_failed = [v.id for v in verdicts if v.state == FAILED]
    previous_pending = any(v.state == PENDING for v in verdicts)
    g4 = [
        _check("portões anteriores aprovados",
               False if previous_failed else (None if previous_pending else True), ", ".join(previous_failed)),
        _check("subtarefas concluídas", not open_children if snapshot.children else True,
               f"{len(open_children)} em aberto" if open_children else ""),
        _check("sem bloqueio pendente", not snapshot.blocked_reason, snapshot.blocked_reason[:160]),
        _check("tarefa concluída", True if status == TaskStatus.COMPLETED else None),
    ]
    verdicts.append(_verdict("G4", "Integração", g4))
    return verdicts


def _verdict(gate_id: str, name: str, checks: list[dict[str, Any]]) -> GateVerdict:
    """Monta o veredito de um portão a partir das verificações."""
    state, blocking = _state(checks)
    return GateVerdict(gate_id, name, state, checks, blocking)


def stage_for(snapshot: WorkSnapshot, gates: list[GateVerdict]) -> WorkStage:
    """Etapa organizacional atual, derivada do status e dos portões.

    Args:
        snapshot: retrato da tarefa.
        gates: vereditos de `evaluate_gates`.

    Returns:
        A etapa do Kanban em que a tarefa está.
    """
    status = TaskStatus(snapshot.status)
    by_id = {g.id: g for g in gates}
    if status == TaskStatus.CANCELLED:
        return WorkStage.CANCELLED
    if status == TaskStatus.BLOCKED:
        return WorkStage.BLOCKED
    if status == TaskStatus.FAILED:
        return WorkStage.FAILED
    if status == TaskStatus.RETRY_PENDING:
        return WorkStage.REWORK
    if status == TaskStatus.PENDING:
        return WorkStage.INBOX if by_id["G0"].state != PASSED else WorkStage.READY
    if status == TaskStatus.PLANNING:
        needs_architect = bool((snapshot.assignment or {}).get("protected_files"))
        return WorkStage.ARCHITECTURE_REVIEW if needs_architect else WorkStage.ANALYSIS
    if status == TaskStatus.READY:
        return WorkStage.READY
    if status == TaskStatus.RUNNING:
        return WorkStage.IN_PROGRESS
    if status == TaskStatus.VERIFYING:
        return WorkStage.QA_REVIEW if snapshot.evidences else WorkStage.IMPLEMENTATION_COMPLETE
    # COMPLETED: o status diz "verificado"; os portões dizem se a organização já aceitou.
    if by_id["G2"].state == FAILED or by_id["G3"].state == FAILED:
        return WorkStage.REWORK
    if by_id["G3"].state == PENDING:
        return WorkStage.TECHNICAL_AUDIT
    if by_id["G4"].state != PASSED:
        return WorkStage.READY_FOR_INTEGRATION
    return WorkStage.DONE if snapshot.is_root else WorkStage.INTEGRATED


def evaluate_delivery(snapshot: WorkSnapshot, gates: list[GateVerdict]) -> dict[str, Any]:
    """Avaliação da entrega em cinco dimensões, sem média que esconda falha eliminatória.

    Cada dimensão diz `ok` (`True`, `False` ou `None` quando não há como medir) e a origem da
    medida. `accepted` só é verdadeiro quando nenhuma dimensão eliminatória falhou e todas
    as eliminatórias foram medidas.

    Args:
        snapshot: retrato da tarefa.
        gates: vereditos de `evaluate_gates`.

    Returns:
        `{"dimensions": [...], "accepted": bool | None, "eliminatory_failures": [...]}`.
    """
    by_id = {g.id: g for g in gates}

    def gate_ok(gate_id: str) -> bool | None:
        state = by_id[gate_id].state
        return True if state == PASSED else (False if state == FAILED else None)

    scope_ok = next((c["ok"] for c in by_id["G1"].checks if c["name"] == "escopo respeitado"), None)
    verifications = max(snapshot.verification_attempts, len(snapshot.evidences))
    efficiency: bool | None = None if verifications == 0 else verifications <= 2
    dims = [
        {"id": "correctness", "name": "Correção", "ok": gate_ok("G2"), "eliminatory": True,
         "source": "última evidência do portão de verificação"},
        {"id": "architecture", "name": "Arquitetura",
         "ok": None if scope_ok is None else (scope_ok and by_id["G3"].state != FAILED), "eliminatory": True,
         "source": "escopo de escrita e auditoria técnica (G1, G3)"},
        {"id": "quality", "name": "Qualidade", "ok": gate_ok("G3"), "eliminatory": True,
         "source": "independência e revisões registradas (G3)"},
        {"id": "maintainability", "name": "Manutenção", "ok": None, "eliminatory": False,
         "source": "não disponível: o Callidus ainda não mede manutenibilidade por tarefa"},
        {"id": "efficiency", "name": "Eficiência", "ok": efficiency, "eliminatory": False,
         "source": f"{verifications} verificação(ões) até o veredito"},
    ]
    failures = [d["name"] for d in dims if d["eliminatory"] and d["ok"] is False]
    unmeasured = [d for d in dims if d["eliminatory"] and d["ok"] is None]
    accepted: bool | None = False if failures else (None if unmeasured else True)
    return {"dimensions": dims, "accepted": accepted, "eliminatory_failures": failures}
