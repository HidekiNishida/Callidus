"""
Arquivo: src/agent/knowledge/reliability/recovery.py
Nome: recovery.py
Propósito: recuperação de estado após falhas e reinicialização.
Responsabilidade: camada de infraestrutura — checkpoint, resume, cleanup.
Componentes: CheckpointManager, RecoveryManager, StateRecovery.
Dependências: agent.knowledge.models, agent.persistence.models, json, pickle.
Observações: checkpoints periódicos; resume automático ao reiniciar.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.persistence.models import (
    KnowledgeRequestModel,
    KnowledgeItemModel,
)
from agent.knowledge.models import KnowledgeRequestStatus
from agent.knowledge.service import KnowledgeEngineService


@dataclass
class Checkpoint:
    """Checkpoint de estado para recuperação."""

    checkpoint_id: str
    project_id: uuid.UUID
    timestamp: datetime
    pending_requests: list[dict] = field(default_factory=list)
    in_progress_acquisitions: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class CheckpointManager:
    """Gerencia checkpoints periódicos do Knowledge Engine."""

    def __init__(
        self,
        session: Session,
        checkpoint_dir: Path,
        interval_seconds: int = 300,  # 5 minutos
    ) -> None:
        self.session = session
        self.checkpoint_dir = checkpoint_dir
        self.interval_seconds = interval_seconds
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._last_checkpoint: datetime | None = None

    def should_checkpoint(self) -> bool:
        """Verifica se deve criar checkpoint."""
        if self._last_checkpoint is None:
            return True
        return (datetime.now(UTC) - self._last_checkpoint).total_seconds() >= self.interval_seconds

    def create_checkpoint(self, project_id: uuid.UUID) -> Checkpoint:
        """Cria checkpoint do estado atual."""
        service = KnowledgeEngineService(self.session)

        # Buscar requests pendentes
        pending_requests = list(self.session.scalars(
            select(KnowledgeRequestModel).where(
                KnowledgeRequestModel.project_id == project_id,
                KnowledgeRequestModel.status.in_(["pending", "in_progress"]),
            )
        ).all())

        # Buscar acquisitions em andamento (items criados recentemente mas não validados)
        recent_items = list(self.session.scalars(
            select(KnowledgeItemModel).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "unvalidated",
                KnowledgeItemModel.created_at >= datetime.now(UTC) - timedelta(hours=1),
            )
        ).all())

        checkpoint = Checkpoint(
            checkpoint_id=f"cp_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            timestamp=datetime.now(UTC),
            pending_requests=[
                {
                    "request_id": str(r.id),
                    "question": r.question,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                }
                for r in pending_requests
            ],
            in_progress_acquisitions=[
                {
                    "item_id": str(i.id),
                    "title": i.title,
                    "created_at": i.created_at.isoformat(),
                }
                for i in recent_items
            ],
            metadata={
                "pending_count": len(pending_requests),
                "in_progress_count": len(recent_items),
            },
        )

        # Salvar em arquivo
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{project_id}_{checkpoint.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump({
                "checkpoint_id": checkpoint.checkpoint_id,
                "project_id": str(checkpoint.project_id),
                "timestamp": checkpoint.timestamp.isoformat(),
                "pending_requests": checkpoint.pending_requests,
                "in_progress_acquisitions": checkpoint.in_progress_acquisitions,
                "metadata": checkpoint.metadata,
            }, f, indent=2, ensure_ascii=False)

        self._last_checkpoint = checkpoint.timestamp
        return checkpoint

    def get_latest_checkpoint(self, project_id: uuid.UUID) -> Checkpoint | None:
        """Recupera checkpoint mais recente."""
        checkpoints = list(self.checkpoint_dir.glob(f"checkpoint_{project_id}_*.json"))
        if not checkpoints:
            return None

        # Ordenar por timestamp (mais recente primeiro)
        checkpoints.sort(reverse=True)

        with open(checkpoints[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        return Checkpoint(
            checkpoint_id=data["checkpoint_id"],
            project_id=uuid.UUID(data["project_id"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            pending_requests=data["pending_requests"],
            in_progress_acquisitions=data["in_progress_acquisitions"],
            metadata=data["metadata"],
        )

    def cleanup_old_checkpoints(self, keep_count: int = 10) -> int:
        """Remove checkpoints antigos."""
        checkpoints = list(self.checkpoint_dir.glob("checkpoint_*.json"))
        checkpoints.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        removed = 0
        for cp in checkpoints[keep_count:]:
            try:
                cp.unlink()
                removed += 1
            except OSError:
                pass

        return removed


class RecoveryManager:
    """Gerencia recuperação após falhas/reinicialização."""

    def __init__(self, session: Session, checkpoint_manager: CheckpointManager) -> None:
        self.session = session
        self.checkpoint_manager = checkpoint_manager
        self.service = KnowledgeEngineService(session)

    def recover_pending_requests(self, project_id: uuid.UUID) -> dict[str, int]:
        """Recupera requests que estavam pendentes/in-progress."""
        checkpoint = self.checkpoint_manager.get_latest_checkpoint(project_id)
        if not checkpoint:
            return {"recovered": 0, "failed": 0, "message": "Nenhum checkpoint encontrado"}

        recovered = 0
        failed = 0

        for req_data in checkpoint.pending_requests:
            request_id = uuid.UUID(req_data["request_id"])
            request = self.session.get(KnowledgeRequestModel, request_id)

            if not request:
                failed += 1
                continue

            if request.status == "in_progress":
                # Verificar se travou (iniciado há muito tempo)
                if request.started_at:
                    elapsed = (datetime.now(UTC) - request.started_at).total_seconds()
                    if elapsed > 600:  # 10 minutos
                        # Marcar como failed para retry
                        request.status = "failed"
                        request.error_message = "Recuperado após timeout - travado em in_progress"
                        request.completed_at = datetime.now(UTC)
                        self.service.update_request_status(request_id, "failed", error_message=request.error_message)
                        recovered += 1
                    else:
                        # Ainda dentro do timeout - deixar como in_progress
                        recovered += 1
                else:
                    # pending - pode continuar
                    recovered += 1
            elif request.status == "pending":
                recovered += 1

        self.session.flush()
        return {"recovered": recovered, "failed": failed}

    def recover_stale_acquisitions(self, project_id: uuid.UUID, max_age_hours: int = 2) -> dict[str, int]:
        """Recupera items de aquisição que ficaram presos."""
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

        stale_items = list(self.session.scalars(
            select(KnowledgeItemModel).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == "unvalidated",
                KnowledgeItemModel.created_at < cutoff,
            )
        ).all())

        recovered = 0
        for item in stale_items:
            # Verificar se tem sources
            from agent.persistence.models import KnowledgeSourceModel
            sources = list(self.session.scalars(
                select(KnowledgeSourceModel).where(KnowledgeSourceModel.item_id == item.id)
            ).all())

            if not sources:
                # Item sem sources - marcar como failed
                item.validation_status = "failed"
                recovered += 1
            elif item.confidence < 0.3:
                # Baixa confiança - marcar para revisão
                item.validation_status = "failed"
                recovered += 1
            else:
                # Tentar validar automaticamente
                from agent.knowledge.learning.confidence import recalculate_confidence
                recalculate_confidence(item, self.session)
                if item.confidence >= 0.5:
                    item.validation_status = "validated"
                recovered += 1

        self.session.flush()
        return {"recovered": recovered, "total_stale": len(stale_items)}

    def full_recovery(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Executa recuperação completa."""
        results = {
            "checkpoint_found": False,
            "requests": {"recovered": 0, "failed": 0},
            "acquisitions": {"recovered": 0, "total_stale": 0},
            "cleanup": {"removed": 0},
        }

        # Recuperar requests
        req_result = self.recover_pending_requests(project_id)
        results["requests"] = req_result
        results["checkpoint_found"] = True

        # Recuperar acquisitions
        acq_result = self.recover_stale_acquisitions(project_id)
        results["acquisitions"] = acq_result

        # Limpar checkpoints antigos
        removed = self.checkpoint_manager.cleanup_old_checkpoints()
        results["cleanup"]["removed"] = removed

        return results


def auto_recover_on_startup(session: Session, checkpoint_dir: Path) -> dict[str, Any]:
    """Executa recuperação automática na inicialização para todos os projetos."""
    from agent.persistence.models import ProjectModel

    projects = list(session.scalars(select(ProjectModel)).all())
    all_results = {}

    for project in projects:
        checkpoint_manager = CheckpointManager(session, checkpoint_dir)
        recovery_manager = RecoveryManager(session, checkpoint_manager)

        result = recovery_manager.full_recovery(project.id)
        all_results[str(project.id)] = result

    return {
        "projects_processed": len(projects),
        "results": all_results,
        "timestamp": datetime.now(UTC).isoformat(),
    }