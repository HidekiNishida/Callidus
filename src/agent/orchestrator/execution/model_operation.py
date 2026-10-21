"""
Arquivo: src/agent/orchestrator/execution/model_operation.py
Nome: model_operation.py
Propósito: executar uma etapa de operação de modelo (inferência + ferramentas + escrita do arquivo).
Responsabilidade: camada de aplicação — o fluxo de uma alteração pedida ao modelo; não decide o estado do run.
Componentes: ModelOperation (run), ContextOverflow, e os handlers de tentativa, ferramenta e recusa.
Dependências: agent.providers.base/observed, agent.orchestrator.tool_loop, agent.context.operation_builder, agent.orchestrator.execution.*.
Observações: o modelo responde; a verificação julga. A resposta do modelo nunca é evidência de sucesso.
"""

from __future__ import annotations

from typing import Any

from agent.context.budget import ContextBudgetError
from agent.context.operation_builder import OperationContextBuilder
from agent.domain.enums import AttemptKind, TaskStatus
from agent.domain.failures import (
    Failure,
    FailureCategory,
    FailureCause,
    classify_context_error,
    classify_model_output,
    classify_provider_error,
    classify_tool_result,
)
from agent.domain.schemas import TaskStatusUpdate
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.observability import emit
from agent.orchestrator.execution.guards import (
    compact_inspection,
    operation_tools_for,
    payload_is_usable,
    write_refusal_reason,
)
from agent.orchestrator.execution.providers import (
    apply_provider_usage,
    profile_from_config,
    select_provider,
    supports_tool_loop,
)
from agent.orchestrator.execution.writes import implicit_spec, model_refusal_result, write_tool_from_payload
from agent.orchestrator.tool_loop import ToolLoopOutcome, run_tool_loop
from agent.persistence.models import ExecutionRunModel, ProjectModel, TaskModel
from agent.providers.base import ChatCompletionRequest, ProviderError
from agent.providers.observed import observed_chat
from agent.services.attempt_service import AttemptService
from agent.util.json_parse import parse_json_object


class ModelOperation:
    """Fluxo de uma etapa de operação de modelo.

    A classe recebe o executor que a criou e usa os colaboradores dele (sessão, serviços,
    registro de ferramentas) — assim há um único lugar que decide o estado da etapa.

    Observações:
        Nada aqui aprova o próprio resultado: a escrita concluída segue para a verificação,
        que é independente de quem executou.
    """

    def __init__(self, executor: Any) -> None:
        """Guarda o executor responsável pela etapa.

        Args:
            executor: executor da tarefa; fornece a sessão, os serviços e a finalização da verificação.
        """
        self._executor = executor

    @property
    def _runtime(self):
        """Colaboradores da execução (sessão, settings, serviços, ferramentas)."""
        return self._executor.runtime

    async def run(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        config: dict,
        root_path: str,
        ctx: Any,
    ) -> dict[str, Any]:
        """Executa a operação pedida ao modelo e devolve o desfecho da etapa.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa a executar.
            config: configuração do run.
            root_path: pasta de trabalho das ferramentas.
            ctx: contexto de execução das ferramentas (memória, run, etapa).

        Returns:
            Dicionário com `action`, `task_id` e o resultado (ou a falha) da etapa.
        """
        session = self._runtime.session
        settings = self._runtime.settings
        tasks = self._runtime.tasks
        attempts = self._runtime.attempts
        tools = self._runtime.tools
        meta = task.metadata_json or {}

        factory = self._runtime.provider_factory or select_provider
        provider = factory(settings, config)
        profile = profile_from_config(config, settings, provider)
        if meta.get("prompt_key") == "page":
            generation = dict(profile.generation)
            generation["num_predict"] = max(int(generation.get("num_predict") or 0), 4096)
            profile = profile.model_copy(update={"generation": generation})
        truncations = sum(
            1 for item in meta.get("failures") or [] if item.get("cause") == FailureCause.TRUNCATED_OUTPUT.value
        )
        if truncations:
            # O modelo consumiu todo o orçamento de saída e devolveu nada: ampliar a
            # resposta (num_predict e output_reserve) para a próxima tentativa.
            generation = dict(profile.generation)
            base = max(int(generation.get("num_predict") or 0), 2048)
            generation["num_predict"] = min(16384, base * 2**truncations)
            profile = profile.model_copy(
                update={
                    "generation": generation,
                    "output_reserve": min(16384, max(profile.output_reserve, 1024) * 2**truncations),
                }
            )
        explicit_budget = int(meta.get("output_budget") or 0)
        if explicit_budget:
            # Orçamento ampliado na estagnação por corte: vale para esta tentativa.
            generation = dict(profile.generation)
            generation["num_predict"] = max(int(generation.get("num_predict") or 0), explicit_budget)
            profile = profile.model_copy(
                update={
                    "generation": generation,
                    "output_reserve": max(profile.output_reserve, explicit_budget),
                }
            )

        builder = OperationContextBuilder(session)
        build = dict(project_id=project.id, root_path=root_path, task=task, profile=profile, run_id=run.id)
        try:
            budget, snap = builder.build_for_task(**build)
        except ContextBudgetError:
            try:
                budget, snap = builder.build_for_task(**build, compact=True)
            except ContextBudgetError as exc:
                return self._context_overflow(run, project, task, provider.name, profile, exc)
            self._executor.note_thought(run, task, "O contexto não cabia; segui com a versão compactada, sem cortar conteúdo.")
        for note in budget.strategy_notes:
            if note.startswith("skills: "):
                skills_list = [s.strip() for s in note.replace("skills: ", "").split(",") if s.strip()]
                emit("skill.selected", {"skills": skills_list, "task_id": str(task.id)}, task_id=task.id, commit=True)
                break
        self._executor.note_thought(run, task, f"Pensando na alteração «{task.title}» com {profile.model_id}.")
        # Fragmentos só quando o provedor transmite de verdade; `stream: false` (etapa ou run) desliga.
        stream_allowed = meta.get("stream", config.get("stream", True)) is not False
        prompt_fp = AttemptService.fingerprint(
            "\n".join(m.content for m in budget.messages)
            + repr(sorted(profile.generation.items()))
            + f"|orçamento:{profile.output_reserve}"
        )
        attempt_request = {
            "context_snapshot_id": str(snap.id),
            "tokens_est": budget.estimated_tokens,
            "prompt_fp": prompt_fp,
        }
        if attempts.prompt_already_sent(task.id, prompt_fp):
            failure = Failure(
                FailureCategory.CHANGE_STRATEGY,
                FailureCause.REPEATED_PROMPT,
                "o pedido ao modelo seria idêntico a uma tentativa anterior",
            )
            attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider.name,
                request=attempt_request,
                response=None,
                success=False,
                project_id=project.id,
                failure=failure,
            )
            noted = self._executor.remember_failure(task, failure)
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=failure.detail))
            return {"action": "blocked_loop", "task_id": str(task.id), "failure": noted}
        tool_log: list[dict[str, Any]] = []
        inspections: list[dict[str, Any]] = []
        used_tokens = 0

        async def _chat_model(provider_obj, request, *, purpose: str, stream: bool):
            """Chamada ao modelo dentro do ciclo: registra a evidência de cada iteração.

            A iteração final (a que traz a resposta) é registrada depois, com a classificação
            do resultado; aqui ficam as iterações intermediárias, em que o modelo pediu
            ferramentas.
            """
            nonlocal used_tokens
            resp = await observed_chat(provider_obj, request, purpose=purpose, stream=stream)
            used_tokens += int(getattr(resp, "completion_tokens_estimate", None) or 0)
            calls = list(getattr(resp, "tool_calls", None) or [])
            if not calls:
                return resp
            iteration_fp = AttemptService.fingerprint(
                "\n".join(m.content for m in request.messages) + f"|iteração:{len(tool_log)}"
            )
            attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider_obj.name,
                request={**attempt_request, "iteration_fp": iteration_fp},
                response={
                    "content_preview": (resp.content or "")[:500],
                    "tool_calls": [{"tool": item.name, "args": item.arguments} for item in calls],
                    "reasoning_chars": len(getattr(resp, "reasoning", None) or ""),
                },
                success=True,
                project_id=project.id,
            )
            return resp

        async def _on_tool_call(entry: dict[str, Any], result: dict[str, Any]) -> None:
            """Registra a chamada de ferramenta feita pelo modelo durante o ciclo."""
            tool_log.append(entry)
            inspections.append(
                {
                    "tool": entry.get("tool"),
                    "path": (entry.get("args") or {}).get("path"),
                    "content": entry.get("content") or "",
                }
            )
            attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.TOOL,
                provider=str(entry.get("tool")),
                request=entry.get("args") or {},
                response={"success": entry.get("success"), "summary": entry.get("summary")},
                success=bool(entry.get("success")),
                project_id=project.id,
                failure=classify_tool_result(result),
            )
            emit(
                "model.tool_call",
                {"tool": entry.get("tool"), "success": entry.get("success"), "summary": entry.get("summary")},
                task_id=task.id,
            )

        try:
            if supports_tool_loop(provider):
                outcome = await run_tool_loop(
                    provider=provider,
                    messages=budget.messages,
                    profile=profile,
                    registry=tools,
                    ctx=ctx,
                    approved=bool(config.get("approve_risky_tools") or meta.get("approved")),
                    max_iterations=settings.max_tool_iterations,
                    max_tool_calls=settings.max_tool_calls,
                    stream=stream_allowed,
                    chat=_chat_model,
                    on_tool_call=_on_tool_call,
                    tool_ids=operation_tools_for(meta),
                    payload_ok=payload_is_usable,
                    tool_guard=lambda name, args: write_refusal_reason(meta, name, args.get("path")),
                    deliverable_hint=(
                        "Entregue agora a alteração. Responda só com JSON: "
                        '{"path":"arquivo","content":"conteúdo inteiro"} ou '
                        '{"path":"arquivo","old_string":"trecho","new_string":"novo"}. '
                        "Nada de explicação, nada de comentário."
                    ),
                )
            else:
                resp = await _chat_model(
                    provider,
                    ChatCompletionRequest(messages=budget.messages, profile=profile),
                    purpose="operation",
                    stream=stream_allowed,
                )
                outcome = ToolLoopOutcome(content=resp.content or "", iterations=1, stop_reason="final")
            content = outcome.content or ""
        except ProviderError as exc:
            self._executor.note_thought(run, task, f"A inferência falhou: {exc}.")
            failure = classify_provider_error(str(exc), exc)
            attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider.name,
                request=attempt_request,
                response={"error": str(exc)},
                success=False,
                error=str(exc),
                project_id=project.id,
                failure=failure,
            )
            noted = self._executor.remember_failure(task, failure)
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {
                "action": "model_operation_error",
                "task_id": str(task.id),
                "error": str(exc),
                "failure": noted,
            }
        excerpt = " ".join(content.split())[:280]
        apply_provider_usage(task, provider)
        if inspections:
            # O que esta tentativa inspecionou fica na tarefa: a próxima tentativa continua
            # dali em vez de reler os mesmos arquivos do zero.
            meta = dict(task.metadata_json or {})
            meta["inspection"] = compact_inspection(inspections)
            task.metadata_json = meta
        if tool_log:
            self._executor.note_thought(
                run,
                task,
                "Inspecionei com as ferramentas: " + ", ".join(f"{item['tool']}" for item in tool_log[:6]),
                phase="tool",
            )
        if outcome.applied:
            # O modelo aplicou a alteração chamando a ferramenta: mesmo caminho de escrita e
            # de verificação do protocolo JSON, com a evidência no mesmo lugar.
            tool_name = outcome.applied_tool or "write_file"
            payload = dict(outcome.applied_args or {})
            out = dict(outcome.applied_result or {})
            refusal = write_refusal_reason(meta, tool_name, payload.get("path"))
            if refusal:
                # A escrita é recusada e a recusa é o resultado da etapa (o modelo
                # respondeu, o arquivo não mudou). Bloquear a etapa faria o sistema
                # repetir o mesmo pedido para sempre.
                task.consolidated_result_json = model_refusal_result(
                    tool_name,
                    payload.get("path"),
                    refusal,
                    report=content.strip(),
                    snapshot_id=str(snap.id),
                )
                self._executor.note_thought(run, task, refusal, phase="tool")
                tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                done = await self._executor.finalize_verification(run, project, task, root_path)
                done["thought"] = excerpt
                return done
            # A operação que aplicou a mudança é uma tentativa da tarefa: sem esta linha a
            # contagem de tentativas ignoraria toda operação que terminou em escrita.
            attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider.name,
                request=attempt_request,
                response={
                    "content_preview": content[:500],
                    "tool_calls": [str(item.get("tool")) for item in tool_log],
                    "applied": tool_name,
                    "reasoning_chars": len(outcome.reasoning or ""),
                },
                success=bool(out.get("success")),
                project_id=project.id,
            )
            path = payload.get("path")
            task.consolidated_result_json = {
                "model_operation": True,
                "tool": tool_name,
                "write": out,
                "context_snapshot_id": str(snap.id),
            }
            if out.get("success") and isinstance(path, str):
                KnowledgeGraphService(session).touch_file(project.id, root_path, path)
            if out.get("success"):
                tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                written = str(
                    payload.get("new_string") if tool_name == "edit_file" else payload.get("content") or ""
                )
                done = await self._executor.finalize_verification(
                    run, project, task, root_path, implicit_spec=implicit_spec(path, written)
                )
                if excerpt:
                    done["thought"] = excerpt
                return done
            noted = self._executor.remember_failure(task, classify_tool_result(out))
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {
                "action": "model_operation_failed",
                "task_id": str(task.id),
                "thought": excerpt,
                "failure": noted,
            }
        data, err = parse_json_object(content)
        missing = ["path"] if data is not None and "path" not in data else None
        if data is None and meta.get("read_only") and content.strip():
            # Etapa somente leitura: a entrega é o relatório em texto, não uma escrita.
            # Exigir JSON aqui transformaria um pedido de leitura em erro de formato.
            task.consolidated_result_json = {
                "model_operation": True,
                "read_only": True,
                "report": content.strip(),
                "context_snapshot_id": str(snap.id),
            }
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            done = await self._executor.finalize_verification(run, project, task, root_path)
            done["thought"] = excerpt
            return done
        # O orçamento efetivo de saída: o que o provedor pode gerar nesta chamada.
        generation_now = dict(profile.generation or {})
        output_budget = int(
            generation_now.get("num_predict") or generation_now.get("max_tokens") or profile.output_reserve
        )
        failure = classify_model_output(
            content,
            err,
            missing,
            budget=output_budget,
            used_tokens=used_tokens or None,
            reasoning=outcome.reasoning,
        )
        if failure is not None and failure.cause == FailureCause.TRUNCATED_OUTPUT:
            self._executor.note_thought(
                run,
                task,
                f"O modelo usou todo o orçamento de {output_budget} tokens e devolveu "
                f"{'nada' if not content.strip() else 'uma resposta incompleta'}; "
                "vou ampliar a resposta e tentar de novo.",
            )
        if failure is not None and failure.cause == FailureCause.EMPTY_OUTPUT:
            self._executor.note_thought(
                run,
                task,
                "O modelo raciocinou e não devolveu a alteração pedida; "
                "vou pedir de novo, com a instrução de responder direto.",
            )
        attempts.record(
            run_id=run.id,
            task_id=task.id,
            kind=AttemptKind.MODEL,
            provider=provider.name,
            request=attempt_request,
            response={
                "content_preview": content[:500],
                "tool_calls": [str(item.get("tool")) for item in tool_log],
                "reasoning_chars": len(outcome.reasoning or ""),
                # O raciocínio explica a resposta vazia: é a evidência do que o modelo
                # pretendia fazer (pedir ferramenta, aplicar a mudança, …).
                "reasoning_preview": (outcome.reasoning or "")[-600:],
            },
            success=failure is None,
            project_id=project.id,
            failure=failure,
        )
        if failure is not None or data is None:
            noted = self._executor.remember_failure(task, failure) if failure else None
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {
                "action": "model_operation_invalid",
                "task_id": str(task.id),
                "error": err,
                "thought": excerpt,
                "failure": noted,
            }
        tool_name, payload = write_tool_from_payload(data)
        refusal = write_refusal_reason(meta, tool_name, payload.get("path"))
        if refusal:
            # A escrita é recusada antes de tocar o disco, e a recusa vira o resultado da
            # etapa (sem repetir o mesmo pedido para sempre).
            task.consolidated_result_json = model_refusal_result(
                tool_name,
                payload.get("path"),
                refusal,
                report=content.strip(),
                snapshot_id=str(snap.id),
            )
            self._executor.note_thought(run, task, refusal, phase="tool")
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            done = await self._executor.finalize_verification(run, project, task, root_path)
            done["thought"] = excerpt
            return done
        out = await tools.execute(tool_name, ctx, payload, approved=bool(config.get("approve_risky_tools") or meta.get("approved")))
        task.consolidated_result_json = {
            "model_operation": True,
            "tool": tool_name,
            "write": out,
            "context_snapshot_id": str(snap.id),
        }
        if out.get("success") and isinstance(data.get("path"), str):
            KnowledgeGraphService(session).touch_file(project.id, root_path, data["path"])
        if out.get("success"):
            tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            written = str(payload.get("new_string") if tool_name == "edit_file" else payload.get("content") or "")
            done = await self._executor.finalize_verification(
                run, project, task, root_path, implicit_spec=implicit_spec(payload.get("path"), written)
            )
            if excerpt:
                done["thought"] = excerpt
            return done
        noted = self._executor.remember_failure(task, classify_tool_result(out))
        tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
        return {
            "action": "model_operation_failed",
            "task_id": str(task.id),
            "thought": excerpt,
            "failure": noted,
        }

    def _context_overflow(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        provider_name: str,
        profile: Any,
        exc: ContextBudgetError,
    ) -> dict[str, Any]:
        """O obrigatório não cabe nem compactado: nada é enviado ao modelo e a tarefa para com a explicação.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa que não coube no orçamento.
            provider_name: nome do provedor escolhido.
            profile: perfil do modelo (com o orçamento aplicado).
            exc: erro de orçamento com o detalhamento do consumo.

        Returns:
            Dicionário com `action` = `blocked_context` e a falha registrada.
        """
        biggest = max((item for item in exc.breakdown if item["required"]), key=lambda item: item["tokens"])
        detail = (
            f"{exc.required_tokens} tokens obrigatórios > orçamento {exc.budget} de {profile.model_id}; "
            f"maior parte: {biggest['name']} ({biggest['tokens']} tokens). "
            "Divida o pedido ou use um modelo com contexto maior."
        )
        failure = classify_context_error(detail)
        self._runtime.attempts.record(
            run_id=run.id,
            task_id=task.id,
            kind=AttemptKind.MODEL,
            provider=provider_name,
            request={"context_snapshot_id": exc.snapshot_id, "breakdown": exc.breakdown, "budget": exc.budget},
            response=None,
            success=False,
            project_id=project.id,
            failure=failure,
        )
        noted = self._executor.remember_failure(task, failure)
        self._executor.note_thought(run, task, f"O contexto necessário não cabe no modelo: {detail}")
        self._runtime.tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.BLOCKED, reason=detail))
        return {"action": "blocked_context", "task_id": str(task.id), "failure": noted}
