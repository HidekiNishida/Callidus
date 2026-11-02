"""
Arquivo: src/agent/verification/gate.py
Nome: gate.py
Propósito: portão de verificação independente entre "executado" e "concluído".
Responsabilidade: camada de aplicação — fachada nomeada sobre a verificação do caminho real
(`TaskExecutor.finalize_verification`), traduzindo o desfecho em estágios (executado → validado →
requisito satisfeito → concluído) com diagnóstico e plano de recuperação.
Componentes: VerificationStage, VerificationGate, GateResult, VERIFICATION_STAGES.
Dependências: agent.orchestrator.execution.executor, agent.persistence.models, agent.verification.recovery, pydantic, uuid.
Observações: existe **um** portão: o orquestrador, os agentes filhos e esta fachada passam pelo mesmo
`finalize_verification`. Não aciona o modelo para aprovar; o modelo produz, o runtime verifica.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from agent.domain.enums import TaskStatus
from agent.persistence.models import EvidenceModel, ExecutionRunModel, ProjectModel, TaskModel
from agent.verification.recovery import RecoveryDiagnosis

if TYPE_CHECKING:
    from agent.orchestrator.execution.executor import TaskExecutor

#: Estados distintos do ciclo de verificação. Um não implica o próximo.
VERIFICATION_STAGES = frozenset(
    {
        "executed",
        "validated",
        "requirement_satisfied",
        "completed",
    }
)


class VerificationStage(str):
    """Estágio de verificação de uma etapa.

    Atributos:
        name: `executed`, `validated`, `requirement_satisfied` ou `completed`.
    """

    EXECUTED = "executed"
    VALIDATED = "validated"
    REQUIREMENT_SATISFIED = "requirement_satisfied"
    COMPLETED = "completed"


class GateResult(BaseModel):
    """Resultado do portão de verificação.

    Atributos:
        task_id: identificador da tarefa.
        stage: estágio atual após a passagem pelo portão.
        passed: `True` quando a verificação independente aprovou.
        verifier: tipo do verificador executado.
        summary: resumo do resultado.
        diagnosis: diagnóstico da falha, quando houver.
        recovery: plano de recuperação, quando aplicável.
        blocked: `True` quando a tarefa não pode prosseguir sem intervenção.
        evidence_id: identificador da evidência gravada.
        unverified: `True` quando a etapa concluiu sem verificador automático (limitação registrada).
        action: ação devolvida pelo caminho de verificação (`verified_ok`, `verify_failed`, ...).
    """

    task_id: UUID
    stage: str
    passed: bool = False
    verifier: str | None = None
    summary: str = ""
    diagnosis: RecoveryDiagnosis | None = None
    recovery: dict[str, Any] | None = None
    blocked: bool = False
    evidence_id: UUID | None = None
    unverified: bool = False
    action: str = ""


class VerificationGate:
    """Portão de verificação independente.

    Fachada sobre `TaskExecutor.finalize_verification`, que é o único caminho de conclusão
    das etapas: quem chama o portão recebe o mesmo veredito, as mesmas evidências e o mesmo
    plano de recuperação que o orquestrador. Antes havia aqui uma segunda implementação,
    fora do fluxo real, que aprovava a etapa quando um verificador mais fraco passava depois
    do principal reprovar — um verde falso que a unificação removeu.

    Atributos:
        _executor: executor da execução (sessão, serviços, ferramentas).
    """

    def __init__(self, executor: TaskExecutor | Any) -> None:
        """Cria o portão ligado ao executor.

        Args:
            executor: `TaskExecutor` em curso, ou um objeto com `runtime` (o executor é montado
                sobre ele).
        """
        if not hasattr(executor, "finalize_verification"):
            from agent.orchestrator.execution.executor import TaskExecutor

            executor = TaskExecutor(executor.runtime)
        self._executor = executor

    async def gate(
        self,
        *,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        root_path: str,
        config: dict[str, Any] | None = None,
    ) -> GateResult:
        """Passa a tarefa pelo portão de verificação independente.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa a verificar.
            root_path: pasta de trabalho das ferramentas.
            config: mantido por compatibilidade; a configuração vem do run.

        Returns:
            O `GateResult` com o estágio atingido e, quando houver, o diagnóstico e o plano
            de recuperação.
        """
        del config
        out = await self._executor.finalize_verification(run, project, task, root_path)
        session = self._executor.runtime.session
        session.flush()
        evidence = session.scalar(
            select(EvidenceModel).where(EvidenceModel.task_id == task.id).order_by(EvidenceModel.created_at.desc())
        )
        action = str(out.get("action") or "")
        status = TaskStatus(task.status)
        recovery = out.get("recovery") if isinstance(out.get("recovery"), dict) else None
        diagnosis = None
        if recovery and isinstance(recovery.get("diagnosis"), dict):
            diagnosis = RecoveryDiagnosis(**recovery["diagnosis"])
        passed = action == "verified_ok"
        if passed:
            stage = VerificationStage.COMPLETED if status == TaskStatus.COMPLETED else VerificationStage.VALIDATED
        elif status == TaskStatus.COMPLETED:
            stage = VerificationStage.COMPLETED
        else:
            stage = VerificationStage.EXECUTED
        return GateResult(
            task_id=task.id,
            stage=stage,
            passed=passed,
            unverified=action == "completed_without_verification",
            verifier=evidence.verifier if evidence is not None else None,
            summary=evidence.summary if evidence is not None else str(out.get("action")),
            diagnosis=diagnosis,
            recovery=recovery,
            blocked=status == TaskStatus.BLOCKED,
            evidence_id=evidence.id if evidence is not None else None,
            action=action,
        )


GateResult.model_rebuild()
