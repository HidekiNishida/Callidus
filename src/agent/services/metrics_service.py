"""
Arquivo: src/agent/services/metrics_service.py
Nome: metrics_service.py
Propósito: agregar as métricas de execução do projeto e de cada run.
Responsabilidade: camada de aplicação — leitura das evidências persistidas e consolidação dos indicadores.
Componentes: MetricsService.
Dependências: agent.persistence.models, sqlalchemy.
Observações: nenhuma pontuação agregada substitui o aceite por requisito.
"""
from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.persistence.models import (
    ContextSnapshotModel,
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    OperationAttemptModel,
    TaskModel,
)


class MetricsService:
    """Consolida os indicadores de execução a partir do que já está persistido.

    Atributos:
        _session: sessão usada nas consultas.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    def project_metrics(self, project_id: uuid.UUID) -> dict:
        """Indicadores agregados de um projeto.

        Args:
            project_id: projeto consultado.

        Returns:
            Um dicionário com tarefas, tentativas, chamadas de modelo, tokens estimados e profundidade máxima.
        """
        tasks = list(
            self._session.scalars(select(TaskModel).where(TaskModel.project_id == project_id)).all()
        )
        task_ids = [t.id for t in tasks]
        attempts = 0
        model_calls = 0
        if task_ids:
            attempts = self._session.scalar(
                select(func.count()).select_from(OperationAttemptModel).where(
                    OperationAttemptModel.task_id.in_(task_ids)
                )
            ) or 0
            model_calls = self._session.scalar(
                select(func.count()).select_from(OperationAttemptModel).where(
                    OperationAttemptModel.task_id.in_(task_ids),
                    OperationAttemptModel.kind == "model",
                )
            ) or 0
        tokens = self._session.scalar(
            select(func.sum(ContextSnapshotModel.estimated_tokens)).where(
                ContextSnapshotModel.project_id == project_id
            )
        ) or 0
        depth = self._max_depth(tasks)
        return {
            "tasks": len(tasks),
            "attempts": attempts,
            "model_calls": model_calls,
            "estimated_context_tokens": int(tokens),
            "max_task_depth": depth,
        }

    def run_metrics(self, run_id: uuid.UUID) -> dict | None:
        """Métricas de um run a partir do que já é persistido (tarefas, tentativas, eventos, snapshots,
        evidências). `progress` separa atividade de progresso: passos e chamadas de modelo desde a última
        vez que o estado verificável melhorou (`orchestrator/progress.made_progress`). `requirements` vem do
        aceite por requisito; nenhuma pontuação agregada substitui esse aceite."""
        from agent.orchestrator.global_verify import requirements_report
        from agent.orchestrator.progress import made_progress, subtree

        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            return None
        tasks = subtree(self._session, run.root_task_id)
        task_ids = [t.id for t in tasks]
        attempts = list(
            self._session.scalars(
                select(OperationAttemptModel)
                .where(OperationAttemptModel.run_id == run_id)
                .order_by(OperationAttemptModel.created_at)
            ).all()
        )
        events = list(
            self._session.scalars(
                select(EventLogModel).where(EventLogModel.run_id == run_id).order_by(EventLogModel.created_at)
            ).all()
        )
        snapshots = list(
            self._session.scalars(select(ContextSnapshotModel).where(ContextSnapshotModel.run_id == run_id)).all()
        )
        evidences = list(
            self._session.scalars(select(EvidenceModel).where(EvidenceModel.task_id.in_(task_ids))).all()
        ) if task_ids else []

        actions = [e.payload_json or {} for e in events if e.event_type == "orchestrator.action"]
        action_counts = Counter(a.get("action") for a in actions)
        errors = Counter(
            ((e.payload_json or {}).get("failure") or {}).get("category")
            for e in events
            if e.event_type == "attempt.recorded" and (e.payload_json or {}).get("failure")
        )
        per_task = Counter(a.task_id for a in attempts)
        prompts = Counter(
            (a.request_json or {}).get("prompt_fp") for a in attempts if (a.request_json or {}).get("prompt_fp")
        )
        omitted = Counter(name for s in snapshots for name in (s.refs_json or []) if isinstance(name, str))

        last_state = None
        steps_since = 0
        for a in actions:
            state = a.get("progress")
            if state is None:
                continue
            if made_progress(last_state, state):
                steps_since = 0
            else:
                steps_since += 1
            last_state = state
        calls_since = self._model_calls_since_progress(attempts, events)

        usage = Counter()
        for t in tasks:
            for key, value in ((t.metadata_json or {}).get("usage") or {}).items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                usage[key] += int(value)
        statuses = Counter(t.status for t in tasks)
        stale = sum(
            1 for e in evidences if e.passed is True and not _current(e)
        )
        root = self._session.get(TaskModel, run.root_task_id)
        reqs = requirements_report(self._session, root) if root is not None else []
        failures = [f for t in tasks for f in ((t.metadata_json or {}).get("failures") or [])]
        signatures = Counter((f.get("signature"), f.get("strategy")) for f in failures if f.get("signature"))
        pauses = [e.payload_json or {} for e in events if e.event_type == "run.paused"]
        artifacts = {
            path
            for e in evidences
            if e.passed is True and _current(e)
            for path in (((e.detail_json or {}).get("artifacts") or {}).get("paths") or [])
        }
        started = _naive(run.created_at)
        finished = _naive(events[-1].created_at if events else run.updated_at)
        return {
            "run_id": str(run_id),
            "status": run.status,
            "tree": {
                "tasks": len(tasks),
                "max_depth": self._max_depth(tasks),
                "by_status": dict(statuses),
                "reopened": sum(len(a.get("reopened") or []) for a in actions if a.get("action") == "global_verify_reopen"),
            },
            "decompositions": action_counts.get("decomposed", 0),
            "replans": action_counts.get("replanned", 0),
            "attempts": {
                "total": len(attempts),
                "by_kind": dict(Counter(a.kind for a in attempts)),
                "max_per_task": max(per_task.values(), default=0),
                "strategies": len(prompts),
                "repeated_prompts": sum(n - 1 for n in prompts.values() if n > 1),
                "repeated_outputs": action_counts.get("blocked_loop", 0),
            },
            "tokens": {
                "estimated_context": int(sum(s.estimated_tokens or 0 for s in snapshots)),
                "reported": dict(usage),
                "accounted": _accounted(self._session, run_id),
            },
            "omitted_context": dict(omitted),
            "errors_by_category": dict(errors),
            "time": {
                "started_at": started.isoformat() if started else None,
                "last_event_at": finished.isoformat() if finished else None,
                "elapsed_sec": round((finished - started).total_seconds(), 3) if finished and started else None,
            },
            "evidence": {
                "passed": sum(1 for e in evidences if e.passed is True),
                "failed": sum(1 for e in evidences if e.passed is False),
                "inconclusive": sum(1 for e in evidences if e.passed is None),
                "stale": stale,
            },
            "requirements": {
                "total": len(reqs),
                "satisfied": sum(1 for r in reqs if r["status"] == "satisfied"),
                "unmet": [r["id"] for r in reqs if r["status"] not in {"satisfied", "não_aplicável", "informativo"}],
                "by_status": dict(Counter(r["status"] for r in reqs)),
            },
            "stagnation": {
                "detected": sum(1 for e in events if e.event_type == "run.stagnation"),
                "repeated_errors": sum(n - 1 for n in signatures.values() if n > 1),
                "max_attempts_per_strategy": max(signatures.values(), default=0),
                "replans_refused": sum(1 for t in tasks if (t.metadata_json or {}).get("replan_refused")),
            },
            "pauses": [
                {"reason": p.get("reason"), "limit": (p.get("limit") or {}).get("limit"), "next_action": p.get("next_action")}
                for p in pauses
            ],
            "resumes": sum(1 for e in events if e.event_type == "run.resumed"),
            "artifacts_validated": sorted(artifacts),
            "progress": {
                "state": last_state,
                "steps_since_progress": steps_since,
                "model_calls_since_progress": calls_since,
            },
        }

    @staticmethod
    def _model_calls_since_progress(attempts: list, events: list) -> int:
        """Chamadas de modelo feitas desde a última melhora de estado verificável.

        Args:
            attempts: tentativas do run, em ordem cronológica.
            events: eventos do run.

        Returns:
            A quantidade de chamadas ao modelo após a última melhora.
        """
        from agent.orchestrator.progress import made_progress

        last_progress_at = None
        last_state = None
        for e in events:
            payload = e.payload_json or {}
            if e.event_type != "orchestrator.action" or payload.get("progress") is None:
                continue
            if made_progress(last_state, payload["progress"]):
                last_progress_at = _naive(e.created_at)
            last_state = payload["progress"]
        return sum(
            1 for a in attempts if a.kind == "model" and (last_progress_at is None or _naive(a.created_at) > last_progress_at)
        )

    @staticmethod
    def _max_depth(tasks: list[TaskModel]) -> int:
        """Profundidade máxima da árvore de tarefas.

        Args:
            tasks: tarefas consideradas.

        Returns:
            A maior distância entre uma tarefa e a raiz da sua árvore.
        """
        by_id = {t.id: t for t in tasks}
        best = 0
        for t in tasks:
            d = 0
            cur = t
            while cur.parent_id and cur.parent_id in by_id:
                d += 1
                cur = by_id[cur.parent_id]
            best = max(best, d)
        return best


def _accounted(session: Session, run_id: uuid.UUID) -> dict:
    """Totais do livro-razão da execução, separados da estimativa de janela.

    Args:
        session: sessão do banco.
        run_id: execução consultada.

    Returns:
        O gasto contabilizado e a qualidade. Sem registros, a medição é indisponível.
    """
    from agent.orchestrator.ledger import run_spend

    value, measurement = run_spend(session, run_id)
    return {"value": value, "measurement": measurement}


def _naive(moment):
    """SQLite devolve datas sem fuso; as ainda em memória têm UTC. Compara tudo sem fuso.

    Args:
        moment: instante lido do banco ou da memória.

    Returns:
        O instante sem fuso, ou `None` quando não há instante.
    """
    return moment.replace(tzinfo=None) if moment is not None else None


def _current(evidence: EvidenceModel) -> bool:
    """Indica se a evidência ainda corresponde ao estado do disco.

    Args:
        evidence: evidência registrada.

    Returns:
        `True` quando os artefatos avaliados não mudaram desde a verificação.
    """
    from agent.verification.fingerprint import is_current

    return is_current((evidence.detail_json or {}).get("artifacts"))
