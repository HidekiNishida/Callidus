"""
Arquivo: src/agent/memory/state.py
Nome: state.py
Propósito: estado estruturado e consultável de uma tarefa, fora da janela do modelo.
Responsabilidade: camada de aplicação — visão consolidada de objetivo, requisitos, restrições,
premissas, critérios de aceite, dependências, operações, arquivos, decisões, evidências, alterações,
testes, pendências, orçamento, tentativas e resultado da verificação de uma tarefa.
Componentes: TaskState, OperationState, TaskStateService.
Dependências: agent.domain.enums, agent.domain.schemas, agent.persistence.models, sqlalchemy, uuid, datetime.
Observações: não cria novas tabelas; lê de TaskModel, TaskContractModel, TaskDependencyModel,
EvidenceModel, OperationAttemptModel e MemoryRecordModel. É a fonte de retomada sem reconstruir
todo o histórico.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from agent.domain.enums import TaskKind, TaskStatus
from agent.memory.operational import render_for_prompt
from agent.persistence.models import (
    EvidenceModel,
    OperationAttemptModel,
    TaskContractModel,
    TaskDependencyModel,
    TaskModel,
)


class OperationState(BaseModel):
    """Estado de uma operação (subtarefa) dentro de uma tarefa.

    Atributos:
        task_id: identificador da subtarefa.
        title: título da etapa.
        objective: objetivo da etapa.
        status: estado atual da etapa.
        kind: tipo da etapa.
        attempts: tentativas já feitas.
        verification: resultado da verificação (passed, summary, verifier).
        result: resultado consolidado da etapa.
        files: arquivos relacionados à etapa.
        depends_on: tarefas das quais esta depende.
        blocked_reason: motivo do bloqueio, quando houver.
    """

    task_id: UUID
    title: str
    objective: str
    status: str
    kind: str = TaskKind.OPERATION.value
    attempts: int = 0
    verification: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    files: list[str] = Field(default_factory=list)
    depends_on: list[UUID] = Field(default_factory=list)
    blocked_reason: str | None = None


class TaskState(BaseModel):
    """Estado estruturado e consultável de uma tarefa.

    Consolida, sem depender do histórico de conversa do LLM, tudo o que é preciso para
    retomar, delegar a outra subtarefa ou montar o contexto da próxima inferência.

    Atributos:
        task_id: identificador da tarefa.
        project_id: projeto dono.
        parent_id: tarefa-pai (None para raiz).
        title: título da tarefa.
        objective: objetivo da tarefa.
        kind: tipo da tarefa.
        status: estado atual.
        requirements: requisitos originais.
        constraints: restrições de execução.
        assumptions: premissas registradas.
        acceptance_criteria: critérios de aceite.
        decisions: decisões tomadas (texto curto).
        evidence: evidências coletadas (resumo + ref).
        changes: alterações realizadas (arquivo + resultado).
        tests: testes executados (veredito + arquivo).
        pending: o que ainda falta concluir.
        operations: estado de cada suboperação.
        dependencies: IDs de tarefas das quais depende.
        dependents: IDs de tarefas que dependem desta.
        files: arquivos relacionados.
        budget: orçamento de execução (tentativas, tokens, tempo).
        attempt_history: histórico de tentativas com causa e detalhe.
        verification_result: resultado da verificação da tarefa.
        last_error: último erro registrado.
        updated_at: instante da última atualização.
    """

    task_id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    title: str
    objective: str
    kind: str = TaskKind.OPERATION.value
    status: str = TaskStatus.PENDING.value
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    changes: list[dict[str, Any]] = Field(default_factory=list)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    operations: list[OperationState] = Field(default_factory=list)
    dependencies: list[UUID] = Field(default_factory=list)
    dependents: list[UUID] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    verification_result: dict[str, Any] | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskStateService:
    """Serviço de consulta de estado estruturado de tarefas.

    Lê de várias tabelas e devolve um `TaskState` consolidado, sem acionar o modelo.
    Todas as operações são leituras (não persistem nada).

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
    """

    def __init__(self, session: Any) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
        """
        self._session = session

    def get_task_state(self, task_id: UUID) -> TaskState | None:
        """Devolve o estado estruturado e consultável de uma tarefa.

        Args:
            task_id: identificador da tarefa.

        Returns:
            O `TaskState` consolidado, ou `None` quando a tarefa não existe.
        """
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return None

        meta = task.metadata_json or {}
        result = task.consolidated_result_json or {}

        contract = self._session.get(TaskContractModel, task_id)
        contract_json: dict[str, Any] = {}
        if contract is not None:
            contract_json = {
                "inputs": contract.inputs_json,
                "outputs": contract.outputs_json,
                "invariants": contract.invariants_json,
                "acceptance": contract.acceptance_json,
            }

        deps = list(
            self._session.scalars(
                select(TaskDependencyModel.depends_on_task_id).where(TaskDependencyModel.task_id == task_id)
            )
        )
        dependents = list(
            self._session.scalars(
                select(TaskDependencyModel.task_id).where(TaskDependencyModel.depends_on_task_id == task_id)
            )
        )

        children = self._session.scalars(select(TaskModel).where(TaskModel.parent_id == task_id)).all()

        evidence_rows = self._session.scalars(select(EvidenceModel).where(EvidenceModel.task_id == task_id)).all()
        evidence = [
            {
                "verifier": e.verifier,
                "passed": e.passed,
                "summary": e.summary,
                "detail": e.detail_json,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evidence_rows
        ]

        attempts_rows = self._session.scalars(
            select(OperationAttemptModel).where(OperationAttemptModel.task_id == task_id)
        ).all()
        attempt_history = [
            {
                "kind": a.kind,
                "provider": a.provider,
                "success": a.success,
                "error_message": a.error_message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "failure": (
                    {
                        "category": (a.response_json or {}).get("failure", {}).get("category"),
                        "cause": (a.response_json or {}).get("failure", {}).get("cause"),
                        "detail": a.error_message,
                    }
                    if a.error_message
                    else None
                ),
            }
            for a in attempts_rows
        ]

        operations: list[OperationState] = []
        pending_under: list[str] = []
        for child in children:
            child_meta = child.metadata_json or {}
            child_result = child.consolidated_result_json or {}
            list(child_meta.get("failures") or [])
            child_verification: dict[str, Any] | None = None
            if child_result.get("verified") is not None:
                child_verification = {
                    "passed": child_result.get("verified"),
                    "summary": child_result.get("summary"),
                }
            elif evidence_rows:
                last_evidence = evidence_rows[-1]
                child_verification = {
                    "passed": last_evidence.passed,
                    "summary": last_evidence.summary,
                }

            op_files: list[str] = []
            inspection = child_meta.get("inspection") if isinstance(child_meta.get("inspection"), list) else []
            op_files.extend(
                [str(item.get("path")) for item in inspection if isinstance(item, dict) and item.get("path")]
            )

            child_deps = list(
                self._session.scalars(
                    select(TaskDependencyModel.depends_on_task_id).where(TaskDependencyModel.task_id == child.id)
                )
            )

            op = OperationState(
                task_id=child.id,
                title=child.title,
                objective=child.objective,
                status=child.status,
                kind=child.kind,
                attempts=child_meta.get("attempts", 0),
                verification=child_verification,
                result=child_result,
                files=op_files,
                depends_on=child_deps,
                blocked_reason=child_meta.get("blocked_reason"),
            )
            operations.append(op)

            if TaskStatus(child.status) != TaskStatus.COMPLETED:
                pending_under.append(child.title)

        return TaskState(
            task_id=task.id,
            project_id=task.project_id,
            parent_id=task.parent_id,
            title=task.title,
            objective=task.objective,
            kind=task.kind,
            status=task.status,
            requirements=self._extract_requirements(contract_json, meta),
            constraints=self._extract_constraints(meta),
            assumptions=self._extract_assumptions(meta, contract_json),
            acceptance_criteria=self._extract_acceptance(contract_json, task),
            decisions=self._extract_decisions(meta),
            evidence=evidence,
            changes=self._extract_changes(result),
            tests=self._extract_tests(evidence),
            pending=pending_under,
            operations=operations,
            dependencies=deps,
            dependents=dependents,
            files=self._extract_files(meta, contract_json),
            budget=self._extract_budget(meta, result),
            attempt_history=attempt_history,
            verification_result=result.get("verification") if isinstance(result.get("verification"), dict) else None,
            last_error=self._extract_last_error(meta),
            updated_at=task.updated_at,
        )

    def get_operational_summary(self, task_id: UUID) -> str:
        """Devolve o resumo operacional (nível 1) de uma tarefa, pronto para o prompt.

        Args:
            task_id: identificador da tarefa.

        Returns:
            O texto do nível 1, ou um resumo montado na hora quando não há registro.
        """
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return ""
        return render_for_prompt(self._session, task)

    # -- internos de extração -------------------------------------------------

    def _extract_requirements(self, contract_json: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
        acceptance = contract_json.get("acceptance") or {}
        if isinstance(acceptance, dict) and acceptance.get("requirements"):
            return acceptance["requirements"]
        return meta.get("requirements", [])

    def _extract_constraints(self, meta: dict[str, Any]) -> dict[str, Any]:
        return meta.get("constraints", {})

    def _extract_assumptions(self, meta: dict[str, Any], contract_json: dict[str, Any]) -> list[str]:
        quality = contract_json.get("quality") if isinstance(contract_json.get("quality"), dict) else None
        assumptions: list[str] = []
        if isinstance(quality, dict):
            assumptions.extend(
                [
                    str(item["text"])
                    for item in quality.get("premises", []) or []
                    if isinstance(item, dict) and item.get("text")
                ]
            )
        assumptions.extend(meta.get("assumptions", []))
        return assumptions

    def _extract_acceptance(self, contract_json: dict[str, Any], task: TaskModel) -> list[str]:
        acceptance = contract_json.get("acceptance") if isinstance(contract_json.get("acceptance"), dict) else None
        if acceptance and acceptance.get("criteria"):
            return acceptance["criteria"]
        if task.acceptance_criteria:
            return [task.acceptance_criteria]
        return []

    def _extract_decisions(self, meta: dict[str, Any]) -> list[str]:
        approach = meta.get("approach")
        decisions: list[str] = []
        if isinstance(approach, dict) and approach.get("decision"):
            decisions.append(str(approach["decision"]))
        if isinstance(approach, str) and approach.strip():
            decisions.append(approach.strip())
        disposition = meta.get("disposition")
        if isinstance(disposition, dict) and disposition.get("reason"):
            decisions.append(str(disposition["reason"]))
        return decisions

    def _extract_changes(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        if isinstance(result, dict):
            write = result.get("write")
            if isinstance(write, dict) and write.get("path"):
                changes.append(
                    {
                        "path": write.get("path"),
                        "tool": result.get("tool"),
                        "success": write.get("success"),
                        "result": write,
                    }
                )
            mcp = result.get("mcp")
            if isinstance(mcp, dict) and mcp.get("result"):
                changes.append({"mcp": mcp.get("mcp_tool"), "result": mcp.get("result")})
        return changes

    def _extract_tests(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "verifier": ev.get("verifier"),
                "passed": ev.get("passed"),
                "summary": ev.get("summary"),
            }
            for ev in evidence
            if ev.get("verifier") in {"pytest", "script", "command", "run_command", "run_script", "static_analysis"}
        ]

    def _extract_files(self, meta: dict[str, Any], contract_json: dict[str, Any]) -> list[str]:
        files: list[str] = []
        refs = contract_json.get("outputs") if isinstance(contract_json.get("outputs"), dict) else None
        if isinstance(refs, dict) and refs.get("files"):
            files.extend(str(x) for x in refs["files"])
        inspection = meta.get("inspection") if isinstance(meta.get("inspection"), list) else []
        for item in inspection:
            if isinstance(item, dict) and item.get("path"):
                p = str(item["path"])
                if p not in files:
                    files.append(p)
        return files

    def _extract_budget(self, meta: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {
            "max_attempts": meta.get("max_attempts", 8),
            "depth": meta.get("depth", 0),
            "max_depth": meta.get("max_depth", 16),
            "output_budget": meta.get("output_budget"),
            "context_budget": meta.get("context_budget"),
            "attempts_used": len(meta.get("failures") or []),
            "result_budget": result.get("budget") if isinstance(result, dict) else None,
        }

    def _extract_last_error(self, meta: dict[str, Any]) -> str | None:
        failures = meta.get("failures") or []
        if not failures:
            return None
        last = failures[-1]
        if isinstance(last, dict):
            return str(last.get("detail") or last.get("cause") or "")
        return str(last)


TaskState.model_rebuild()
