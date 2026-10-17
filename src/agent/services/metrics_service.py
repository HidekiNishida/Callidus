# src/agent/services/metrics_service.py — métricas agregadas de execução
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.persistence.models import ContextSnapshotModel, OperationAttemptModel, TaskModel


class MetricsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def project_metrics(self, project_id: uuid.UUID) -> dict:
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

    @staticmethod
    def _max_depth(tasks: list[TaskModel]) -> int:
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
