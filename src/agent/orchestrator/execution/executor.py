"""
Arquivo: src/agent/orchestrator/execution/executor.py
Nome: executor.py
Propósito: executar uma única tarefa da árvore e registrar o desfecho dela.
Responsabilidade: camada de aplicação — despacho da etapa (MCP, modelo, ferramenta, verificação) e a evidência.
Componentes: TaskExecutor (execute, finalize_verification, diagnostic_complement, approval_gate, inflight_guard, clear_inflight, await_approval, write_final_answer, save_requested_memory), unmet_criterion, stage_finding.
Dependências: agent.orchestrator.execution.*, agent.services.*, agent.verification.*, agent.tools.registry.
Observações: o executor decide **como** a etapa roda; o orquestrador decide **quando** ela roda.
"""

from __future__ import annotations

from typing import Any

from agent.domain.enums import AttemptKind, MemoryKind, TaskKind, TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
    classify_tool_result,
    classify_verification,
)
from agent.domain.schemas import MemoryCreate, TaskStatusUpdate
from agent.i18n.locale import language_instruction
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.orchestrator.consolidation import (
    children_of,
    consolidate_parent,
    remember_final_answer,
    settled,
    stages_outcome,
)
from agent.orchestrator.execution.automation_operation import AutomationOperation
from agent.orchestrator.execution.guards import evidence_state, write_refusal_reason
from agent.orchestrator.execution.journal import note_thought, remember_failure
from agent.orchestrator.execution.model_operation import ModelOperation
from agent.orchestrator.execution.providers import (
    apply_provider_usage,
    profile_from_config,
    select_provider,
)
from agent.orchestrator.execution.runtime import ExecutionRuntime
from agent.orchestrator.execution.tool_results import (
    is_informative_test_result,
    test_summary,
)
from agent.orchestrator.execution.workspace import work_root
from agent.orchestrator.execution.writes import (
    WriteJournal,
    implicit_spec,
    tool_refusal_result,
)
from agent.orchestrator.requirements import effective_covers
from agent.persistence.models import (
    EvidenceModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.services.attempt_service import AttemptService
from agent.services.project_service import ProjectService
from agent.tools.policy import tool_policy
from agent.tools.registry import ToolContext, canonical_tool_id
from agent.verification.fingerprint import snapshot as artifact_snapshot
from agent.verification.runner import VerificationResult, run_verification

ENVIRONMENT_FAILURES = (FailureCategory.CONFIGURATION, FailureCategory.EXTERNAL_UNAVAILABLE)


#: Orçamento (caracteres) do que as etapas descobriram, levado à resposta final: por etapa e no total.
_FINAL_ANSWER_FINDING_CHARS = 1500
_FINAL_ANSWER_FINDINGS_BUDGET = 4500


def stage_finding(result: dict[str, Any]) -> str:
    """Trecho do resultado de uma etapa que vale levar à resposta final.

    Args:
        result: resultado consolidado da etapa.

    Returns:
        O texto produzido pela etapa (resumo, conteúdo lido, saída), ou vazio.
    """
    if not isinstance(result, dict):
        return ""
    if isinstance(result.get("markdown"), str) and result["markdown"].strip():
        return result["markdown"].strip()
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}
    for key in ("content", "stdout", "summary", "text"):
        if isinstance(inner.get(key), str) and inner[key].strip():
            return inner[key].strip()
    summary = result.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


def unmet_criterion(spec: dict[str, Any], summary: str) -> str:
    """Descreve, em uma linha, o critério de verificação que não foi satisfeito.

    Args:
        spec: critério de verificação que reprovou.
        summary: resumo devolvido pelo verificador.

    Returns:
        O tipo do verificador e o alvo (arquivo, trecho, comando), seguidos do resumo.
    """
    kind = str(spec.get("type") or "verificação")
    target = spec.get("path") or spec.get("command") or ""
    if isinstance(target, list):
        target = " ".join(str(part) for part in target)
    contains = spec.get("contains")
    parts = [kind, str(target)] + ([f"contém {str(contains)[:60]!r}"] if contains else [])
    head = " ".join(part for part in parts if part)
    return f"{head}: {summary[:160]}" if summary else head

# Natureza possível de uma etapa: cada uma leva a um ramo diferente do despacho.
_ACTION_KEYS = ("mcp_tool", "final_answer", "model_operation", "automation_operation", "tool", "verification")


class TaskExecutor:
    """Executa uma etapa da árvore de tarefas.

    O executor é criado uma vez por run e compartilhado com o modelo: os dois usam a mesma
    sessão, o mesmo registro de tentativas e o mesmo registro de ferramentas.

    Observações:
        A verificação é sempre independente de quem executou: quem escreve o arquivo não
        aprova o próprio resultado.
    """

    def __init__(self, runtime: ExecutionRuntime) -> None:
        """Guarda os colaboradores da execução.

        Args:
            runtime: sessão, configuração, serviço de tarefas, registro de tentativas e ferramentas.
        """
        self.runtime = runtime
        self._model_operation = ModelOperation(self)
        self._automation_operation = AutomationOperation(self)

    @property
    def _session(self):
        """Sessão SQLAlchemy em uso."""
        return self.runtime.session

    @property
    def _settings(self):
        """Configuração do processo."""
        return self.runtime.settings

    @property
    def _tasks(self):
        """Serviço de tarefas (transições de estado e dependências)."""
        return self.runtime.tasks

    @property
    def _attempts(self):
        """Registro de tentativas (contagem, dedup e fingerprint)."""
        return self.runtime.attempts

    @property
    def _tools(self):
        """Registro de ferramentas determinísticas."""
        return self.runtime.tools

    def note_thought(
        self,
        run: ExecutionRunModel,
        task: TaskModel | None,
        text: str,
        *,
        phase: str = "thinking",
        category: str | None = None,
    ) -> None:
        """Grava o que está acontecendo e libera o banco para a interface ler durante a inferência.

        Args:
            run: execução em curso.
            task: etapa em foco, quando houver.
            text: descrição curta do que está acontecendo.
            phase: fase da execução (`thinking`, `tool`, ...).
            category: categoria do feed; quando ausente, deriva da fase.
        """
        note_thought(self._session, run, task, text, phase=phase, category=category)

    def remember_failure(self, task: TaskModel, failure: Failure) -> dict[str, Any]:
        """Guarda a falha na tarefa: a próxima tentativa e a política de replanejamento leem daqui.

        Args:
            task: etapa que falhou.
            failure: falha estruturada.

        Returns:
            A falha registrada, com assinatura e estratégia.
        """
        return remember_failure(task, failure)

    def approval_gate(self, run: ExecutionRunModel, project: ProjectModel | None, task: TaskModel):
        """Portão de aprovação granular desta etapa, entregue ao contexto da ferramenta.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa que fará as chamadas.

        Returns:
            Função `(tool, args, risk, reason) -> veredito` que consulta o pedido de aprovação
            persistido da operação, consome uma aprovação concedida e abre o pedido quando
            ainda não existe (registrando o evento `approval.requested`).
        """
        from agent.observability import emit
        from agent.services.approval_service import ApprovalService

        def _gate(tool: str, args: dict[str, Any], risk: str, reason: str) -> dict[str, Any]:
            verdict = ApprovalService(self._session).check(
                tool=tool,
                args=args,
                task_id=task.id,
                run_id=run.id,
                project_id=project.id if project is not None else None,
                risk=risk,
                reason=reason,
            )
            if verdict.get("created"):
                emit(
                    "approval.requested",
                    {"approval_id": verdict["approval_id"], "tool": tool, "risk": risk, "reason": reason},
                    task_id=task.id,
                    commit=True,
                )
            return verdict

        return _gate

    def inflight_guard(
        self,
        run: ExecutionRunModel,
        project: ProjectModel | None,
        task: TaskModel,
        tool_id: str,
        args: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Torna a retomada idempotente para operações que não podem ser repetidas com segurança.

        Antes de uma operação não repetível (a que exige aprovação ou mexe em configuração), a
        etapa grava — e confirma no banco — o marcador `inflight_operation`. Se a execução cair
        no meio, a retomada reencontra o marcador: a operação pode já ter produzido efeito, então
        ela não é repetida às cegas; abre-se um pedido de confirmação para esta operação.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa que fará a chamada.
            tool_id: ferramenta pedida.
            args: argumentos da chamada.

        Returns:
            `None` quando a operação é repetível ou não havia marcador (o marcador é gravado);
            senão o veredito do pedido de confirmação (`approved`, `approval_id`, `status`).
        """
        from agent.services.approval_service import ApprovalService, operation_key

        try:
            spec = self._tools.get_spec(tool_id)
        except Exception:  # ferramenta desconhecida: o registro devolve o erro adequado
            return None
        if not (spec.requires_approval or spec.risk in {"configure", "privileged"}):
            return None
        key = operation_key(tool_id, args)
        meta = dict(task.metadata_json or {})
        marker = meta.get("inflight_operation")
        if isinstance(marker, dict) and marker.get("key") == key:
            verdict = ApprovalService(self._session).check(
                tool=tool_id,
                args={**args, "_resume_after_interruption": True},
                task_id=task.id,
                run_id=run.id,
                project_id=project.id if project is not None else None,
                risk=spec.risk,
                reason="a execução foi interrompida durante esta operação; ela pode já ter produzido efeito",
            )
            if verdict.get("created"):
                from agent.observability import emit

                emit(
                    "approval.requested",
                    {"approval_id": verdict["approval_id"], "tool": tool_id, "reason": "retomada após interrupção"},
                    task_id=task.id,
                    commit=True,
                )
            return verdict
        meta["inflight_operation"] = {"tool": tool_id, "key": key}
        task.metadata_json = meta
        # O marcador precisa estar no disco **antes** do efeito: é ele que a retomada lê.
        self._session.commit()
        return None

    def clear_inflight(self, task: TaskModel) -> None:
        """Remove o marcador de operação em voo depois que a chamada voltou (com sucesso ou não).

        Args:
            task: etapa que fez a chamada.
        """
        meta = task.metadata_json or {}
        if "inflight_operation" in meta:
            task.metadata_json = {k: v for k, v in meta.items() if k != "inflight_operation"}

    def await_approval(
        self,
        run: ExecutionRunModel,
        task: TaskModel,
        tool_id: str,
        out: dict[str, Any],
        failure: Failure | None,
    ) -> dict[str, Any]:
        """A operação do plano exige aprovação: a etapa espera a decisão em vez de repetir a chamada.

        Repetir uma chamada recusada por falta de aprovação devolve a mesma recusa e só
        consome tentativas. A etapa fica BLOCKED com o pedido anotado (`awaiting_approval`);
        o orquestrador pausa o run, e a decisão (`ApprovalService.decide`) a devolve ao fluxo.
        Uma operação **negada** também bloqueia, mas sem espera: o replanejamento decide.

        Args:
            run: execução em curso.
            task: etapa que pediu a operação.
            tool_id: ferramenta recusada.
            out: recusa devolvida pelo registro, com `approval_id` e `approval_status`.
            failure: falha classificada da recusa.

        Returns:
            Ação `awaiting_approval` (pedido pendente) ou `approval_denied` (negado).
        """
        approval_id = str(out.get("approval_id"))
        denied = out.get("approval_status") == "denied"
        if failure is not None:
            self.remember_failure(task, failure)
        meta = dict(task.metadata_json or {})
        if denied:
            meta.pop("awaiting_approval", None)
            reason = f"operação negada por quem aprova: {tool_id}"
        else:
            meta["awaiting_approval"] = approval_id
            reason = f"aguardando aprovação para {tool_id}"
        meta["blocked_reason"] = reason
        task.metadata_json = meta
        self.note_thought(
            run,
            task,
            (
                f"A operação {tool_id} foi negada. Não vou executá-la; o plano precisa de outro caminho."
                if denied
                else f"A operação {tool_id} é arriscada e precisa de aprovação. Vou esperar a decisão, sem repetir a chamada."
            ),
            phase="block",
            category="alert",
        )
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=reason))
        return {
            "action": "approval_denied" if denied else "awaiting_approval",
            "task_id": str(task.id),
            "approval_id": approval_id,
            "tool": tool_id,
        }

    def _provider(self, settings, config: dict):
        """Provedor do run segundo a política da execução.

        Args:
            settings: configuração do processo.
            config: configuração do run.

        Returns:
            A instância do provedor escolhido.
        """
        factory = self.runtime.provider_factory or select_provider
        return factory(settings, config)

    def work_root(self, project: ProjectModel, task: TaskModel | None) -> str:
        """Pasta de trabalho da etapa.

        Args:
            project: projeto da execução.
            task: etapa em foco.

        Returns:
            O caminho absoluto da pasta de trabalho.
        """
        return work_root(self._session, project, task)

    def criteria_of(self, task: TaskModel) -> dict[str, Any]:
        """Critério avaliado pela verificação: requisitos que a etapa cobre e o critério de aceite dela.

        Args:
            task: etapa verificada.

        Returns:
            Dicionário com `requirements`, `partial` e `acceptance`.
        """
        covers = effective_covers(self._session, task)
        return {
            "requirements": [c["req"] for c in covers],
            "partial": [c["req"] for c in covers if c["partial"]],
            "acceptance": task.acceptance_criteria or "",
        }

    def save_requested_memory(self, project: ProjectModel, task: TaskModel, args: dict) -> dict:
        """Grava a memória pedida pela ferramenta `remember`.

        Args:
            project: projeto da execução.
            task: etapa que pediu a memória.
            args: argumentos da ferramenta (`content`, `scope`, `title`).

        Returns:
            Dicionário com `success` e os dados da memória gravada.
        """
        content = str(args.get("content") or args.get("text") or "").strip()
        if not content:
            return {"success": False, "error": "conteúdo vazio"}
        scope = str(args.get("scope") or "conversation").lower()
        title = str(args.get("title") or content[:80]).strip() or "Memória"
        conversation_id = None if scope == "project" else task.conversation_id
        kind = MemoryKind.CANONICAL if scope == "project" else MemoryKind.CONTEXTUAL
        record = ProjectService(self._session).add_memory(
            project.id,
            MemoryCreate(
                kind=kind,
                title=title[:180],
                content=content,
                task_id=task.id,
                conversation_id=conversation_id,
            ),
        )
        return {
            "success": True,
            "id": str(record.id),
            "summary": record.summary,
            "scope": "project" if conversation_id is None else "conversation",
        }

    async def execute(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        config: dict,
        work_root_path: str | None = None,
    ) -> dict[str, Any]:
        """Executa a etapa e devolve o desfecho.

        O despacho segue a natureza da etapa: ferramenta MCP, resposta final, operação de
        modelo, ferramenta do plano, verificação declarada, consolidação dos filhos.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa a executar.
            config: configuração do run.
            work_root_path: pasta de trabalho; quando ausente, é resolvida.

        Returns:
            Dicionário com `action`, `task_id` e o resultado (ou a falha) da etapa.
        """
        root_path = work_root_path or self.work_root(project, task)
        if self._attempts.attempts_exhausted(task.id):
            failure = self.remember_failure(
                task,
                Failure(FailureCategory.OPERATIONAL_LIMIT, FailureCause.ATTEMPTS_EXHAUSTED, "limite de tentativas"),
            )
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.FAILED, reason="limite de tentativas"),
            )
            return {"action": "blocked_attempts", "task_id": str(task.id), "failure": failure}

        meta = task.metadata_json or {}
        remote = None
        if project is not None:
            remote_config = ProjectService(self._session).get_remote(project.id)
            if remote_config:
                from agent.remote.ssh import RemoteConfig

                try:
                    remote = RemoteConfig(**remote_config)
                except Exception:  # configuração inválida: o projeto segue local
                    remote = None
        ctx = ToolContext(
            project_root=root_path,
            run_id=str(run.id),
            task_id=str(task.id),
            memory_saver=lambda args, task=task, project=project: self.save_requested_memory(project, task, args),
            browser_mode=str(config.get("browser_mode") or "off"),
            remote=remote,
            # As ferramentas que consultam o estado persistente (as automações) usam a
            # mesma sessão da execução: o modelo fala com os serviços, não com HTTP.
            session=self._session,
            project_id=str(project.id) if project is not None else None,
            conversation_id=str(task.conversation_id) if task.conversation_id else None,
            settings=self._settings,
            # A política decide o que roda sem aprovação; o registro permite ao modelo
            # pedir o catálogo e o detalhe de uma ferramenta sob demanda.
            policy=tool_policy(self._settings),
            scratch={"registry": self._tools},
            approval_gate=self.approval_gate(run, project, task),
        )
        approved = bool(config.get("approve_risky_tools") or meta.get("approved"))

        if meta.get("mcp_tool"):
            from agent.mcp.manager import McpManager

            mgr = McpManager(self._settings.mcp_config_path or self._settings.data_dir / "mcp.json")
            out = await mgr.call_tool(meta["mcp_tool"], meta.get("mcp_args") or {})
            failure = classify_tool_result(out)
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.TOOL,
                provider="mcp",
                request=meta,
                response=out,
                success=failure is None,
                project_id=project.id,
                failure=failure,
            )
            task.consolidated_result_json = {"mcp": meta["mcp_tool"], "result": out}
            if failure is None:
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self.finalize_verification(run, project, task, root_path)
            noted = self.remember_failure(task, failure)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "mcp_tool", "task_id": str(task.id), "success": False, "failure": noted}

        if meta.get("automation_operation"):
            # Pedido sobre tarefas agendadas: a etapa opera as ferramentas de automação
            # e responde com o estado real devolvido por elas.
            return await self._automation_operation.run(run, project, task, config, root_path, ctx)

        if meta.get("final_answer"):
            return await self.write_final_answer(run, project, task, config)

        if meta and not any(meta.get(key) for key in _ACTION_KEYS) and not children_of(self._session, task.id):
            meta = {**meta, "model_operation": True}
            task.metadata_json = meta
            self.note_thought(run, task, f"«{task.title}» não dizia como fazer; vou executar como alteração.")

        if meta.get("model_operation"):
            return await self._model_operation.run(run, project, task, config, root_path, ctx)

        if meta.get("tool"):
            tool_id = canonical_tool_id(meta["tool"])
            args = meta.get("tool_args") or {}
            target = args.get("path") or args.get("pattern") or args.get("command") or ""
            where = f" em {target}" if isinstance(target, str) and target else ""
            refusal = write_refusal_reason(meta, tool_id, args.get("path"))
            if refusal:
                # A escrita do plano é recusada antes de tocar o disco, e a recusa fica
                # registrada como o resultado da etapa.
                task.consolidated_result_json = tool_refusal_result(tool_id, args.get("path"), refusal)
                self.note_thought(run, task, refusal, phase="tool")
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                done = await self.finalize_verification(run, project, task, root_path)
                done["tool"] = tool_id
                return done
            self.note_thought(run, task, f"Usando {tool_id}{where}.", phase="tool")
            # Escrita pronta vinda do plano: guarda o original para desfazer se a verificação
            # reprovar (visto com o qwen3-vl:8b: `def def clear_fields` concluído "sem verificação").
            plan_write_journal = WriteJournal(root_path) if tool_id in {"write_file", "edit_file"} else None
            if plan_write_journal is not None:
                plan_write_journal.remember(tool_id, args.get("path"))
            guarded = self.inflight_guard(run, project, task, tool_id, args)
            if guarded is not None and not guarded.get("approved"):
                return self.await_approval(
                    run,
                    task,
                    tool_id,
                    {"approval_id": guarded.get("approval_id"), "approval_status": guarded.get("status")},
                    None,
                )
            out = await self._tools.execute(tool_id, ctx, args, approved=approved or bool(guarded))
            self.clear_inflight(task)
            if plan_write_journal is not None and out.get("success"):
                plan_write_journal.settle(tool_id, args.get("path"))
            fp = AttemptService.fingerprint({"tool": tool_id, "result": out})
            if self._attempts.repeated_output_detected(task.id, fp, kind=AttemptKind.TOOL):
                noted = self.remember_failure(
                    task,
                    Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.REPEATED_OUTPUT, "loop detectado"),
                )
                self.note_thought(
                    run,
                    task,
                    "A mesma chamada de ferramenta se repetiu sem mudança. "
                    "Vou encerrar esta tentativa para escolher outra abordagem.",
                    phase="recover",
                    category="alert",
                )
                self._tasks.update_status(
                    task.id,
                    TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="loop detectado"),
                )
                return {"action": "blocked_loop", "task_id": str(task.id), "failure": noted}
            failure = classify_tool_result(out)
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.TOOL,
                provider=tool_id,
                request=args,
                response={"tool": tool_id, "result": out},
                success=failure is None,
                project_id=project.id,
                failure=failure,
            )
            task.consolidated_result_json = {"tool": tool_id, "result": out}
            if out.get("error") == "approval_required" and out.get("approval_id"):
                return self.await_approval(run, task, tool_id, out, failure)
            if out.get("success") and tool_id in {"write_file", "edit_file", "move_file"}:
                p = args.get("path") or args.get("to") or args.get("dest")
                if isinstance(p, str):
                    KnowledgeGraphService(self._session).touch_file(project.id, root_path, p)
            if failure is None:
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                if plan_write_journal is None or meta.get("verification"):
                    return await self.finalize_verification(run, project, task, root_path)
                # Escrita sem verificação declarada: a mesma régua das escritas do modelo
                # (o trecho gravado, a sintaxe e a integridade do projeto); reprovada, desfeita.
                written = args.get("new_string") if tool_id == "edit_file" else args.get("content")
                done = await self.finalize_verification(
                    run, project, task, root_path, implicit_spec=implicit_spec(args.get("path"), str(written or ""))
                )
                if done.get("action") != "verified_ok" and plan_write_journal.originals:
                    restored = plan_write_journal.restore()
                    if restored:
                        self.note_thought(
                            run, task, "A verificação reprovou a edição do plano; desfiz a escrita.", phase="recover"
                        )
                        done["undone"] = restored
                    if plan_write_journal.conflicts:
                        done["rollback_conflicts"] = plan_write_journal.conflicts
                return done
            if is_informative_test_result(tool_id, out):
                # Rodar a suíte e ver os testes falharem **é o resultado**, não uma ferramenta
                # quebrada: repetir a mesma chamada devolve a mesma falha. A etapa registra o
                # que a suíte disse e segue para a verificação, que é quem julga o código.
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                done = await self.finalize_verification(run, project, task, root_path)
                done["tool"] = tool_id
                done["thought"] = (
                    f"A suíte de testes rodou e reprovou: {test_summary(out)}"
                )
                return done
            if failure.cause == FailureCause.TOOL_INPUT and self._attempts.repeated_output_detected(
                task.id, fp, window=2, kind=AttemptKind.TOOL
            ):
                # Erro de entrada é determinístico: repetir a mesma chamada não muda nada.
                # A etapa para para o replanejamento adaptar o plano (outro arquivo, outra
                # ferramenta) em vez de insistir em chamada idêntica.
                noted = self.remember_failure(
                    task,
                    Failure(
                        FailureCategory.CHANGE_STRATEGY,
                        FailureCause.TOOL_INPUT,
                        f"a mesma chamada de ferramenta falhou de novo: {failure.detail}",
                    ),
                )
                self.note_thought(
                    run,
                    task,
                    "Os mesmos argumentos falharam de novo. Vou corrigir a entrada em vez de repetir a chamada idêntica.",
                    phase="recover",
                    category="alert",
                )
                self._tasks.update_status(
                    task.id,
                    TaskStatusUpdate(
                        status=TaskStatus.BLOCKED,
                        reason=f"a mesma chamada de ferramenta falhou de novo: {failure.detail}"[:300],
                    ),
                )
                return {
                    "action": "tool_executed",
                    "task_id": str(task.id),
                    "success": False,
                    "failure": noted,
                }
            noted = self.remember_failure(task, failure)
            from agent.orchestrator.recovery_policy import narrate_failure

            self.note_thought(
                run,
                task,
                narrate_failure(failure.category.value, failure.cause.value, failure.detail),
                phase="recover",
                category="error" if failure.category == FailureCategory.CONFIGURATION else "alert",
            )
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "tool_executed", "task_id": str(task.id), "success": False, "failure": noted}

        if meta.get("verification"):
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            return await self.finalize_verification(run, project, task, root_path)

        kids = children_of(self._session, task.id)
        if kids:
            report = consolidate_parent(self._session, task.id)
            current = TaskStatus(task.status)
            if report is None and current == TaskStatus.RUNNING:
                for status in (TaskStatus.VERIFYING, TaskStatus.PLANNING):
                    self._tasks.update_status(task.id, TaskStatusUpdate(status=status, reason="aguardando etapas"))
            elif current == TaskStatus.RUNNING:
                pending = ", ".join(f"«{item['title']}»" for item in (report or {}).get("pending") or [])
                noted = self.remember_failure(
                    task,
                    Failure(
                        FailureCategory.BLOCKED_DEPENDENCY,
                        FailureCause.DEPENDENCY_FAILED,
                        f"etapas não concluídas: {pending}",
                    ),
                )
                self.note_thought(
                    run,
                    task,
                    f"Etapas ainda não concluídas impedem fechar «{task.title}». O que já passou permanece.",
                    phase="recover",
                    category="alert",
                )
                self._tasks.update_status(
                    task.id, TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=f"etapas não concluídas: {pending}")
                )
                return {"action": "blocked_children", "task_id": str(task.id), "failure": noted}
            return {
                "action": "consolidated_parent",
                "task_id": str(task.id),
                "achieved": bool((report or {}).get("achieved")),
            }

        if TaskKind(task.kind) == TaskKind.OPERATION and not meta:
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="operação sem metadata"),
            )
            return {"action": "blocked_no_metadata", "task_id": str(task.id)}

        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        return {"action": "skipped_to_verify", "task_id": str(task.id)}

    async def write_final_answer(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        config: dict,
    ) -> dict[str, Any]:
        """Escreve a resposta final da conversa e a deixa pronta para a verificação.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa de resposta final.
            config: configuração do run.

        Returns:
            Dicionário com `action` = `final_answer` ou o desfecho da verificação declarada.
        """
        from agent.guides.discover import capability_line
        from agent.orchestrator.closing import (
            compose_final_markdown,
            extract_sources,
            local_now_line,
            usable_reply,
            validate_final_answer,
            verification_footer,
        )
        from agent.providers.base import ChatCompletionRequest, ChatMessage
        from agent.providers.observed import observed_chat

        siblings = children_of(self._session, task.parent_id) if task.parent_id else []
        stages: list[dict] = []
        budget = _FINAL_ANSWER_FINDINGS_BUDGET
        for sibling in siblings:
            if sibling.id == task.id:
                continue
            result = sibling.consolidated_result_json or {}
            blob = str(result)
            stage = {
                "title": sibling.title,
                "status": sibling.status,
                "sources": extract_sources(blob, sibling.objective or ""),
            }
            # O que a etapa descobriu (o arquivo lido, a saída do comando), dentro de um orçamento
            # fixo: sem isso a resposta final de "leia e explique" seria escrita sem o conteúdo.
            finding = stage_finding(result)[: min(_FINAL_ANSWER_FINDING_CHARS, budget)]
            if finding and sibling.status == TaskStatus.COMPLETED.value:
                stage["finding"] = finding
                budget -= len(finding)
            stages.append(stage)
        parent = self._tasks.get_task(task.parent_id) if task.parent_id else task
        objective = parent.objective if parent else task.objective
        provider = self._provider(settings=self._settings, config=config)
        profile = profile_from_config(config, self._settings, provider)
        prompt = (
            f"{language_instruction(str(config.get('locale') or 'pt'))}\n"
            f"{capability_line(profile.model_id)}\n"
            "Escreva somente a resposta para a pessoa, no idioma do pedido. "
            "Não descreva etapas, verificações, fontes nem o fluxo. "
            "Não monte um relatório. Se bastar uma frase, escreva a frase.\n"
            f"Data e hora locais agora: {local_now_line()}.\n\n"
            f"Pedido:\n{objective[:1500]}\n\nEtapas:\n{stages}"
        )
        model_text = ""
        try:
            self.note_thought(run, task, "Escrevendo a resposta final.")
            resp = await observed_chat(
                provider,
                ChatCompletionRequest(
                    messages=[ChatMessage(role="user", content=prompt)],
                    profile=profile,
                ),
                purpose="final_answer",
                stream=config.get("stream", True) is not False,
            )
            model_text = (resp.content or "").strip()
            apply_provider_usage(task, provider)
        except Exception:
            model_text = ""
        markdown = model_text if usable_reply(model_text) else compose_final_markdown(
            objective=objective,
            stages=stages,
            model_text=model_text,
        )
        # O rodapé é determinístico: o texto do modelo é conciso por desenho, e quem lê a
        # resposta precisa saber, sem depender do julgamento do modelo, o que foi verificado.
        footer = verification_footer(self._session, parent if parent is not None else task)
        if footer:
            markdown = f"{markdown.rstrip()}\n\n{footer}"
        # Validação da resposta final: variáveis de template não preenchidas e placeholders
        # genéricos indicam que o modelo não entregou o conteúdo pedido.
        ok_final, motivo_final = validate_final_answer(markdown)
        if not ok_final:
            from agent.domain.failures import Failure, FailureCategory, FailureCause
            failure = Failure(
                FailureCategory.CHANGE_STRATEGY,
                FailureCause.INVALID_OUTPUT,
                f"resposta final incompleta: {motivo_final}",
            )
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider.name,
                request={"purpose": "final_answer"},
                response={"content_preview": markdown[:500]},
                success=False,
                project_id=project.id,
                failure=failure,
            )
            noted = self.remember_failure(task, failure)
            self.note_thought(
                run,
                task,
                f"A resposta final ainda não está pronta: {motivo_final}. Vou reescrever.",
                phase="recover",
                category="alert",
            )
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING, reason=motivo_final))
            return {
                "action": "final_answer_invalid",
                "task_id": str(task.id),
                "failure": noted,
                "thought": f"Resposta final incompleta: {motivo_final}.",
            }
        sources = extract_sources(markdown, *[str(stage.get("sources")) for stage in stages])
        task.consolidated_result_json = {"final_answer": True, "markdown": markdown, "sources": sources}
        # A conversa lê a raiz. A consolidação só copia o texto quando todos os
        # irmãos já terminaram; sem esta cópia, um cancelamento no meio deixa a
        # resposta escrita e invisível.
        remember_final_answer(self._session, task)
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        spec = (task.metadata_json or {}).get("verification")
        if isinstance(spec, dict) and spec:
            # A verificação declarada na etapa de resposta final **roda**: sem isso a etapa
            # ficava sem evidência, a consolidação a reabria, e o agent reescrevia a
            # resposta para sempre — a resposta não muda nada, a medição é a mesma.
            return await self.finalize_verification(
                run, project, task, self.work_root(project, task)
            )
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
        if task.parent_id:
            consolidate_parent(self._session, task.parent_id)
        return {"action": "final_answer", "task_id": str(task.id), "thought": markdown[:280]}

    async def finalize_verification(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        work_root_path: str | None = None,
        implicit_spec: dict | None = None,
    ) -> dict[str, Any]:
        """Verificação proporcional ao risco: a declarada na tarefa; senão, para escrita, a implícita
        (`file_contains` com o que foi gravado); leitura sem verificação conclui sem evidência.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa verificada.
            work_root_path: pasta de trabalho; quando ausente, é resolvida.
            implicit_spec: critério implícito derivado da escrita realizada.

        Returns:
            Dicionário com `action` (veredito) e, quando houver, a falha registrada.
        """
        root_path = work_root_path or self.work_root(project, task)
        meta = task.metadata_json or {}
        spec = meta.get("verification") or implicit_spec or meta.get("implicit_verification")
        if isinstance(spec, str):
            # Verificação vinda como texto ("verification": "pytest"): não é um contrato.
            # Tratar como ausente é melhor do que derrubar a etapa com uma exceção.
            spec = None
        if not isinstance(spec, dict) or not spec:
            # Etapa sem verificador automático aplicável (leitura, explicação, operação externa):
            # conclui, mas a limitação fica **registrada** — ausência de verificação não é
            # aprovação. A aceitação por requisito continua exigindo prova na raiz.
            from agent.observability import emit

            reason = "a etapa não declara verificação e não alterou arquivos que gerem uma implícita"
            task.consolidated_result_json = {
                **(task.consolidated_result_json or {}),
                "verified": None,
                "verification_absent": reason,
            }
            emit("verification.skipped", {"reason": reason}, task_id=task.id)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            consolidate_parent(self._session, task.parent_id) if task.parent_id else None
            return {"action": "completed_without_verification", "task_id": str(task.id), "verified": None}

        config = run.config_json or {}
        approved = bool(config.get("approve_risky_tools"))
        tool_args = meta.get("tool_args") or {}
        if str(spec.get("type") or "") == "stages":
            # `stages` confere as etapas das quais esta depende: precisa do estado persistido,
            # não só do disco — por isso não é verificador de arquivo.
            passed_stages, summary_stages, detail_stages = stages_outcome(self._session, task)
            vresult = VerificationResult("stages", passed_stages, summary_stages, detail_stages)
        else:
            vresult = await run_verification(
                project_root=root_path,
                spec=spec,
                tool_args=tool_args,
                approved=approved,
            )
        detail = dict(vresult.detail) if isinstance(vresult.detail, dict) else {}
        artifacts = artifact_snapshot(root_path, spec, tool_args)
        if artifacts:
            detail["artifacts"] = artifacts
        if not meta.get("verification"):
            task.metadata_json = {**meta, "implicit_verification": spec}
        output = f"{detail.get('stdout') or ''}\n{detail.get('stderr') or detail.get('error') or ''}"
        failure = classify_verification(vresult.passed, vresult.summary, output)
        if failure is not None and (
            detail.get("category") == FailureCategory.CONFIGURATION.value or detail.get("error") == "approval_required"
        ):
            failure = classify_tool_result(detail)
        blocked = vresult.passed is False and failure is not None and failure.category in ENVIRONMENT_FAILURES
        passed = None if blocked else vresult.passed
        detail.update(
            state=evidence_state(passed, blocked),
            criteria=self.criteria_of(task),
            command={k: v for k, v in spec.items() if k != "implicit"},
            exit_code=detail.get("exit_code"),
        )
        if failure is not None:
            detail["reason"] = failure.detail[:500]
        if vresult.passed is False and not blocked and not meta.get("final_answer"):
            complement = await self.diagnostic_complement(root_path, spec, vresult, detail, tool_args)
            if complement:
                detail["complement"] = complement
        attempt = self._attempts.record(
            run_id=run.id,
            task_id=task.id,
            kind=AttemptKind.VERIFICATION,
            provider=vresult.verifier,
            request=spec,
            response={"passed": vresult.passed, "summary": vresult.summary},
            success=failure is None,
            project_id=project.id,
            failure=failure,
        )
        self._session.add(
            EvidenceModel(
                task_id=task.id,
                attempt_id=attempt.id,
                verifier=vresult.verifier,
                passed=passed,
                summary=vresult.summary,
                detail_json=detail,
            )
        )
        self._session.flush()

        if vresult.passed is True:
            # O veredito se soma ao resultado da etapa (o arquivo lido, a saída): substituí-lo
            # apagaria o que a etapa produziu e que o pai e a resposta final precisam ler.
            task.consolidated_result_json = {
                **(task.consolidated_result_json or {}),
                "verified": True,
                "summary": vresult.summary,
            }
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            if task.parent_id:
                parent = self._tasks.get_task(task.parent_id)
                kids = children_of(self._session, parent.id)
                if kids and all(settled(k) for k in kids):
                    consolidate_parent(self._session, parent.id)
            return {"action": "verified_ok", "task_id": str(task.id)}

        if blocked:
            noted = self.remember_failure(task, failure)
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=f"verificação bloqueada: {failure.detail[:200]}"),
            )
            return {"action": "verify_blocked", "task_id": str(task.id), "failure": noted}

        if vresult.passed is False:
            if meta.get("final_answer"):
                # A resposta final foi entregue; a verificação reprovou. Reescrever a resposta
                # não muda a medição — o que reprovou é o código, não o texto. A etapa
                # conclude com a evidência reprovada, e o rodapé da resposta reporta o
                # veredito. Quem decide se o requisito está provado é o aceite por requisito.
                task.consolidated_result_json = {
                    "final_answer": True,
                    "verified": False,
                    "summary": vresult.summary,
                }
                self.remember_failure(task, failure)
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
                if task.parent_id:
                    consolidate_parent(self._session, task.parent_id)
                return {"action": "verify_failed", "task_id": str(task.id), "final_answer": True}
            fp = AttemptService.fingerprint({"passed": False, "summary": vresult.summary})
            if self._attempts.repeated_output_detected(task.id, fp, window=2, kind=AttemptKind.VERIFICATION):
                noted = self.remember_failure(
                    task,
                    Failure(FailureCategory.CHANGE_STRATEGY, FailureCause.REPEATED_OUTPUT, vresult.summary),
                )
                self.note_thought(
                    run,
                    task,
                    "A mesma verificação reprovou outra vez. A contagem não prova que o problema é insolúvel; "
                    "vou mudar a abordagem.",
                    phase="recover",
                    category="alert",
                )
                self._tasks.update_status(
                    task.id,
                    TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="a mesma verificação falhou de novo"),
                )
                return {"action": "blocked_loop", "task_id": str(task.id), "failure": noted}
            recovery = self.plan_verification_recovery(task, vresult, detail, spec)
            noted = self.remember_failure(task, failure)
            if recovery.get("retry"):
                task.metadata_json = {
                    **(task.metadata_json or {}),
                    "verification_recovery": recovery,
                    "recovery_guidance": recovery.get("guidance", ""),
                }
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
                return {
                    "action": "verify_failed",
                    "task_id": str(task.id),
                    "failure": noted,
                    "recovery": recovery,
                }
            guidance = str(recovery.get("guidance") or "")[:180]
            if recovery.get("action") == "manual_review":
                recovery_text = f"A verificação não pode seguir sozinha. O impedimento é: {guidance}"
            else:
                recovery_text = (
                    "A mesma recuperação não será repetida. Vou registrar o diagnóstico e mudar a abordagem. "
                    f"{guidance}"
                )
            self.note_thought(run, task, recovery_text, phase="recover", category="alert")
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(
                    status=TaskStatus.BLOCKED,
                    reason=f"verificação reprovou e a recuperação exige intervenção: {str(recovery.get('guidance'))[:200]}",
                ),
            )
            return {
                "action": "verify_blocked",
                "task_id": str(task.id),
                "failure": noted,
                "recovery": recovery,
            }

        noted = self.remember_failure(task, failure)
        self.note_thought(
            run,
            task,
            "A verificação não mediu o resultado. O estado fica sem evidência, não como sucesso.",
            phase="recover",
            category="alert",
        )
        self._tasks.update_status(
            task.id,
            TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="verificação inconclusiva"),
        )
        return {"action": "verify_inconclusive", "task_id": str(task.id), "failure": noted}

    async def diagnostic_complement(
        self,
        root_path: str,
        spec: dict[str, Any],
        vresult: Any,
        detail: dict[str, Any],
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Roda uma verificação complementar somente-leitura para estreitar a causa da reprovação.

        Um complemento que passa (o arquivo existe, a sintaxe é válida) **não aprova** a etapa:
        ele diz que a falha está em outro lugar (comportamento, conteúdo), e isso vai para a
        orientação da próxima tentativa.

        Args:
            root_path: pasta de trabalho.
            spec: critério que reprovou.
            vresult: resultado reprovado.
            detail: detalhe da reprovação.
            tool_args: argumentos da ferramenta da etapa.

        Returns:
            `{"verifier", "passed", "summary"}` do complemento que passou, ou `None`.
        """
        from agent.observability import emit
        from agent.verification.alternatives import run_alternative_verification
        from agent.verification.recovery import diagnose_verification_failure

        diagnosis = diagnose_verification_failure(
            verifier=vresult.verifier, summary=vresult.summary, detail=detail, spec=spec
        )
        try:
            alt = await run_alternative_verification(
                project_root=root_path,
                spec=spec,
                primary_verifier=vresult.verifier,
                diagnosis=diagnosis,
                attempted=[vresult.verifier],
                tool_args=tool_args,
                approved=False,
            )
        except Exception:  # o complemento é diagnóstico: falhar nele não muda o veredito
            return None
        if alt is None:
            return None
        emit(
            "verification.alternative",
            {"verifier": alt.verifier, "primary_verifier": vresult.verifier, "passed": alt.passed},
        )
        return {"verifier": alt.verifier, "passed": alt.passed, "summary": str(alt.summary)[:300]}

    def plan_verification_recovery(
        self,
        task: TaskModel,
        vresult: Any,
        detail: dict[str, Any],
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        """Diagnostica a reprovação e decide o próximo passo (diagnóstico → correção → re-verificação).

        Args:
            task: etapa reprovada.
            vresult: resultado do verificador.
            detail: detalhe da verificação (saída, erro, artefatos).
            spec: critério de verificação executado.

        Returns:
            O plano de recuperação, com causa, ação e indicação de nova tentativa.
        """
        from agent.observability import emit
        from agent.verification.recovery import (
            diagnose_verification_failure,
            plan_recovery,
            recovery_signature,
        )

        diagnosis = diagnose_verification_failure(
            verifier=vresult.verifier,
            summary=vresult.summary,
            detail=detail,
            spec=spec,
        )
        recoveries = int((task.metadata_json or {}).get("verification_recoveries") or 0)
        signature = recovery_signature(diagnosis, detail)
        previous = str((task.metadata_json or {}).get("verification_recovery_signature") or "")
        plan = plan_recovery(
            diagnosis,
            attempt_count=recoveries,
            max_recoveries=self._settings.verification_max_recoveries,
        )
        plan["signature"] = signature
        plan["recoveries"] = recoveries
        plan["diagnosis"] = diagnosis.as_dict()
        plan["unmet_criterion"] = unmet_criterion(spec, vresult.summary)
        complement = detail.get("complement")
        if isinstance(complement, dict) and complement.get("passed") is True:
            plan["guidance"] = (
                f"{plan.get('guidance') or ''} Conferido à parte ({complement['verifier']}): "
                f"{complement['summary']} — a reprovação não vem daí; corrija o comportamento que "
                f"o critério «{plan['unmet_criterion']}» mede."
            ).strip()
        if previous and previous == signature and plan.get("retry"):
            # A **mesma causa** de reprovação voltou. Um contador cru deixaria a recuperação
            # consumir o orçamento de novo como se fosse um problema diferente; a assinatura
            # diz que é o mesmo problema, e o passo para o diagnóstico.
            plan = {
                **plan,
                "action": "block",
                "retry": False,
                "guidance": (
                    "a mesma causa de reprovação voltou; trocar a abordagem da etapa, "
                    "em vez de repetir a mesma recuperação"
                ),
            }
        task.metadata_json = {
            **(task.metadata_json or {}),
            "verification_recoveries": recoveries + 1,
            "verification_recovery_signature": signature,
        }
        emit(
            "verification.recovery_planned",
            {"cause": plan.get("cause"), "action": plan.get("action"), "retry": plan.get("retry", False)},
            task_id=task.id,
            commit=True,
        )
        return plan
