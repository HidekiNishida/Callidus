"""
Arquivo: src/agent/orchestrator/runner.py
Nome: runner.py
Propósito: coordenar o ciclo de execução de um run — planejar, executar, verificar, consolidar.
Responsabilidade: camada de aplicação — orquestração do ciclo; delega a execução de uma tarefa.
Componentes: RunOrchestrator (step, planejamento, estagnação, pausa, retomada), helpers de fluxo.
Dependências: agent.services.task_service, agent.services.attempt_service, agent.orchestrator.execution, agent.persistence.models.
Observações: o SQLite é a fonte da verdade; a verificação é independente de quem executa.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.agent_enums import ExecutionStatus
from agent.domain.enums import MemoryKind, RunStatus, TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
)
from agent.domain.schemas import MemoryCreate, TaskStatusUpdate
from agent.i18n.locale import detect_language
from agent.observability import emit, get_bus, observe, set_task
from agent.orchestrator.approach import approach_of, approach_signature
from agent.orchestrator.atomizer import should_decompose_further
from agent.orchestrator.consolidation import (
    children_of,
    pending_reason,
    settled,
    verification_evidence_ok,
)
from agent.orchestrator.decomposition import (
    apply_decomposition,
    executable_leaf,
    plan_copies_siblings,
    resolve_decomposition_plan,
    seal_repeated_steps,
)
from agent.orchestrator.execution import (
    ExecutionRuntime,
    TaskExecutor,
    apply_provider_usage,
    note_thought,
    profile_from_config,
    remember_failure,
    select_provider,
    work_root,
)
from agent.orchestrator.global_verify import (
    correct_requirement_gaps,
    ensure_global_verification_task,
    evaluate_global_acceptance,
    reopen_verification_gaps,
    requirements_report,
)
from agent.orchestrator.plan_validation import (
    PlanValidation,
    active_children,
    plan_fingerprint,
    sanitize_spec,
    summarize,
    validate_and_repair,
)
from agent.orchestrator.planner import ensure_canonical_memory_for_objective
from agent.orchestrator.progress import made_progress, progress_state
from agent.orchestrator.replan import replan_decision, replan_under
from agent.orchestrator.requirements import (
    effective_covers,
    ensure_requirements,
    root_of,
)
from agent.orchestrator.stagnation import (
    LIMIT_LABELS,
    diagnose,
    limit_reached,
    limits_for,
    next_action_for_limit,
    problem_attempts,
)
from agent.persistence.models import (
    EventLogModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.providers.base import LLMProvider, ModelProfile
from agent.services.agent_service import AgentService
from agent.services.attempt_service import AttemptService
from agent.services.contract_service import ContractService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.registry import build_default_registry
from agent.verification.fingerprint import workspace_state


def _select_provider(settings: Settings, run_config: dict) -> LLMProvider:
    """Provedor do run — a escolha vive em `agent.orchestrator.execution.providers`.

    O nome permanece neste módulo porque é aqui que consumidores e testes a injetam
    (monkeypatch): trocar a implementação não pode quebrar quem injeta o provedor.

    Args:
        settings: configuração do processo.
        run_config: configuração do run (`provider`, `mock_keyword_map`).

    Returns:
        A instância do provedor escolhido.

    Raises:
        ProviderConfigError: quando o provedor pedido não existe e não há fallback autorizado.
    """
    return select_provider(settings, run_config)


def _profile_from_config(run_config: dict, settings: Settings, provider: LLMProvider | None = None) -> ModelProfile:
    """Perfil do modelo para o run (limites de contexto e geração).

    Args:
        run_config: configuração do run.
        settings: configuração do processo.
        provider: provedor escolhido, quando já conhecido.

    Returns:
        O perfil do modelo a aplicar nas chamadas.
    """
    return profile_from_config(run_config, settings, provider)


class RunBlockedError(RuntimeError):
    """Erro de execução que impede a run de continuar.

    Observações:
        Distingue um bloqueio de negócio de uma falha inesperada, para que o chamador saiba que é preciso ação de fora.
    """
    pass


_ACTION_KEYS = ("mcp_tool", "final_answer", "model_operation", "tool", "verification")


class RunOrchestrator:
    """Orquestrador de uma execução: planeja, executa, verifica, consolida e fecha.

    Observações:
        Todo o estado do ciclo vive no banco; a verificação é independente de quem executa o passo.
    """
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        """Prepara o orquestrador sobre a sessão do banco.

        Args:
            session: sessão usada em todas as operações do ciclo.
            settings: configurações do processo; quando ausentes, usa as configurações padrão.
        """
        self._session = session
        self._settings = settings or Settings()
        self._tasks = TaskService(session)
        self._attempts = AttemptService(session, max_attempts=self._settings.max_attempts_per_task)
        self._tools = build_default_registry()
        self._runtime = ExecutionRuntime(
            session=session,
            settings=self._settings,
            tasks=self._tasks,
            attempts=self._attempts,
            tools=self._tools,
            # A política de provedor passa pela função deste módulo: quem injeta um
            # provedor por monkeypatch continua injetando no mesmo lugar.
            provider_factory=lambda settings, config: _select_provider(settings, config),
        )
        self._executor = TaskExecutor(self._runtime)

    def _run_config(self, run: ExecutionRunModel) -> dict:
        """Devolve a configuração gravada do run.

        Args:
            run: registro do run.

        Returns:
            O dicionário de configuração do run, ou um dicionário vazio quando o run não tem configuração.
        """
        return run.config_json or {}

    def _promote_ready_or_block(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Libera a etapa para execução, ou a bloqueia quando o contrato obrigatório falta.

        Args:
            task_id: identificador da etapa.

        Returns:
            O bloqueio com o motivo quando o contrato impede a execução, ou `None` quando a etapa foi liberada.
        """
        ok, errs = ContractService(self._session).validate_for_run(task_id)
        if not ok:
            self._tasks.update_status(
                task_id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="; ".join(errs)),
            )
            return {"action": "blocked_contract", "task_id": str(task_id), "errors": errs}
        self._tasks.update_status(task_id, TaskStatusUpdate(status=TaskStatus.READY))
        return None

    def _same_title_above(self, task: TaskModel) -> bool:
        """Diz se a etapa repete o título ou o objetivo de alguma etapa acima na árvore.

        Args:
            task: etapa avaliada.

        Returns:
            Verdadeiro quando existe um ancestral com o mesmo título ou o mesmo objetivo.

        Observações:
            A varredura é protegida contra ciclos de parentagem.
        """
        title = task.title.strip().casefold()
        objective = " ".join((task.objective or "").split()).casefold()
        parent_id = task.parent_id
        seen: set[uuid.UUID] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = self._session.get(TaskModel, parent_id)
            if parent is None:
                return False
            if parent.title.strip().casefold() == title:
                return True
            if objective and " ".join((parent.objective or "").split()).casefold() == objective:
                return True
            parent_id = parent.parent_id
        return False

    def _validate_plan(
        self,
        run: ExecutionRunModel,
        parent: TaskModel,
        config: dict[str, Any],
        work_root: str,
        spec_issues: list | None = None,
    ) -> PlanValidation:
        """Valida o plano das filhas de uma tarefa e aplica as correções seguras.

        Args:
            run: run dona do plano.
            parent: tarefa cujo plano é validado.
            config: configuração do run.
            work_root: pasta de trabalho usada para conferir ferramentas e verificações.
            spec_issues: problemas já detectados na especificação do plano.

        Returns:
            O resultado da validação, com o veredito e as correções aplicadas.
        """
        return validate_and_repair(
            self._session,
            parent,
            project_root=work_root,
            run_config=config,
            max_tasks=self._settings.max_tasks_per_run,
            run_id=run.id,
            extra_issues=spec_issues,
        )

    def _block_invalid_plan(self, parent: TaskModel, validation: PlanValidation) -> dict[str, Any]:
        """Plano que não pôde ser corrigido: nada dele executa; o pai fica BLOCKED (recuperável) com o motivo,
        e a falha diz ao replanejamento do nível de cima o que fazer."""
        codes = {i.code for i in validation.issues}
        if "all_blocked" in codes:
            category = FailureCategory.EXTERNAL_UNAVAILABLE
        elif "budget_exceeded" in codes:
            category = FailureCategory.OPERATIONAL_LIMIT
        else:
            category = FailureCategory.CHANGE_STRATEGY
        reason = summarize(validation)
        noted = self._remember_failure(parent, Failure(category, FailureCause.INVALID_PLAN, reason))
        for status in self._TO_BLOCKED.get(TaskStatus(parent.status), ()):
            self._tasks.update_status(parent.id, TaskStatusUpdate(status=status, reason=reason))
        return {
            "action": "plan_invalid",
            "task_id": str(parent.id),
            "plan": validation.verdict.value,
            "failure": noted,
            "thought": reason,
        }

    def _revalidate_plan(
        self, run: ExecutionRunModel, task: TaskModel, config: dict[str, Any], work_root: str
    ) -> dict[str, Any] | None:
        """Antes de executar uma etapa, confere se o plano do pai mudou desde a última validação
        (replanejamento, dependência nova, cobertura alterada); se mudou, valida de novo."""
        if task.parent_id is None:
            return None
        parent = self._tasks.get_task(task.parent_id)
        previous = (parent.metadata_json or {}).get("plan_validation")
        if not previous or previous.get("fingerprint") == plan_fingerprint(self._session, parent.id):
            return None
        validation = self._validate_plan(run, parent, config, work_root)
        if not validation.runnable:
            return self._block_invalid_plan(parent, validation)
        return {
            "action": "plan_revalidated",
            "task_id": str(parent.id),
            "plan": validation.verdict.value,
            "fixes": validation.fixes,
        }

    def _task_requirements(self, task: TaskModel) -> list[dict]:
        """Requisitos que esta etapa precisa atender (os da raiz filtrados pela cobertura herdada)."""
        reqs = ensure_requirements(self._session, root_of(self._session, task))
        covered = {c["req"]: c for c in effective_covers(self._session, task, reqs)}
        return [
            {**r, "partial": covered[r["id"]]["partial"], "part": covered[r["id"]]["part"]}
            for r in reqs
            if r["id"] in covered and r["applicability"] == "obrigatório"
        ]

    def _conversation_objectives(self, task: TaskModel, limit: int = 5) -> list[str]:
        """Pedidos anteriores da mesma conversa, do mais recente ao mais antigo.

        Args:
            task: etapa em curso.
            limit: número máximo de pedidos devolvidos.

        Returns:
            A lista de objetivos anteriores.

        Observações:
            É o que permite reconhecer uma confirmação ("sim, pode ativar") como
            resposta a um pedido de automação, e não como um pedido novo.
        """
        conversation_id = getattr(task, "conversation_id", None)
        if not conversation_id:
            return []
        rows = list(
            self._session.scalars(
                select(TaskModel)
                .where(TaskModel.conversation_id == conversation_id)
                .order_by(TaskModel.created_at.desc())
                .limit(limit + 1)
            ).all()
        )
        objectives: list[str] = []
        for row in rows:
            if str(row.id) == str(task.id):
                continue
            if row.objective:
                objectives.append(row.objective)
            if len(objectives) >= limit:
                break
        return objectives

    def _recursion_guard(self, run: ExecutionRunModel, task: TaskModel) -> str | None:
        """Proteção contra recursão, separada da decisão de dividir: plano que repete um ancestral,
        árvore mais funda que `max_tree_depth` ou run com mais de `max_tasks_per_run` tarefas."""
        if self._same_title_above(task):
            return "repete o título ou o objetivo de uma etapa acima"
        if self._depth(task) >= self._settings.max_tree_depth:
            return f"profundidade de proteção ({self._settings.max_tree_depth}) atingida"
        tasks = list(self._session.scalars(select(TaskModel).where(TaskModel.project_id == task.project_id)).all())
        if len(self._subtree_ids(run.root_task_id, tasks)) >= self._settings.max_tasks_per_run:
            return f"limite de {self._settings.max_tasks_per_run} tarefas no run atingido"
        return None

    def _depth(self, task: TaskModel) -> int:
        """Calcula a profundidade da etapa na árvore de tarefas.

        Args:
            task: etapa avaliada.

        Returns:
            O número de ancestrais da etapa.

        Observações:
            A varredura é protegida contra ciclos de parentagem.
        """
        depth = 0
        parent_id = task.parent_id
        seen: set[uuid.UUID] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = self._session.get(TaskModel, parent_id)
            if parent is None:
                return depth
            depth += 1
            parent_id = parent.parent_id
        return depth

    def _propagate_strategy(self, parent: TaskModel, plan: Any) -> None:
        """Repassa a estratégia profissional do pai para os filhos recém-criados.

        Cada filho herda a especialidade líder (para o prompt) e recebe `atomize=True`
        quando a estratégia é complexa — é o gatilho da decomposição recursiva da etapa
        interna (diagnóstico → correção → verificação).
        """
        from agent.orchestrator.strategy import ProfessionalStrategy

        meta = parent.metadata_json or {}
        strategy = ProfessionalStrategy.from_dict(meta.get("professional_strategy"))
        if strategy is None:
            return
        for child in children_of(self._session, parent.id):
            child_meta = dict(child.metadata_json or {})
            child_meta.setdefault("lead_specialty", strategy.lead_specialty)
            for flag in ("read_only", "protect_tests"):
                if strategy.metadata.get(flag):
                    # Restrições do pedido viram permissão, não só instrução, e descem com a
                    # decomposição.
                    child_meta.setdefault(flag, True)
            if strategy.needs_atomization and not child_meta.get("tool") and not child_meta.get("verification"):
                child_meta.setdefault("atomize", True)
            if strategy.extracted_requirements:
                child_meta.setdefault("strategy_requirements", strategy.extracted_requirements[:5])
            child.metadata_json = child_meta

    def _run_as_leaf(self, run: ExecutionRunModel, task: TaskModel, *, note: str) -> dict[str, Any]:
        """Executa a etapa como folha, sem decompô-la.

        Args:
            run: run em curso.
            task: etapa que será executada como folha.
            note: explicação registrada para a interface.

        Returns:
            A ação resultante: a etapa ficou pronta, ou está esperando as dependências.
        """
        meta = dict(task.metadata_json or {})
        if not meta.get("tool") and not meta.get("verification") and not meta.get("final_answer"):
            meta["model_operation"] = True
            meta["atomic"] = True
            task.metadata_json = meta
        self._note_thought(run, task, note)
        if self._tasks.dependencies_satisfied(task.id):
            blocked = self._promote_ready_or_block(task.id)
            if blocked:
                return blocked
            return {"action": "operation_ready", "task_id": str(task.id), "thought": note}
        return {"action": "operation_wait_deps", "task_id": str(task.id)}

    async def step(self, run_id: uuid.UUID) -> dict[str, Any]:
        """Executa um passo do ciclo da run.

        Args:
            run_id: identificador da run.

        Returns:
            A ação realizada no passo, com a tarefa afetada.

        Raises:
                LookupError: quando a run não existe.

        Observações:
            O passo é o mesmo executado pelo worker autônomo: quem executa não muda o que é verificado.
        """
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        bus = get_bus()
        bus.step_started(str(run.id))
        try:
            with observe(self._session, run_id=run.id, project_id=run.project_id):
                out = await self._step_body(run_id)
                out = self._check_stagnation(run_id, out) or out
                self._record_action(run_id, out)
        finally:
            bus.step_finished(str(run.id))
        return out

    def _check_stagnation(self, run_id: uuid.UUID, out: dict[str, Any]) -> dict[str, Any] | None:
        """Resposta à ausência de progresso de uma etapa: o mesmo problema, no mesmo objetivo, repetido
        `attempts_per_strategy` vezes sem mudança material interrompe a repetição.

        A contagem vive na **raiz** do objetivo, não na etapa: o replanejamento cria etapas
        novas, e a contagem precisa sobreviver a isso — era exatamente aí que o contador
        recomeçava e a cadeia "falhou → replanejou → falhou igual" podia continuar.

        Uma tentativa só continua a contagem quando nada mudou de material: a mesma operação,
        a mesma abordagem declarada e o mesmo estado do disco. Mudou qualquer um deles, é uma
        tentativa legítima (a causa foi corrigida, a abordagem mudou, o projeto avançou) e a
        contagem recomeça.

        Quando a estagnação é confirmada, grava o diagnóstico (tipo, causa provável, hipótese,
        o que será diferente, critério de sucesso e de fracasso) e a próxima ação; segue só se
        houver estratégia justificável (replanejar o pai com o diagnóstico), senão pausa o run
        com diagnóstico recuperável.
        """
        raw = out.get("task_id")
        if not out.get("failure") or not isinstance(raw, str):
            return None
        task = self._session.get(TaskModel, uuid.UUID(raw))
        if task is None or TaskStatus(task.status) != TaskStatus.RETRY_PENDING:
            return None
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            return None
        cap = limits_for(self._settings, self._run_config(run))["attempts_per_strategy"]
        cap_problem = limits_for(self._settings, self._run_config(run))["attempts_per_problem"]
        failures = list((task.metadata_json or {}).get("failures") or [])
        last = failures[-1] if failures else dict(out["failure"])
        if not last.get("signature"):
            return None
        root = self._tasks.get_task(run.root_task_id)
        project = self._session.get(ProjectModel, run.project_id)
        work_root = self._work_root(project, root) if project is not None else "."
        count, total, problem = problem_attempts(
            root,
            last,
            workspace=workspace_state(work_root),
            approach=approach_signature(task),
        )
        repeated = bool(cap) and count >= cap
        exhausted = bool(cap_problem) and total >= cap_problem
        if not (repeated or exhausted):
            return None
        diag = diagnose(last, count)
        # Corte de saída: o plano serve, faltou orçamento. Ampliar e seguir — sem replanejar e
        # sem pausar, para o run seguir sozinho.
        if last.get("cause") == FailureCause.TRUNCATED_OUTPUT.value:
            budget = self._widen_output_budget(task)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
            self._note_thought(
                run,
                task,
                f"«{task.title}» esbarrou no limite de resposta; ampliei para {budget} tokens e vou tentar de novo.",
            )
            self._session.add(
                EventLogModel(
                    project_id=run.project_id,
                    run_id=run.id,
                    task_id=task.id,
                    event_type="run.budget_widened",
                    payload_json={
                        "task": task.title,
                        "output_budget": budget,
                        "count": count,
                        "cause": last.get("cause"),
                    },
                )
            )
            return {
                "action": "budget_widened",
                "task_id": raw,
                "output_budget": budget,
                "failure": last,
            }
        approach = approach_of(task)
        record = {
            "previous_status": task.status,
            "signature": last.get("signature"),
            "strategy": last.get("strategy"),
            "count": count,
            "total": total,
            "repeated": repeated,
            "exhausted": exhausted,
            **diag,
            "problem": approach.get("problem") or last.get("detail"),
            "hypothesis": approach.get("hypothesis") or diag["probable_cause"],
            "next_change": approach.get("next_change") or "",
            "success_criterion": approach.get("success_criterion") or "",
            "failure_criterion": approach.get("failure_criterion") or "",
            "attempts": int(approach.get("attempts") or count),
            "changed": bool(problem.get("changed")),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        category = FailureCategory.CHANGE_STRATEGY if diag["automatic"] else FailureCategory.CONFIGURATION
        reason = f"estagnação ({diag['kind']}): {diag['probable_cause']}"
        if exhausted and not repeated:
            reason = f"problema sem solução após {total} tentativas: {diag['probable_cause']}"
        noted = self._remember_failure(task, Failure(category, FailureCause.STAGNATION, reason))
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=reason[:300]))
        parent = self._session.get(TaskModel, task.parent_id) if task.parent_id else None
        decision = None
        # O problema esgotou o orçamento: outra abordagem não resolve, e o run precisa parar.
        if diag["automatic"] and parent is not None and not exhausted:
            kids = children_of(self._session, parent.id)
            done = sum(1 for k in kids if k.status == TaskStatus.COMPLETED.value)
            decision = replan_decision(parent.metadata_json or {}, task, done)
        if decision is not None and decision.replan:
            record["next_action"] = f"replanejar «{parent.title}» para {diag['action']}"
        else:
            if exhausted:
                record["next_action"] = (
                    f"o problema já consumiu {total} tentativas, com abordagens diferentes; "
                    "revisar a causa ou aumentar `limits.attempts_per_problem`, depois retomar "
                    f"(POST /runs/{run_id}/resume)"
                )
            else:
                record["next_action"] = f"{diag['action']}; depois retomar (POST /runs/{run_id}/resume)"
            if decision is not None:
                record["replan_refused"] = decision.reason
        task.metadata_json = {**(task.metadata_json or {}), "stagnation": record}
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=task.id,
                event_type="run.stagnation",
                payload_json={"task": task.title, **record},
            )
        )
        result = {"task_id": raw, "after": out.get("action"), "failure": noted, "stagnation": record}
        if decision is not None and decision.replan:
            self._note_thought(run, task, f"«{task.title}» repete o mesmo erro. Vou {diag['action']}.")
            return {"action": "stagnation_replan", **result}
        root = self._tasks.get_task(run.root_task_id)
        limit_key = "attempts_per_problem" if exhausted else "attempts_per_strategy"
        hit = {
            "limit": limit_key,
            "label": LIMIT_LABELS[limit_key],
            "value": total if limit_key == "attempts_per_problem" else count,
            "max": cap_problem if limit_key == "attempts_per_problem" else cap,
            "task": task.title,
        }
        return {**self._pause_run(run, root, hit, record["next_action"], diagnosis=record), **result}

    def _pause_run(
        self,
        run: ExecutionRunModel,
        root: TaskModel,
        hit: dict[str, Any],
        next_action: str,
        *,
        diagnosis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Limite atingido: o run pausa (retomável) com estado, pendências, requisitos, motivo e próxima
        ação gravados na raiz e no evento `run.paused`. Nenhuma tarefa muda de estado; nada é dado como concluído."""
        from agent.orchestrator.closing import compose_incomplete_markdown

        reason = f"limite atingido: {hit['label']} ({hit['value']} de {hit['max']})"
        pending = self._pending_under(root.id)
        requirements = requirements_report(self._session, root)
        pause = {
            **hit,
            "reason": reason,
            "next_action": next_action,
            "at": datetime.now(timezone.utc).isoformat(),
            "progress": progress_state(self._session, root.id),
            "pending": pending,
            "requirements": requirements,
            **({"diagnosis": diagnosis} if diagnosis else {}),
        }
        message = compose_incomplete_markdown(
            objective=root.objective or root.title, pending=pending, reason=reason, requirements=requirements
        )
        message += f"\n\n**Próxima ação:** {next_action}"
        root.metadata_json = {**(root.metadata_json or {}), "pause": pause}
        root.consolidated_result_json = {
            **(root.consolidated_result_json or {}),
            "achieved": False,
            "paused": pause,
            "final_answer": message,
        }
        run.status = RunStatus.PAUSED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=root.id,
                event_type="run.paused",
                payload_json={"reason": reason, "limit": hit, "next_action": next_action, "pending": pending},
            )
        )
        return {"action": "run_paused", "run_id": str(run.id), "reason": reason, "next_action": next_action}

    def _record_action(self, run_id: uuid.UUID, out: dict[str, Any]) -> None:
        """Grava a ação do passo no histórico e publica o progresso quando ele muda.

        Args:
            run_id: identificador da run.
            out: ação realizada no passo.

        Observações:
            O evento `run.progress` só é emitido quando o estado de progresso muda; decompor sem avançar não é progresso.
        """
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            return
        task_id = None
        raw = out.get("task_id")
        if isinstance(raw, str):
            try:
                task_id = uuid.UUID(raw)
            except ValueError:
                task_id = None
        payload = {k: v for k, v in out.items() if k not in {"log"}}
        self._session.flush()
        payload["progress"] = progress_state(self._session, run.root_task_id)
        previous = self._session.scalars(
            select(EventLogModel.payload_json)
            .where(EventLogModel.run_id == run_id, EventLogModel.event_type == "orchestrator.action")
            .order_by(EventLogModel.created_at.desc())
            .limit(1)
        ).first()
        before = (previous or {}).get("progress")
        if before != payload["progress"]:
            emit(
                "run.progress",
                {
                    "state": payload["progress"],
                    "previous": before,
                    "made_progress": made_progress(before, payload["progress"]),
                },
                task_id=None,
            )
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run_id,
                task_id=task_id,
                event_type="orchestrator.action",
                payload_json=payload,
            )
        )

    def _note_thought(
        self, run: ExecutionRunModel, task: TaskModel | None, text: str, *, phase: str = "thinking"
    ) -> None:
        """Grava o que está acontecendo e libera o banco para a interface ler durante a inferência."""
        note_thought(self._session, run, task, text, phase=phase)

    def _remember_failure(self, task: TaskModel, failure: Failure) -> dict[str, Any]:
        """Guarda a falha na tarefa: a próxima tentativa e a política de replanejamento leem daqui."""
        return remember_failure(task, failure)

    def _widen_output_budget(self, task: TaskModel, *, factor: int = 2) -> int:
        """Aumenta o orçamento de resposta da etapa (o modelo gastou tudo e devolveu nada).

        O plano continua válido: o que falhou foi o tamanho da resposta, não a estratégia.
        """
        meta = dict(task.metadata_json or {})
        current = int(meta.get("output_budget") or 0)
        budget = min(32768, max(current, 1024) * factor)
        meta["output_budget"] = budget
        # Zera a contagem dessa assinatura: a tentativa widened conta como nova estratégia.
        history = [
            item
            for item in (meta.get("failures") or [])
            if item.get("cause") != FailureCause.TRUNCATED_OUTPUT.value
        ]
        meta["failures"] = history
        task.metadata_json = meta
        return budget

    _TO_BLOCKED: dict[TaskStatus, tuple[TaskStatus, ...]] = {
        TaskStatus.PENDING: (TaskStatus.PLANNING, TaskStatus.BLOCKED),
        TaskStatus.PLANNING: (TaskStatus.BLOCKED,),
        TaskStatus.READY: (TaskStatus.BLOCKED,),
        TaskStatus.RUNNING: (TaskStatus.BLOCKED,),
        TaskStatus.RETRY_PENDING: (TaskStatus.BLOCKED,),
        TaskStatus.VERIFYING: (TaskStatus.PLANNING, TaskStatus.BLOCKED),
        TaskStatus.COMPLETED: (TaskStatus.VERIFYING, TaskStatus.PLANNING, TaskStatus.BLOCKED),
    }

    def _pending_under(self, root_id: uuid.UUID) -> list[dict[str, Any]]:
        """Lista as etapas que ainda impedem a raiz de concluir.

        Args:
            root_id: identificador da raiz da árvore.

        Returns:
            As pendências com título, estado e o motivo de cada uma.
        """
        tasks = list(self._session.scalars(select(TaskModel)).all())
        subtree = self._subtree_ids(root_id, tasks)
        pending: list[dict[str, Any]] = []
        for t in sorted((t for t in tasks if t.id in subtree and t.id != root_id), key=lambda t: t.sort_order):
            done = TaskStatus(t.status) == TaskStatus.COMPLETED and verification_evidence_ok(self._session, t)
            if done or settled(t) or children_of(self._session, t.id):
                continue
            pending.append({"task_id": str(t.id), "title": t.title, "status": t.status, "reason": pending_reason(t)})
        return pending

    def _stall_run(self, run: ExecutionRunModel, root: TaskModel, reason: str) -> dict[str, Any]:
        """Nada pode avançar e o objetivo não foi cumprido: o run termina como falho, com o estado salvo,
        a raiz em BLOCKED (recuperável) e a explicação das pendências. Nada é dado como concluído."""
        from agent.orchestrator.closing import compose_incomplete_markdown

        pending = self._pending_under(root.id)
        tasks = list(self._session.scalars(select(TaskModel)).all())
        subtree = self._subtree_ids(root.id, tasks)
        refusals = sorted(
            {str((t.metadata_json or {}).get("replan_refused")) for t in tasks if t.id in subtree and (t.metadata_json or {}).get("replan_refused")}
        )
        if refusals:
            reason = f"{reason}; sem replanejamento: {'; '.join(refusals)}"
        for status in self._TO_BLOCKED.get(TaskStatus(root.status), ()):
            self._tasks.update_status(root.id, TaskStatusUpdate(status=status, reason=reason))
        report = dict(root.consolidated_result_json or {})
        requirements = requirements_report(self._session, root)
        report.update(achieved=False, pending=pending, stalled_reason=reason, requirements=requirements)
        report["final_answer"] = compose_incomplete_markdown(
            objective=root.objective or root.title, pending=pending, reason=reason, requirements=requirements
        )
        root.consolidated_result_json = report
        run.status = RunStatus.FAILED.value
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=root.id,
                event_type="run.failed",
                payload_json={"reason": reason, "kind": "stalled", "pending": pending, "requirements": requirements},
            )
        )
        return {"action": "run_stalled", "run_id": str(run.id), "reason": reason, "pending": pending}

    def _capture_outcome_memory(self, project: ProjectModel, root: TaskModel) -> None:
        """Guarda o resultado do trabalho como memória contextual do projeto.

        Args:
            project: projeto que recebe a memória.
            root: tarefa raiz do objetivo.

        Observações:
            A gravação é idempotente: a mesma conclusão não é gravada duas vezes.
        """
        report = root.consolidated_result_json or {}
        final = report.get("final_answer") or ""
        if not isinstance(final, str):
            final = ""
        content = f"{root.objective}\n\n{final}".strip()
        if not content:
            return
        existing = ProjectService(self._session).list_memory(project.id, MemoryKind.CONTEXTUAL)
        if any(item.task_id == root.id and item.title == "Resultado da conversa" for item in existing):
            return
        ProjectService(self._session).add_memory(
            project.id,
            MemoryCreate(
                kind=MemoryKind.CONTEXTUAL,
                title="Resultado da conversa",
                content=content,
                task_id=root.id,
                conversation_id=root.conversation_id,
                source_refs=[f"task:{root.id}"],
            ),
        )

    def _sync_agent_execution(self, task: TaskModel, run_id: uuid.UUID | None = None) -> None:
        """Alinha o estado do agente lógico com o estado da tarefa.

        Tarefa e execução são conceitos diferentes: a tarefa guarda o resultado, a
        execução guarda o que ocupa memória de inferência. Esta função apenas reflete
        a realidade — nunca inventa progresso nem apaga resultado. Falhas aqui não
        podem derrubar a execução do run.
        """
        try:
            # Savepoint: se a sincronização falhar, só ela é desfeita — o trabalho
            # da etapa (status da tarefa, resultado) permanece.
            with self._session.begin_nested():
                agents = AgentService(self._session, self._settings)
                agent = agents.agent_for_task(task.id)
                if agent is None:
                    agent = agents.ensure_agent(task.id)
                status = TaskStatus(task.status)
                execution = agents.current_execution(agent.id)
                live = {
                    ExecutionStatus.RUNNING,
                    ExecutionStatus.RESUMING,
                    ExecutionStatus.WAITING_FOR_CHILD,
                    ExecutionStatus.PENDING,
                }
                if status == TaskStatus.RUNNING:
                    if execution is None or ExecutionStatus(execution.status) not in live:
                        agents.start_execution(agent.id, task_id=task.id, run_id=run_id)
                elif status == TaskStatus.COMPLETED:
                    if execution is not None and ExecutionStatus(execution.status) in live:
                        agents.complete_execution(agent.id)
                elif status == TaskStatus.FAILED:
                    if execution is not None and ExecutionStatus(execution.status) in live:
                        agents.fail_execution(agent.id, "tarefa falhou")
        except Exception:  # noqa: BLE001 — a sincronização é observabilidade, não requisito
            pass

    async def _step_body(self, run_id: uuid.UUID) -> dict[str, Any]:
        """Corpo do passo: decide o que fazer com a próxima etapa da run.

            Args:
                run_id: identificador da run.

            Returns:
                A ação realizada no passo.

            Raises:
                LookupError: quando a run ou o projeto da run não existem.

            Observações:
                A ordem das decisões é fixa: limite de orçamento, replanejamento, escolha da próxima etapa,
                revalidação do plano e, por fim, a execução ou a verificação conforme o estado da etapa.
        """
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        if run.status in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}:
            return {"action": "run_terminal", "status": run.status}
        if run.status == RunStatus.PAUSED.value:
            return {"action": "run_paused", "run_id": str(run.id), "status": run.status}

        project = self._session.get(ProjectModel, run.project_id)
        if project is None:
            raise LookupError("project")

        config = self._run_config(run)
        root_for_locale = self._tasks.get_task(run.root_task_id)
        locale = (root_for_locale.metadata_json or {}).get("locale") or detect_language(
            root_for_locale.objective or ""
        )
        config = {**config, "locale": locale}
        provider = _select_provider(self._settings, config)

        root = self._tasks.get_task(run.root_task_id)
        hit = limit_reached(
            self._session,
            run,
            limits_for(self._settings, config),
            allowance=self._settings.resume_limit_allowance,
        )
        if hit:
            return self._pause_run(run, root, hit, next_action_for_limit(run.id, hit))
        work_root = self._work_root(project, root)
        revised = replan_under(self._session, root.id)
        if revised:
            self._note_thought(run, root, str(revised.get("thought") or "Replanejei o que ainda falta."))
            return revised
        task = self._pick_next_task(run.root_task_id)
        if task is None:
            added = ensure_global_verification_task(self._session, project.id, root)
            if added is not None:
                return {"action": "global_verification_added", "task_id": str(added.id)}
            reason = "nenhuma etapa pode avançar"
            if self._all_terminal_under(root.id) and TaskStatus(root.status) == TaskStatus.COMPLETED:
                ok, reason = evaluate_global_acceptance(self._session, root.id)
                if ok:
                    root.consolidated_result_json = {
                        **(root.consolidated_result_json or {}),
                        "requirements": requirements_report(self._session, root),
                    }
                    run.status = RunStatus.COMPLETED.value
                    self._ensure_final_message(root)
                    self._capture_outcome_memory(project, root)
                    reqs = root.consolidated_result_json["requirements"]
                    emit(
                        "run.completed",
                        {
                            "requirements": len(reqs) if isinstance(reqs, list) else None,
                            "progress": progress_state(self._session, root.id),
                        },
                        task_id=root.id,
                    )
                    return {"action": "run_completed", "run_id": str(run_id)}
                reopened = reopen_verification_gaps(self._session, root.id)
                if reopened:
                    return {"action": "global_verify_reopen", "reopened": [str(x) for x in reopened]}
                fixes = correct_requirement_gaps(self._session, root)
                if fixes:
                    self._note_thought(run, root, f"Faltou comprovar um requisito ({reason}). Vou tratar só ele.")
                    return {"action": "requirements_reopen", "created": [str(x) for x in fixes], "reason": reason}
            return self._stall_run(run, root, reason)

        set_task(task.id)
        revalidated = self._revalidate_plan(run, task, config, work_root)
        if revalidated:
            return revalidated

        self._session.add(
            EventLogModel(
                project_id=project.id,
                run_id=run_id,
                task_id=task.id,
                event_type="orchestrator.step",
                payload_json={"task": task.title, "status": task.status},
            )
        )

        status = TaskStatus(task.status)

        if status == TaskStatus.PENDING:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.PLANNING))
            if task.id == run.root_task_id:
                ensure_canonical_memory_for_objective(self._session, project.id, task)
                ensure_requirements(self._session, task)
                from agent.orchestrator.strategy import ProfessionalStrategist

                strat = ProfessionalStrategist().analyze(task.objective)
                task.metadata_json = {
                    **(task.metadata_json or {}),
                    "professional_strategy": strat.as_dict(),
                    "lead_specialty": strat.lead_specialty,
                }
                if strat.metadata.get("read_only"):
                    # A restrição fica na própria raiz: assim ela desce com a decomposição,
                    # com o replanejamento e com a decomposição adaptativa.
                    task.metadata_json = {**task.metadata_json, "read_only": True}
                if strat.metadata.get("protect_tests"):
                    task.metadata_json = {**task.metadata_json, "protect_tests": True}
                emit("strategy.formulated", strat.as_dict(), task_id=task.id, commit=True)
            return {"action": "started_planning", "task_id": str(task.id)}

        if status == TaskStatus.PLANNING:
            kids = active_children(self._session, task.id)
            meta = task.metadata_json or {}
            if not kids and meta.get("final_answer"):
                if self._tasks.dependencies_satisfied(task.id):
                    self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
                    return {"action": "operation_ready", "task_id": str(task.id)}
                return {"action": "operation_wait_deps", "task_id": str(task.id)}
            if not kids and executable_leaf(meta):
                if self._tasks.dependencies_satisfied(task.id):
                    blocked = self._promote_ready_or_block(task.id)
                    if blocked:
                        return blocked
                    return {"action": "operation_ready", "task_id": str(task.id)}
                return {"action": "operation_wait_deps", "task_id": str(task.id)}
            guard = self._recursion_guard(run, task) if not kids else None
            if guard:
                task.metadata_json = {**meta, "recursion_guard": guard}
                return self._run_as_leaf(
                    run,
                    task,
                    note=f"«{task.title}» {guard}. Vou executar esta etapa, sem dividir de novo.",
                )
            if not kids:
                attempts = self._attempts.count_attempts(task.id)
                depth = self._depth(task)
                emit("plan.started", {"title": task.title, "depth": depth})
                if meta.get("atomize") or (
                    attempts >= 2
                    and should_decompose_further(
                        objective=task.objective,
                        metadata=meta,
                        kind=task.kind,
                        attempt_count=attempts,
                        has_children=False,
                        depth=depth,
                        max_depth=self._settings.max_tree_depth,
                    )
                ):
                    from agent.orchestrator.atomizer import adaptive_decompose_operation
                    strat_meta = meta.get("professional_strategy") or {}
                    lead_spec = strat_meta.get("lead_specialty") or meta.get("lead_specialty")
                    plan = adaptive_decompose_operation(
                        task.objective,
                        metadata=meta,
                        lead_specialty=lead_spec,
                        depth=depth,
                        max_depth=self._settings.max_tree_depth,
                    )
                    source = "atomizer-adaptive"
                else:
                    self._note_thought(run, task, f"Pensando em como dividir «{task.title}».")
                    plan, source = await resolve_decomposition_plan(
                        settings=self._settings,
                        run_config=config,
                        objective=task.objective,
                        project_root=work_root,
                        provider=provider
                        if str(config.get("provider") or self._settings.default_provider) != "mock"
                        else None,
                        requirements=self._task_requirements(task),
                        previous_objectives=self._conversation_objectives(task),
                    )
                apply_provider_usage(task, provider)
                if plan is None or not plan.subtasks:
                    self._tasks.update_status(
                        task.id,
                        TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="decomposição falhou"),
                    )
                    return {"action": "blocked_decompose", "task_id": str(task.id)}
                plan = seal_repeated_steps(task.title, plan)
                sibling_titles = [item.title for item in children_of(self._session, task.parent_id)] if task.parent_id else []
                if plan_copies_siblings(sibling_titles, [item.title for item in plan.subtasks], task.title):
                    return self._run_as_leaf(
                        run,
                        task,
                        note=f"«{task.title}» repetiu o mesmo plano. Vou executar esta etapa, sem dividir de novo.",
                    )
                plan, spec_issues = sanitize_spec(plan)
                apply_decomposition(self._session, project.id, task.id, plan)
                depth = self._depth(task)
                self._propagate_strategy(task, plan)
                emit(
                    "plan.updated",
                    {
                        "source": source,
                        "tasks": [
                            {"id": str(k.id), "title": k.title, "kind": k.kind}
                            for k in children_of(self._session, task.id)
                            if k.status == TaskStatus.PENDING.value
                        ],
                    },
                )
                emit(
                    "decomposition.recursive",
                    {
                        "depth": depth,
                        "source": source,
                        "count": len(plan.subtasks),
                        "titles": [spec.title for spec in plan.subtasks],
                        "parent": task.title,
                    },
                    task_id=task.id,
                    commit=True,
                )
                validation = self._validate_plan(run, task, config, work_root, spec_issues)
                if not validation.runnable:
                    return self._block_invalid_plan(task, validation)
                titles = ", ".join(spec.title for spec in plan.subtasks[:6])
                return {
                    "action": "decomposed",
                    "task_id": str(task.id),
                    "count": len(plan.subtasks),
                    "source": source,
                    "plan": validation.verdict.value,
                    "thought": f"Vou fazer: {titles}.",
                }

            if self._tasks.dependencies_satisfied(task.id):
                blocked = self._promote_ready_or_block(task.id)
                if blocked:
                    return blocked
            return {"action": "planning_wait_children", "task_id": str(task.id)}

        promoted = self._tasks.promote_ready_if_dependencies_met(task.id)
        if promoted:
            ok, errs = ContractService(self._session).validate_for_run(task.id)
            if not ok:
                self._tasks.update_status(
                    task.id,
                    TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="; ".join(errs)),
                )
                return {"action": "blocked_contract", "task_id": str(task.id), "errors": errs}
            return {"action": "promoted_ready", "task_id": str(task.id)}

        if status == TaskStatus.READY:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
            status = TaskStatus.RUNNING

        if status == TaskStatus.RUNNING:
            result = await self._executor.execute(run, project, task, config, work_root)
            self._sync_agent_execution(task, run_id)
            return result

        if status == TaskStatus.VERIFYING:
            return await self._executor.finalize_verification(run, project, task, work_root)

        if status == TaskStatus.RETRY_PENDING:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
            return {"action": "retry_ready", "task_id": str(task.id)}

        return {"action": "noop", "task_id": str(task.id), "status": task.status}

    async def run_until_idle(self, run_id: uuid.UUID, max_steps: int = 50) -> list[dict]:
        """Avança a run em vários passos até ela parar, travar ou o orçamento de passos acabar.

            Args:
                run_id: identificador da run.
                max_steps: número máximo de passos executados.

            Returns:
                O registro das ações de cada passo.

            Observações:
                Dois passos consecutivos de espera encerram o laço: a run não está progredindo.
        """
        log: list[dict] = []
        for _ in range(max_steps):
            out = await self.step(run_id)
            log.append(out)
            if out.get("action") in {
                "run_completed",
                "run_terminal",
                "blocked_decompose",
                "blocked_loop",
                "blocked_attempts",
                "blocked_contract",
                "blocked_context",
                "run_stalled",
                "run_paused",
                "global_verify_failed",
            }:
                break
            if out.get("action") == "waiting":
                if len(log) >= 2 and log[-1] == log[-2]:
                    break
        return log

    def _pick_next_task(self, root_id: uuid.UUID) -> TaskModel | None:
        """Escolhe a etapa que o próximo passo deve tratar.

            Args:
                root_id: identificador da raiz da árvore.

            Returns:
                A etapa escolhida, ou `None` quando nenhuma etapa pode avançar.

            Observações:
                A prioridade vai do estado mais avançado ao menos avançado; uma etapa só é escolhida quando
                suas dependências estão satisfeitas e, no planejamento, quando as filhas já estão resolvidas.
        """
        stmt = select(TaskModel)
        all_tasks = list(self._session.scalars(stmt).all())
        subtree = self._subtree_ids(root_id, all_tasks)
        priority = [
            TaskStatus.RUNNING,
            TaskStatus.VERIFYING,
            TaskStatus.READY,
            TaskStatus.RETRY_PENDING,
            TaskStatus.PLANNING,
            TaskStatus.PENDING,
        ]
        for st in priority:
            for t in all_tasks:
                if t.id in subtree and TaskStatus(t.status) == st:
                    if st in {TaskStatus.PLANNING, TaskStatus.PENDING, TaskStatus.READY}:
                        if not self._tasks.dependencies_satisfied(t.id):
                            continue
                    if st in {TaskStatus.PLANNING, TaskStatus.PENDING}:
                        kids = [c for c in all_tasks if c.parent_id == t.id]
                        if kids and not all(settled(c) for c in kids):
                            continue
                    return t
        return None

    def _subtree_ids(self, root_id: uuid.UUID, tasks: list[TaskModel]) -> set[uuid.UUID]:
        """Recolhe o identificador da raiz e o de todos os seus descendentes.

            Args:
                root_id: identificador da raiz da árvore.
                tasks: tarefas do projeto.

            Returns:
                O conjunto de identificadores da subárvore.
        """
        ids = {root_id}
        changed = True
        while changed:
            changed = False
            for t in tasks:
                if t.parent_id in ids and t.id not in ids:
                    ids.add(t.id)
                    changed = True
        return ids

    def _all_terminal_under(self, root_id: uuid.UUID) -> bool:
        """Diz se todas as etapas abaixo da raiz chegaram a um estado final.

            Args:
                root_id: identificador da raiz da árvore.

            Returns:
                Verdadeiro quando nenhuma etapa abaixo da raiz continua em andamento.
        """
        stmt = select(TaskModel)
        tasks = list(self._session.scalars(stmt).all())
        subtree = self._subtree_ids(root_id, tasks)
        # Check children only (exclude the root task itself)
        for t in tasks:
            if t.id in subtree and t.id != root_id and TaskStatus(t.status) not in {
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
            }:
                return False
        return True

    def _ensure_final_message(self, root: TaskModel) -> None:
        """Garante que a raiz tenha uma resposta final para o usuário.

            Args:
                root: tarefa raiz do objetivo.

            Observações:
                A resposta da etapa de resposta final tem precedência; quando ela não existe, a conclusão é
                montada a partir das etapas e recebe o rodapé de verificações executadas.
        """
        report = dict(root.consolidated_result_json or {})
        current = report.get("final_answer")
        if isinstance(current, str) and current.strip():
            return
        for child in children_of(self._session, root.id):
            meta = child.metadata_json or {}
            result = child.consolidated_result_json or {}
            markdown = result.get("markdown")
            if meta.get("final_answer") and isinstance(markdown, str) and markdown.strip():
                report["final_answer"] = markdown
                report["sources"] = result.get("sources") or []
                root.consolidated_result_json = report
                return
        from agent.orchestrator.closing import (
            compose_final_markdown,
            verification_footer,
        )

        stages = [
            {"title": child.title, "status": child.status, "sources": []}
            for child in children_of(self._session, root.id)
        ]
        markdown = compose_final_markdown(objective=root.objective or root.title, stages=stages)
        footer = verification_footer(self._session, root)
        if footer:
            markdown = f"{markdown.rstrip()}\n\n{footer}"
        report["final_answer"] = markdown
        root.consolidated_result_json = report

    def _work_root(self, project: ProjectModel, task: TaskModel | None) -> str:
        """Pasta de trabalho da etapa (projeto ou conversa solta)."""
        return work_root(self._session, project, task)

