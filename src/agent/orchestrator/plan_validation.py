# src/agent/orchestrator/plan_validation.py — validação determinística do plano antes da execução
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.orchestrator.decomposition import DecompositionResult
from agent.orchestrator.consolidation import inherits_flag
from agent.orchestrator.requirements import (
    MANDATORY,
    effective_covers,
    ensure_requirements,
    normalize_covers,
    root_of,
)
from agent.persistence.models import EventLogModel, TaskDependencyModel, TaskModel
from agent.services.task_service import TaskService
from agent.tools.registry import build_default_registry, canonical_tool_id
from agent.verification.runner import VERIFIER_TYPES


class PlanVerdict(StrEnum):
    VALID = "válido"
    WARNINGS = "válido com ressalvas"
    INCONCLUSIVE = "inconclusivo"
    INCOMPLETE = "incompleto"
    INCONSISTENT = "inconsistente"
    INFEASIBLE = "inviável"


_RANK = {
    PlanVerdict.VALID: 0,
    PlanVerdict.WARNINGS: 1,
    PlanVerdict.INCONCLUSIVE: 2,
    PlanVerdict.INCOMPLETE: 3,
    PlanVerdict.INCONSISTENT: 4,
    PlanVerdict.INFEASIBLE: 5,
}
RUNNABLE = {PlanVerdict.VALID, PlanVerdict.WARNINGS, PlanVerdict.INCONCLUSIVE}

_WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "move_file", "make_dir"}
_READS_PATH = {"read_file", "edit_file"}


@dataclass
class Issue:
    code: str
    verdict: PlanVerdict
    message: str
    task_id: str | None = None


@dataclass
class PlanValidation:
    verdict: PlanVerdict
    issues: list[Issue] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    fingerprint: str = ""
    fixes: list[str] = field(default_factory=list)
    initial_verdict: str = ""

    @property
    def runnable(self) -> bool:
        return self.verdict in RUNNABLE

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        data["issues"] = [{**asdict(i), "verdict": i.verdict.value} for i in self.issues]
        return data


def sanitize_spec(plan: DecompositionResult) -> tuple[DecompositionResult, list[Issue]]:
    """Dependências por índice do plano JSON: fora do intervalo, para si mesma ou que fecham ciclo são
    removidas e registradas, em vez de sumirem em silêncio (ou derrubarem `add_dependency`)."""
    issues: list[Issue] = []
    count = len(plan.subtasks)
    kept: list[list[int]] = []
    for index, spec in enumerate(plan.subtasks):
        deps = []
        for dep in spec.depends_on_indices:
            if not 0 <= dep < count:
                issues.append(Issue("dependency_missing", PlanVerdict.INCONSISTENT, f"«{spec.title}» depende da etapa {dep}, que não existe"))
            elif dep == index:
                issues.append(Issue("dependency_self", PlanVerdict.INCONSISTENT, f"«{spec.title}» depende de si mesma"))
            elif dep not in deps:
                deps.append(dep)
        kept.append(deps)
    graph = {i: set(d) for i, d in enumerate(kept)}
    for index in range(count):
        for dep in list(graph[index]):
            if _reaches(graph, dep, index):
                graph[index].discard(dep)
                issues.append(
                    Issue(
                        "dependency_cycle",
                        PlanVerdict.INCONSISTENT,
                        f"dependência circular entre «{plan.subtasks[index].title}» e «{plan.subtasks[dep].title}»",
                    )
                )
    subtasks = [
        spec.model_copy(update={"depends_on_indices": sorted(graph[i])}) for i, spec in enumerate(plan.subtasks)
    ]
    return DecompositionResult(subtasks=subtasks, warnings=list(plan.warnings)), issues


def _reaches(graph: dict[int, set[int]], start: int, target: int) -> bool:
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def active_children(session: Session, parent_id: uuid.UUID) -> list[TaskModel]:
    """Filhos que fazem parte do plano atual (fora os cancelados por plano inválido)."""
    rows = session.scalars(select(TaskModel).where(TaskModel.parent_id == parent_id)).all()
    return [t for t in rows if not (t.metadata_json or {}).get("invalid_plan")]


def plan_fingerprint(session: Session, parent_id: uuid.UUID) -> str:
    """Muda quando entra/sai etapa, muda cobertura, ferramenta, verificação ou dependência."""
    kids = active_children(session, parent_id)
    ids = {k.id for k in kids}
    deps = session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id.in_(ids))).all() if ids else []
    payload = sorted(
        (
            str(k.id),
            k.status == TaskStatus.CANCELLED.value,
            json.dumps((k.metadata_json or {}).get("covers"), sort_keys=True, default=str),
            str((k.metadata_json or {}).get("tool")),
            json.dumps((k.metadata_json or {}).get("verification"), sort_keys=True, default=str),
        )
        for k in kids
    )
    edges = sorted((str(d.task_id), str(d.depends_on_task_id)) for d in deps)
    return hashlib.sha256(json.dumps([payload, edges]).encode()).hexdigest()[:16]


def _verifiable(task: TaskModel) -> bool:
    meta = task.metadata_json or {}
    if meta.get("verification") or meta.get("final_answer") or meta.get("model_operation"):
        return True
    if task.kind == TaskKind.SUBSYSTEM.value or not meta:
        return True
    return bool((task.acceptance_criteria or "").strip())


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def validate_children(
    session: Session,
    parent: TaskModel,
    *,
    project_root: str,
    run_config: dict[str, Any] | None = None,
    max_tasks: int | None = None,
    extra_issues: list[Issue] | None = None,
) -> PlanValidation:
    """Regras estruturais, todas determinísticas. Cobertura sem nenhuma declaração `covers` fica
    implícita: com um requisito é ressalva; com vários não dá para provar e o resultado é inconclusivo
    (a decisão semântica de um modelo não seria prova)."""
    config = run_config or {}
    issues: list[Issue] = list(extra_issues or [])
    root = root_of(session, parent)
    reqs = ensure_requirements(session, root)
    by_id = {r["id"]: r for r in reqs}
    kids = [k for k in active_children(session, parent.id) if k.status != TaskStatus.CANCELLED.value]
    blocked: list[str] = []

    if not _norm(root.objective):
        issues.append(Issue("objective_missing", PlanVerdict.INCOMPLETE, "objetivo global vazio"))
    if not reqs:
        issues.append(Issue("criteria_missing", PlanVerdict.INCOMPLETE, "objetivo sem critérios de aceite"))
    for req in reqs:
        if req["applicability"] == MANDATORY and not req["criterion"]:
            issues.append(Issue("criterion_missing", PlanVerdict.INCOMPLETE, f"{req['id']} sem critério de aceite"))
    if not kids:
        issues.append(Issue("plan_empty", PlanVerdict.INCOMPLETE, "plano sem etapas"))

    needed = [
        c for c in effective_covers(session, parent, reqs) if by_id.get(c["req"], {}).get("applicability") == MANDATORY
    ]
    declared_any = any(normalize_covers((k.metadata_json or {}).get("covers")) is not None for k in kids)
    coverage: dict[str, list[str]] = {c["req"]: [] for c in needed}
    for kid in kids:
        meta = kid.metadata_json or {}
        if not _norm(kid.objective):
            issues.append(Issue("result_unclear", PlanVerdict.INCOMPLETE, f"«{kid.title}» sem resultado esperado", str(kid.id)))
        for cover in normalize_covers(meta.get("covers")) or []:
            if cover["req"] not in by_id:
                issues.append(
                    Issue("unknown_requirement", PlanVerdict.INCONSISTENT, f"«{kid.title}» cobre {cover['req']}, que não existe", str(kid.id))
                )
        covers = effective_covers(session, kid, reqs) if declared_any else [{"req": r} for r in coverage]
        if declared_any and covers and not _verifiable(kid):
            issues.append(
                Issue("criteria_unverifiable", PlanVerdict.INCOMPLETE, f"«{kid.title}» cobre requisito sem critério verificável", str(kid.id))
            )
        for cover in covers:
            if cover["req"] in coverage:
                coverage[cover["req"]].append(str(kid.id))
        tool = canonical_tool_id(str(meta["tool"])) if meta.get("tool") else None
        if tool:
            known = {spec.id for spec in build_default_registry().list_specs()}
            if tool not in known:
                issues.append(Issue("unknown_tool", PlanVerdict.INCONSISTENT, f"«{kid.title}» usa ferramenta inexistente: {tool}", str(kid.id)))
            elif tool == "browser" and str(config.get("browser_mode") or "off") == "off":
                blocked.append(str(kid.id))
                issues.append(Issue("external_blocked", PlanVerdict.WARNINGS, f"«{kid.title}» precisa do navegador, que está desligado", str(kid.id)))
            elif build_default_registry().get_spec(tool).requires_approval and not config.get("approve_risky_tools"):
                blocked.append(str(kid.id))
                issues.append(Issue("external_blocked", PlanVerdict.WARNINGS, f"«{kid.title}» depende de aprovação para {tool}", str(kid.id)))
            path = (meta.get("tool_args") or {}).get("path")
            if tool in _READS_PATH and isinstance(path, str) and path and not (Path(project_root) / path).exists():
                if not _produced_before(session, kid, path):
                    issues.append(Issue("input_missing", PlanVerdict.WARNINGS, f"«{kid.title}» lê {path}, que não existe e nenhuma etapa anterior cria", str(kid.id)))
            if tool == "edit_file" and isinstance(path, str) and path:
                # O modelo planeja a edição com o trecho antigo que *acredita* existir. Se ele
                # não existe no arquivo, a etapa falha de certeza: melhor virar operação do
                # modelo (que inspeciona e aplica) do que executar uma edição impossível.
                anchor = (meta.get("tool_args") or {}).get("old_string")
                if isinstance(anchor, str) and anchor and not _anchor_present(project_root, path, anchor):
                    issues.append(
                        Issue(
                            "edit_anchor_missing",
                            PlanVerdict.WARNINGS,
                            f"«{kid.title}» edita {path} com um trecho que não está no arquivo",
                            str(kid.id),
                        )
                    )
        if meta.get("external"):
            blocked.append(str(kid.id))
            issues.append(Issue("external_blocked", PlanVerdict.WARNINGS, f"«{kid.title}» bloqueada por dependência externa: {meta['external']}", str(kid.id)))
        verification = meta.get("verification")
        if verification is not None and not isinstance(verification, dict):
            # Verificação em texto solto (o modelo às vezes manda "verification": "pytest"):
            # não é um contrato, e executá-la derrubaria a etapa. Vira um aviso para reparo.
            issues.append(
                Issue(
                    "unknown_verification",
                    PlanVerdict.INCONSISTENT,
                    f"«{kid.title}» declara verificação fora do formato: {str(verification)[:80]}",
                    str(kid.id),
                )
            )
        elif isinstance(verification, dict):
            vtype = str(verification.get("type") or verification.get("verification") or "")
            if vtype and vtype not in VERIFIER_TYPES:
                # Verificador inexistente só falharia na execução, depois do trabalho feito.
                issues.append(
                    Issue(
                        "unknown_verification",
                        PlanVerdict.INCONSISTENT,
                        f"«{kid.title}» declara verificação de tipo inexistente: {vtype}",
                        str(kid.id),
                    )
                )

    for req_id, owners in coverage.items():
        if not owners:
            issues.append(Issue("requirement_uncovered", PlanVerdict.INCOMPLETE, f"{req_id} ({by_id[req_id]['description'][:80]}) sem etapa responsável"))
        elif all(o in blocked for o in owners):
            issues.append(Issue("requirement_blocked", PlanVerdict.WARNINGS, f"{req_id} depende só de etapas bloqueadas"))
    if not declared_any and len(coverage) > 1:
        issues.append(Issue("coverage_implicit", PlanVerdict.INCONCLUSIVE, "o plano não declara quais requisitos cada etapa atende; cobertura não comprovada"))
    elif not declared_any and coverage:
        issues.append(Issue("coverage_implicit", PlanVerdict.WARNINGS, "cobertura implícita: todas as etapas herdam o requisito"))

    change_reqs = [by_id[r] for r in coverage if by_id[r]["evidence"] == "change"]
    changes = [k for k in kids if (k.metadata_json or {}).get("model_operation") and not (k.metadata_json or {}).get("final_answer")]
    changes += [k for k in kids if canonical_tool_id(str((k.metadata_json or {}).get("tool") or "")) in _WRITE_TOOLS]
    declared_checks = [k for k in kids if (k.metadata_json or {}).get("verification")]
    if change_reqs and changes and not declared_checks:
        issues.append(Issue("verification_implicit", PlanVerdict.WARNINGS, "nenhuma verificação declarada; só a implícita da escrita"))

    issues += _dependency_issues(session, kids)
    issues += _duplicate_issues(kids)

    if max_tasks is not None:
        total = len(_subtree_ids(session, root))
        if total > max_tasks:
            issues.append(Issue("budget_exceeded", PlanVerdict.INFEASIBLE, f"o plano leva o run a {total} tarefas, acima do limite de {max_tasks}"))
    if kids and len(blocked) == len(kids):
        issues.append(Issue("all_blocked", PlanVerdict.INFEASIBLE, "todas as etapas dependem de algo externo indisponível"))

    verdict = max((i.verdict for i in issues), key=_RANK.get, default=PlanVerdict.VALID)
    return PlanValidation(
        verdict=verdict,
        issues=issues,
        coverage=coverage,
        blocked=blocked,
        fingerprint=plan_fingerprint(session, parent.id),
    )


def _anchor_present(project_root: str, path: str, anchor: str) -> bool:
    """O trecho que a edição pretende substituir existe no arquivo?"""
    try:
        full = Path(project_root) / path
    except (TypeError, ValueError):  # pragma: no cover - caminho inválido
        return True
    if not full.is_file():
        return True  # o arquivo ainda não existe: nada a conferir
    try:
        return anchor in full.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - arquivo ilegível
        return True


def _produced_before(session: Session, task: TaskModel, path: str) -> bool:
    deps = session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id == task.id)).all()
    for dep in deps:
        other = session.get(TaskModel, dep.depends_on_task_id)
        meta = (other.metadata_json or {}) if other else {}
        if meta.get("model_operation") or path in json.dumps(meta.get("tool_args") or {}) or path in (other.objective if other else ""):
            return True
    return False


def _dependency_issues(session: Session, kids: list[TaskModel]) -> list[Issue]:
    issues = []
    ids = {k.id for k in kids}
    graph: dict[uuid.UUID, set[uuid.UUID]] = {k.id: set() for k in kids}
    for kid in kids:
        for dep in session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id == kid.id)).all():
            other = session.get(TaskModel, dep.depends_on_task_id)
            if other is None:
                issues.append(Issue("dependency_missing", PlanVerdict.INCONSISTENT, f"«{kid.title}» depende de tarefa inexistente", str(kid.id)))
            elif other.project_id != kid.project_id:
                issues.append(Issue("dependency_foreign", PlanVerdict.INCONSISTENT, f"«{kid.title}» depende de tarefa de outro projeto", str(kid.id)))
            elif other.status == TaskStatus.CANCELLED.value or (other.metadata_json or {}).get("invalid_plan"):
                issues.append(Issue("dependency_cancelled", PlanVerdict.INCONSISTENT, f"«{kid.title}» depende de «{other.title}», que foi cancelada", str(kid.id)))
            elif other.id in ids:
                graph[kid.id].add(other.id)
    for kid in kids:
        for dep in graph[kid.id]:
            if _reaches_ids(graph, dep, kid.id):
                issues.append(Issue("dependency_cycle", PlanVerdict.INCONSISTENT, f"dependência circular passando por «{kid.title}»", str(kid.id)))
                break
    return issues


def _reaches_ids(graph: dict[uuid.UUID, set[uuid.UUID]], start: uuid.UUID, target: uuid.UUID) -> bool:
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def _duplicate_issues(kids: list[TaskModel]) -> list[Issue]:
    issues = []
    seen_exact: dict[tuple, TaskModel] = {}
    seen_title: dict[str, TaskModel] = {}
    for kid in kids:
        meta = kid.metadata_json or {}
        exact = (_norm(kid.title), _norm(kid.objective), str(meta.get("tool")), json.dumps(meta.get("tool_args"), sort_keys=True, default=str))
        if exact in seen_exact:
            issues.append(Issue("duplicate_task", PlanVerdict.INCONSISTENT, f"«{kid.title}» repete outra etapa do plano", str(kid.id)))
        elif _norm(kid.title) in seen_title:
            issues.append(Issue("similar_task", PlanVerdict.WARNINGS, f"«{kid.title}» tem o mesmo título de outra etapa", str(kid.id)))
        seen_exact.setdefault(exact, kid)
        seen_title.setdefault(_norm(kid.title), kid)
    return issues


def _subtree_ids(session: Session, root: TaskModel) -> set[uuid.UUID]:
    rows = session.scalars(select(TaskModel).where(TaskModel.project_id == root.project_id)).all()
    ids = {root.id}
    changed = True
    while changed:
        changed = False
        for t in rows:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True
    return ids


def repair_steps(session: Session, parent: TaskModel, validation: PlanValidation) -> list[str]:
    """Correções locais de etapa: a etapa passa a fazer o que é possível fazer.

    São reparos **locais e seguros** — trocam o mecanismo da etapa (ferramenta, verificação,
    edição) sem mexer na estrutura do plano. Aplicados mesmo quando o plano é executável:
    uma etapa que edita um trecho inexistente falha de certeza, e consertá-la é melhor do que
    discovering a falha no meio da execução.
    """
    fixes: list[str] = []
    kids = {str(k.id): k for k in active_children(session, parent.id)}
    reqs = {r["id"]: r for r in ensure_requirements(session, root_of(session, parent))}
    for issue in validation.issues:
        kid = kids.get(issue.task_id or "")
        if kid is None:
            continue
        if issue.code == "unknown_tool":
            meta = {k: v for k, v in (kid.metadata_json or {}).items() if k not in {"tool", "tool_args"}}
            kid.metadata_json = {**meta, "model_operation": True}
            fixes.append(f"«{kid.title}» passou a operação do modelo (ferramenta inexistente)")
        elif issue.code == "unknown_verification":
            # O verificador inventado é removido: mantê-lo só faria a etapa falhar na execução.
            # Se a etapa não tinha outra ação, ela vira operação do modelo (a etapa não some).
            meta = {k: v for k, v in (kid.metadata_json or {}).items() if k != "verification"}
            if not any(meta.get(key) for key in ("tool", "model_operation", "final_answer")):
                meta["model_operation"] = True
            kid.metadata_json = meta
            fixes.append(f"«{kid.title}» perdeu a verificação de tipo inexistente")
        elif issue.code == "edit_anchor_missing":
            # A edição com um trecho que não existe falha de certeza. A etapa vira operação do
            # modelo: ela inspeciona o arquivo e aplica a mudança com o conteúdo correto.
            meta = {k: v for k, v in (kid.metadata_json or {}).items() if k not in {"tool", "tool_args"}}
            meta["model_operation"] = True
            kid.metadata_json = meta
            fixes.append(f"«{kid.title}» passou a operação do modelo (trecho de edição inexistente)")
        elif issue.code == "unknown_requirement":
            covers = [c for c in normalize_covers((kid.metadata_json or {}).get("covers")) or [] if c["req"] in reqs]
            kid.metadata_json = {**(kid.metadata_json or {}), "covers": covers}
            fixes.append(f"«{kid.title}» deixou de citar requisito inexistente")
        elif issue.code == "criteria_unverifiable":
            kid.metadata_json = {**(kid.metadata_json or {}), "covers": []}
            fixes.append(f"«{kid.title}» virou etapa de apoio (sem critério verificável)")
    session.flush()
    return fixes


def repair_plan(session: Session, parent: TaskModel, validation: PlanValidation) -> list[str]:
    """Correções automáticas seguras; devolve o que foi feito. O que não tem correção segura fica para o
    bloqueio recuperável."""
    ts = TaskService(session)
    fixes: list[str] = repair_steps(session, parent, validation)
    kids = {str(k.id): k for k in active_children(session, parent.id)}
    reqs = {r["id"]: r for r in ensure_requirements(session, root_of(session, parent))}
    for issue in validation.issues:
        kid = kids.get(issue.task_id or "")
        if issue.code == "duplicate_task" and kid and kid.status != TaskStatus.CANCELLED.value:
            _cancel(ts, kid, "etapa duplicada no plano", "duplicate")
            fixes.append(f"cancelada a duplicada «{kid.title}»")
        elif issue.code == "dependency_cancelled" and kid:
            for dep in session.scalars(select(TaskDependencyModel).where(TaskDependencyModel.task_id == kid.id)).all():
                other = session.get(TaskModel, dep.depends_on_task_id)
                if other is None or other.status == TaskStatus.CANCELLED.value or (other.metadata_json or {}).get("invalid_plan"):
                    session.delete(dep)
                    fixes.append(f"removida a dependência de «{kid.title}» em tarefa cancelada")
    session.flush()
    covered = {c["req"] for k in active_children(session, parent.id) if k.status != TaskStatus.CANCELLED.value for c in effective_covers(session, k)}
    missing = [i for i in validation.issues if i.code in {"requirement_uncovered", "criteria_unverifiable"}]
    if missing:
        final = next((k for k in active_children(session, parent.id) if (k.metadata_json or {}).get("final_answer")), None)
        for req_id in validation.coverage:
            if req_id in covered:
                continue
            req = reqs[req_id]
            task = ts.create_task(
                parent.project_id,
                TaskCreate(
                    title=f"Atender {req_id}",
                    objective=req["description"],
                    acceptance_criteria=req["criterion"],
                    kind=TaskKind.SUBSYSTEM,
                    parent_id=parent.id,
                    metadata={
                        "covers": [req_id],
                        "added_by_validation": True,
                        # A etapa criada para um requisito herda as restrições do pedido.
                        **{
                            flag: True
                            for flag in ("read_only", "protect_tests")
                            if inherits_flag(session, parent, flag)
                        },
                    },
                ),
            )
            if final is not None:
                ts.add_dependency(final.id, TaskDependencyCreate(depends_on_task_id=task.id))
            fixes.append(f"criada «Atender {req_id}» para o requisito sem etapa responsável")
    session.flush()
    return fixes


def _cancel(ts: TaskService, task: TaskModel, reason: str, kind: str = "plan") -> None:
    status = TaskStatus(task.status)
    if status == TaskStatus.PENDING or status in {TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.RETRY_PENDING, TaskStatus.BLOCKED}:
        # O motivo fica na tarefa: a consolidação precisa distinguir cancelamento previsto
        # (outra etapa assume o trabalho) de trabalho que simplesmente não foi feito.
        task.metadata_json = {**(task.metadata_json or {}), "cancelled_reason": kind, "cancel_detail": reason[:200]}
        ts.update_status(task.id, TaskStatusUpdate(status=TaskStatus.CANCELLED, reason=reason))


def record_validation(session: Session, parent: TaskModel, validation: PlanValidation, run_id: uuid.UUID | None) -> None:
    """Estado atual em `metadata.plan_validation`; cada versão do plano em um evento `plan.validated`."""
    meta = dict(parent.metadata_json or {})
    version = int((meta.get("plan_validation") or {}).get("version") or 0) + 1
    meta["plan_validation"] = {**validation.as_dict(), "version": version}
    parent.metadata_json = meta
    plan = [
        {
            "id": str(k.id),
            "title": k.title,
            "status": k.status,
            "covers": (k.metadata_json or {}).get("covers"),
            "tool": (k.metadata_json or {}).get("tool"),
            "verification": (k.metadata_json or {}).get("verification"),
        }
        for k in active_children(session, parent.id)
    ]
    session.add(
        EventLogModel(
            project_id=parent.project_id,
            run_id=run_id,
            task_id=parent.id,
            event_type="plan.validated",
            payload_json={"version": version, **validation.as_dict(), "plan": plan},
        )
    )


def validate_and_repair(
    session: Session,
    parent: TaskModel,
    *,
    project_root: str,
    run_config: dict[str, Any] | None,
    max_tasks: int | None,
    run_id: uuid.UUID | None,
    extra_issues: list[Issue] | None = None,
) -> PlanValidation:
    """Valida; aplica as correções seguras e valida de novo. Grava o resultado.
    Se ainda não puder executar, as etapas do plano são canceladas como `invalid_plan` (ficam no histórico)
    e quem chama bloqueia o pai com o motivo."""
    first = validate_children(
        session, parent, project_root=project_root, run_config=run_config, max_tasks=max_tasks, extra_issues=extra_issues
    )
    result = first
    fixes = [f"{i.message} (dependência removida)" for i in extra_issues or []]
    # Os reparos locais de etapa valem para qualquer plano: uma etapa que edita um trecho
    # inexistente ou declares um verificador que não existe falha de certeza na execução.
    step_fixes = repair_steps(session, parent, first)
    if step_fixes:
        fixes += step_fixes
        result = validate_children(
            session, parent, project_root=project_root, run_config=run_config, max_tasks=max_tasks
        )
    if not result.runnable:
        fixes += repair_plan(session, parent, result)
        result = validate_children(session, parent, project_root=project_root, run_config=run_config, max_tasks=max_tasks)
    result.fixes = fixes
    result.initial_verdict = first.verdict.value
    record_validation(session, parent, result, run_id)
    if not result.runnable:
        ts = TaskService(session)
        for kid in active_children(session, parent.id):
            kid.metadata_json = {**(kid.metadata_json or {}), "invalid_plan": True}
            _cancel(ts, kid, "plano inválido", "invalid_plan")
    return result


def summarize(validation: PlanValidation, limit: int = 4) -> str:
    worst = sorted(validation.issues, key=lambda i: -_RANK[i.verdict])[:limit]
    return f"plano {validation.verdict.value}: " + "; ".join(i.message for i in worst) if worst else f"plano {validation.verdict.value}"
