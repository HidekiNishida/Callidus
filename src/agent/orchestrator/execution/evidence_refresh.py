"""
Arquivo: src/agent/orchestrator/execution/evidence_refresh.py
Nome: evidence_refresh.py
Propósito: reverificar, contra o disco atual, as etapas concluídas cuja evidência ficou desatualizada porque outra etapa alterou o mesmo arquivo.
Responsabilidade: camada de aplicação — localizar as etapas afetadas, rodar de novo a verificação que elas já tinham e gravar a evidência nova.
Componentes: refresh_stale_evidence.
Dependências: agent.orchestrator.requirements, agent.orchestrator.consolidation, agent.persistence.models, agent.verification.runner, agent.verification.fingerprint.
Observações: só verifica — nunca refaz o trabalho nem muda o estado da etapa; evidência nova que reprova é registrada como reprovação (a consolidação decide).

Por que existe
--------------
Visto com o `qwen3-vl:8b` na calculadora: duas etapas alteravam `main.py`. A escrita da segunda
deixava a evidência da primeira desatualizada; a consolidação reabria a primeira, que refazia a
alteração e desatualizava a segunda — sem fim, abrindo uma janela nova a cada volta. A regra
"evidência desatualizada não vale" continua; a reação muda: verificar de novo, não refazer.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import TaskStatus
from agent.orchestrator.consolidation import collect_evidences
from agent.orchestrator.execution.guards import evidence_state
from agent.persistence.models import EvidenceModel, TaskModel
from agent.verification.fingerprint import is_current
from agent.verification.fingerprint import snapshot as artifact_snapshot
from agent.verification.runner import run_verification


def _root_id(session: Session, task: TaskModel):
    """Raiz da árvore da etapa."""
    current, seen = task, set()
    while current.parent_id and current.id not in seen:
        seen.add(current.id)
        parent = session.get(TaskModel, current.parent_id)
        if parent is None:
            break
        current = parent
    return current


def _tree(session: Session, root: TaskModel) -> list[TaskModel]:
    """A raiz e todos os descendentes."""
    rows = list(session.scalars(select(TaskModel).where(TaskModel.project_id == root.project_id)).all())
    ids, changed = {root.id}, True
    while changed:
        changed = False
        for row in rows:
            if row.parent_id in ids and row.id not in ids:
                ids.add(row.id)
                changed = True
    return [row for row in rows if row.id in ids]


def _same_file(paths: list[Any], target: str) -> bool:
    """A evidência examinou o arquivo (ou o projeto inteiro)?"""
    name = str(target).replace("\\\\", "/").rsplit("/", 1)[-1]
    for raw in paths or []:
        text = str(raw).replace("\\\\", "/")
        if text in {"", ".", "./"} or text == target or text.rsplit("/", 1)[-1] == name:
            return True
    return False


async def refresh_stale_evidence(
    session: Session, *, task: TaskModel, path: str, root_path: str, approved: bool
) -> list[str]:
    """Reverifica as etapas concluídas cuja última evidência aprovada ficou desatualizada pelo arquivo `path`.

    Args:
        session: sessão do banco.
        task: etapa que acabou de gravar e ter a escrita aprovada.
        path: arquivo gravado.
        root_path: pasta de trabalho.
        approved: aprovação de ferramentas de risco do run (a verificação pode rodar testes).

    Returns:
        Os títulos das etapas reverificadas.
    """
    refreshed: list[str] = []
    for other in _tree(session, _root_id(session, task)):
        if other.id == task.id or TaskStatus(other.status) != TaskStatus.COMPLETED:
            continue
        evs = collect_evidences(session, other.id)
        if not evs or evs[-1].get("passed") is not True:
            continue
        detail = evs[-1].get("detail") or {}
        artifacts = detail.get("artifacts") or {}
        if is_current(artifacts) or not _same_file(artifacts.get("paths") or [], path):
            continue
        meta = other.metadata_json or {}
        spec = meta.get("verification") or meta.get("implicit_verification")
        if not isinstance(spec, dict) or not spec:
            continue
        result = await run_verification(project_root=root_path, spec=spec, tool_args=meta.get("tool_args") or {}, approved=approved)
        fresh = dict(result.detail) if isinstance(result.detail, dict) else {}
        snap = artifact_snapshot(root_path, spec, meta.get("tool_args") or {})
        if snap:
            fresh["artifacts"] = snap
        fresh.update(
            state=evidence_state(result.passed),
            criteria=detail.get("criteria") or {},
            command={k: v for k, v in spec.items() if k != "implicit"},
            refreshed_after=str(task.id),
        )
        session.add(
            EvidenceModel(task_id=other.id, verifier=result.verifier, passed=result.passed, summary=result.summary, detail_json=fresh)
        )
        refreshed.append(other.title)
    if refreshed:
        session.flush()
    return refreshed
