"""
Arquivo: src/agent/verification/gate.py
Nome: gate.py
Propósito: portão de verificação independente entre "executado" e "concluído".
Responsabilidade: camada de aplicação — garante que nenhuma tarefa seja declarada concluída
sem passar por verificação determinística, separa estados (executado → validado → requisito
satisfeito → concluído) e rastreia orçamento e recuperações de verificação.
Componentes: VerificationStage, VerificationGate, GateResult.
Dependências: agent.domain.enums, agent.domain.failures, agent.orchestrator.execution.executor,
agent.persistence.models, agent.verification.recovery, agent.verification.runner, pydantic, uuid.
Observações: não aciona o modelo para aprovar; o modelo produz, o runtime verifica.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from agent.domain.enums import AttemptKind, TaskStatus

from agent.domain.schemas import TaskStatusUpdate
from agent.persistence.models import (
    EvidenceModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)

if TYPE_CHECKING:
    from agent.domain.failures import Failure
    from agent.orchestrator.execution.executor import TaskExecutor
from agent.verification.alternatives import (
    AlternativeVerification,
    run_alternative_verification,
)
from agent.verification.recovery import (
    RecoveryDiagnosis,
    diagnose_verification_failure,
    plan_recovery,
    recovery_signature,
)
from agent.verification.runner import VerificationResult, run_verification

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


class VerificationGate:
    """Portão de verificação independente.

    Garante que uma tarefa só avance de "executado" para "concluído" depois de passar
    por verificação determinística (pytest, file_contains, syntax, etc.) que não depende
    do mesmo modelo que produziu a alteração.

    Atributos:
        _executor: executor da execução (fornece sessão, serviços, ferramentas).
    """

    def __init__(self, executor: TaskExecutor) -> None:
        """Cria o portão ligado ao executor.

        Args:
            executor: executor da execução em curso.
        """
        self._executor = executor

    @property
    def _session(self):
        return self._executor.runtime.session

    @property
    def _tasks(self):
        return self._executor.runtime.tasks

    @property
    def _attempts(self):
        return self._executor.runtime.attempts

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

        Fluxo:
        1. Lê o spec de verificação da tarefa (declarado ou implícito).
        2. Executa o verificador determinístico (não o modelo).
        3. Se aprovado: avança para `validated`, verifica requisitos, avança para
           `requirement_satisfied`, então `completed`.
        4. Se reprovado: diagnostica, planeja recuperação, registra evidência,
           bloqueia ou permite nova tentativa dentro do orçamento.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa a verificar.
            root_path: pasta de trabalho das ferramentas.
            config: configuração do run (aprovação de ferramentas arriscadas, etc.).

        Returns:
            O `GateResult` com o estágio atingido e, quando houver, o diagnóstico e
            o plano de recuperação.
        """
        config = config or {}
        session = self._session
        meta = task.metadata_json or {}
        spec = meta.get("verification") or meta.get("implicit_verification")
        if isinstance(spec, str):
            spec = None

        approved = bool((run.config_json or {}).get("approve_risky_tools"))
        tool_args = meta.get("tool_args") or {}

        # Tenta a verificação determinística (não aciona o modelo).
        # Se não houver spec, usa verificação implícita baseada no tipo de tarefa.
        if spec is None:
            spec = {"type": "acceptance_manual"}

        vresult = await run_verification(
            project_root=root_path,
            spec=spec,
            tool_args=tool_args,
            approved=approved,
        )

        # Grava a evidência da verificação (independente do modelo).
        attempt = self._attempts.record(
            run_id=run.id,
            task_id=task.id,
            kind=AttemptKind.VERIFICATION,
            provider=vresult.verifier,
            request=spec or {},
            response={"passed": vresult.passed, "summary": vresult.summary},
            success=vresult.passed is True,
            project_id=project.id,
        )
        evidence = EvidenceModel(
            task_id=task.id,
            attempt_id=attempt.id,
            verifier=vresult.verifier,
            passed=vresult.passed,
            summary=vresult.summary,
            detail_json={
                "state": "validated" if vresult.passed is True else "reproved",
                "criteria": self._criteria_of(task),
                "command": {k: v for k, v in (spec or {}).items() if k != "implicit"},
                "exit_code": (vresult.detail or {}).get("exit_code"),
            },
        )
        session.add(evidence)
        session.flush()

        if vresult.passed is True:
            return self._approve(run, project, task, evidence.id, vresult)

        # Prepara detail para diagnóstico e verificação alternativa.
        detail = dict(vresult.detail) if isinstance(vresult.detail, dict) else {}

        # Reprovado: tenta verificação alternativa antes de diagnosticar.
        alt_result = await run_alternative_verification(
            project_root=root_path,
            spec=spec or {},
            primary_verifier=vresult.verifier,
            diagnosis=diagnose_verification_failure(
                verifier=vresult.verifier,
                summary=vresult.summary,
                detail=detail,
                spec=spec or {},
            ),
            attempted=[vresult.verifier],
            tool_args=tool_args,
            approved=approved,
        )

        if alt_result is not None and alt_result.passed is True:
            # Verificação alternativa passou: grava evidência e aprova.
            alt_attempt = self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.VERIFICATION,
                provider=alt_result.verifier,
                request=spec or {},
                response={"passed": alt_result.passed, "summary": alt_result.summary},
                success=True,
                project_id=project.id,
            )
            alt_evidence = EvidenceModel(
                task_id=task.id,
                attempt_id=alt_attempt.id,
                verifier=alt_result.verifier,
                passed=True,
                summary=alt_result.summary,
                detail_json={
                    "state": "validated",
                    "criteria": self._criteria_of(task),
                    "command": {k: v for k, v in (spec or {}).items() if k != "implicit"},
                    "exit_code": (alt_result.detail or {}).get("exit_code"),
                    "alternative": True,
                    "primary_verifier": vresult.verifier,
                },
            )
            session.add(alt_evidence)
            session.flush()
            return self._approve(run, project, task, alt_evidence.id, alt_result)

        # Reprovado: diagnostica e planeja recuperação dentro do orçamento.
        output = f"{detail.get('stdout') or ''}\n{detail.get('stderr') or detail.get('error') or ''}"
        self._classify(vresult.passed, vresult.summary, output)
        diagnosis = diagnose_verification_failure(
            verifier=vresult.verifier,
            summary=vresult.summary,
            detail=detail,
            spec=spec or {},
        )
        recoveries = int(meta.get("verification_recoveries") or 0)
        signature = recovery_signature(diagnosis, detail)
        previous = str(meta.get("verification_recovery_signature") or "")

        plan = plan_recovery(
            diagnosis,
            attempt_count=recoveries,
            max_recoveries=self._executor.runtime.settings.verification_max_recoveries,
        )
        plan["signature"] = signature
        plan["recoveries"] = recoveries

        # Mesma causa de reprovação voltou: não consome o orçamento de recuperação como se
        # fosse um problema diferente; para o diagnóstico e muda a abordagem.
        if previous and previous == signature and plan.get("retry"):
            plan = {
                **plan,
                "action": "block",
                "retry": False,
                "guidance": (
                    "a mesma causa de reprovação voltou; troque a abordagem da etapa, "
                    "em vez de repetir a mesma recuperação"
                ),
            }

        # Persiste estado de recuperação.
        task.metadata_json = {
            **meta,
            "verification_recoveries": recoveries + 1,
            "verification_recovery_signature": signature,
            "verification_recovery": plan,
        }
        session.flush()

        from agent.observability import emit

        emit(
            "verification.recovery_planned",
            {"cause": plan.get("cause"), "action": plan.get("action"), "retry": plan.get("retry", False)},
            task_id=task.id,
            commit=True,
        )

        # Atualiza o estágio: executado, mas não validado.
        stage = VerificationStage.EXECUTED
        blocked = False

        if not plan.get("retry"):
            blocked = True
            self._tasks.update_status(
                task.id,
                self._blocked_status(plan.get("action"), diagnosis, vresult.summary),
            )
        else:
            self._tasks.update_status(
                task.id,
                self._retry_status(diagnosis, vresult.summary),
            )

        return GateResult(
            task_id=task.id,
            stage=stage,
            passed=False,
            verifier=vresult.verifier,
            summary=vresult.summary,
            diagnosis=diagnosis,
            recovery=plan,
            blocked=blocked,
            evidence_id=evidence.id,
        )

    # -- estágios internos -------------------------------------------------

    def _approve(
        self,
        _run: ExecutionRunModel,
        _project: ProjectModel,
        task: TaskModel,
        evidence_id: UUID,
        vresult: VerificationResult | AlternativeVerification,
    ) -> GateResult:
        """Avança a tarefa pelos estágios de verificação após aprovação independente.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa aprovada.
            evidence_id: identificador da evidência da verificação aprovada.
            vresult: resultado do verificador.

        Returns:
            O `GateResult` com o estágio atingido.
        """
        session = self._session
        task.consolidated_result_json = {
            "verified": True,
            "summary": vresult.summary,
        }

        # Estágio 1: validado — a verificação independente aprovou.
        current_status = TaskStatus(task.status)
        if current_status != TaskStatus.VERIFYING:
            self._tasks.update_status(
                task.id,
                self._status_for(VerificationStage.VALIDATED, "verificação independente aprovada"),
            )

        # Estágio 2: requisito satisfeito — o critério de aceite da tarefa foi coberto.
        criteria = self._criteria_of(task)
        all_requirements_met = bool(criteria.get("requirements")) and not criteria.get("partial")
        if all_requirements_met:
            current_status = TaskStatus(task.status)
            if current_status != TaskStatus.VERIFYING:
                self._tasks.update_status(
                    task.id,
                    self._status_for(VerificationStage.REQUIREMENT_SATISFIED, "requisitos satisfeitos"),
                )

        # Estágio 3: concluído — só quando não há filhos pendentes.
        from agent.orchestrator.consolidation import children_of, settled

        kids = children_of(session, task.id)
        if kids and not all(settled(k) for k in kids):
            # Há etapas filhas pendentes: a tarefa pai não pode concluir ainda.
            return GateResult(
                task_id=task.id,
                stage=VerificationStage.REQUIREMENT_SATISFIED,
                passed=True,
                verifier=vresult.verifier,
                summary=vresult.summary,
                evidence_id=evidence_id,
            )

        self._tasks.update_status(
            task.id,
            self._status_for(VerificationStage.COMPLETED, "tarefa concluída com verificação independente"),
        )
        if task.parent_id:
            parent = self._tasks.get_task(task.parent_id)
            if parent:
                kids = children_of(session, parent.id)
                if kids and all(settled(k) for k in kids):
                    from agent.orchestrator.consolidation import consolidate_parent

                    consolidate_parent(session, parent.id)

        return GateResult(
            task_id=task.id,
            stage=VerificationStage.COMPLETED,
            passed=True,
            verifier=vresult.verifier,
            summary=vresult.summary,
            evidence_id=evidence_id,
        )

    # -- classificações e status ---------------------------------------------

    def _classify(self, passed: bool | None, summary: str, output: str) -> Failure | None:
        """Classifica uma reprovação de verificação (reaproveita a taxonomia do executor)."""
        from agent.domain.failures import classify_verification

        return classify_verification(passed, summary, output)

    def _criteria_of(self, task: TaskModel) -> dict[str, Any]:
        from agent.orchestrator.requirements import effective_covers

        covers = effective_covers(session=self._session, task=task)
        return {
            "requirements": [c["req"] for c in covers],
            "partial": [c["req"] for c in covers if c.get("partial")],
            "acceptance": task.acceptance_criteria or "",
        }

    def _status_for(self, stage: VerificationStage, reason: str) -> TaskStatus:
        """Mapea o estágio de verificação para o status de tarefa persistido."""
        mapping = {
            VerificationStage.EXECUTED: TaskStatus.RUNNING,
            VerificationStage.VALIDATED: TaskStatus.VERIFYING,
            VerificationStage.REQUIREMENT_SATISFIED: TaskStatus.VERIFYING,
            VerificationStage.COMPLETED: TaskStatus.COMPLETED,
        }
        return TaskStatusUpdate(status=mapping[stage], reason=reason)

    def _retry_status(self, diagnosis: RecoveryDiagnosis, summary: str) -> TaskStatus:
        """Status da tarefa quando nova tentativa é permitida."""
        return TaskStatusUpdate(
            status=TaskStatus.RETRY_PENDING,
            reason=f"verificação reprovou ({diagnosis.cause}): {summary[:200]}",
        )

    def _blocked_status(
        self,
        action: str,
        diagnosis: RecoveryDiagnosis | None,
        summary: str,
    ) -> TaskStatus:
        """Status da tarefa quando bloqueada sem nova tentativa."""
        if action == "manual_review":
            reason = f"verificação exige intervenção: {(diagnosis.guidance if diagnosis else summary)[:200]}"
        else:
            reason = f"verificação bloqueada: {summary[:200]}"
        return TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=reason)


GateResult.model_rebuild()
