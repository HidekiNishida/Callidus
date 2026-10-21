"""
Arquivo: src/agent/orchestrator/execution/executor.py
Nome: executor.py
Propósito: executar uma única tarefa da árvore e registrar o desfecho dela.
Responsabilidade: camada de aplicação — despacho da etapa (MCP, modelo, ferramenta, verificação) e a evidência.
Componentes: TaskExecutor (execute, finalize_verification, write_final_answer, save_requested_memory).
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
from agent.orchestrator.execution.writes import tool_refusal_result
from agent.orchestrator.requirements import effective_covers
from agent.persistence.models import (
    EvidenceModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.services.attempt_service import AttemptService
from agent.services.project_service import ProjectService
from agent.tools.policy import PermissionPolicy, tool_policy
from agent.tools.registry import ToolContext, canonical_tool_id
from agent.verification.fingerprint import snapshot as artifact_snapshot
from agent.verification.runner import VerificationResult, run_verification

ENVIRONMENT_FAILURES = (FailureCategory.CONFIGURATION, FailureCategory.EXTERNAL_UNAVAILABLE)

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
            out = await self._tools.execute(tool_id, ctx, args, approved=approved)
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
            if out.get("success") and tool_id in {"write_file", "edit_file", "move_file"}:
                p = args.get("path") or args.get("to") or args.get("dest")
                if isinstance(p, str):
                    KnowledgeGraphService(self._session).touch_file(project.id, root_path, p)
            if failure is None:
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self.finalize_verification(run, project, task, root_path)
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
            verification_footer,
        )
        from agent.providers.base import ChatCompletionRequest, ChatMessage
        from agent.providers.observed import observed_chat

        siblings = children_of(self._session, task.parent_id) if task.parent_id else []
        stages: list[dict] = []
        for sibling in siblings:
            if sibling.id == task.id:
                continue
            result = sibling.consolidated_result_json or {}
            blob = str(result)
            stages.append(
                {
                    "title": sibling.title,
                    "status": sibling.status,
                    "sources": extract_sources(blob, sibling.objective or ""),
                }
            )
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
        sources = extract_sources(markdown, *[str(stage.get("sources")) for stage in stages])
        task.consolidated_result_json = {"final_answer": True, "markdown": markdown, "sources": sources}
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
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            consolidate_parent(self._session, task.parent_id) if task.parent_id else None
            return {"action": "completed_without_verification", "task_id": str(task.id)}

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
            task.consolidated_result_json = {
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
