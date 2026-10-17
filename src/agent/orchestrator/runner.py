# src/agent/orchestrator/runner.py — ciclo completo de execução
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.enums import AttemptKind, MemoryKind, RunStatus, TaskKind, TaskStatus
from agent.domain.schemas import MemoryCreate, TaskStatusUpdate
from agent.i18n.locale import detect_language, language_instruction
from agent.orchestrator.consolidation import children_of, consolidate_parent
from agent.orchestrator.global_verify import (
    ensure_global_verification_task,
    evaluate_global_acceptance,
    reopen_verification_gaps,
)
from agent.services.contract_service import ContractService
from agent.orchestrator.atomizer import micro_decompose_operation, should_decompose_further
from agent.orchestrator.decomposition import (
    apply_decomposition,
    executable_leaf,
    plan_copies_siblings,
    resolve_decomposition_plan,
    seal_repeated_steps,
)
from agent.orchestrator.planner import ensure_canonical_memory_for_objective
from agent.orchestrator.replan import replan_under
from agent.context.operation_builder import OperationContextBuilder
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.persistence.models import (
    ConversationModel,
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.services.inbox import effective_root
from agent.providers.base import LLMProvider, ModelProfile
from agent.providers.mock import MockProvider
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.ollama import OllamaProvider
from agent.services.attempt_service import AttemptService
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolContext, build_default_registry
from agent.verification.runner import run_verification


class RunBlockedError(RuntimeError):
    pass


def _select_provider(settings: Settings, run_config: dict) -> LLMProvider:
    name = run_config.get("provider") or settings.default_provider
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url)
    if name == "llamacpp":
        return LlamaCppProvider(settings.llamacpp_base_url)
    if name == "mock":
        kw = run_config.get("mock_keyword_map") or {}
        return MockProvider(keyword_map=kw)
    return MockProvider()


def _profile_from_config(run_config: dict, settings: Settings) -> ModelProfile:
    from agent.orchestrator.decomposition import profile_from_run_config

    return profile_from_run_config(run_config, settings)


class RunOrchestrator:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or Settings()
        self._tasks = TaskService(session)
        self._attempts = AttemptService(session, max_attempts=self._settings.max_attempts_per_task)
        self._tools = build_default_registry()

    def _run_config(self, run: ExecutionRunModel) -> dict:
        return run.config_json or {}

    def _promote_ready_or_block(self, task_id: uuid.UUID) -> dict[str, Any] | None:
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
        title = task.title.strip().casefold()
        parent_id = task.parent_id
        seen: set[uuid.UUID] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = self._session.get(TaskModel, parent_id)
            if parent is None:
                return False
            if parent.title.strip().casefold() == title:
                return True
            parent_id = parent.parent_id
        return False

    def _depth(self, task: TaskModel) -> int:
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

    def _run_as_leaf(self, run: ExecutionRunModel, task: TaskModel, *, note: str) -> dict[str, Any]:
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
        out = await self._step_body(run_id)
        self._record_action(run_id, out)
        return out

    def _record_action(self, run_id: uuid.UUID, out: dict[str, Any]) -> None:
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
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run_id,
                task_id=task_id,
                event_type="orchestrator.action",
                payload_json=payload,
            )
        )

    def _note_thought(self, run: ExecutionRunModel, task: TaskModel | None, text: str, *, phase: str = "thinking") -> None:
        """Grava o que está acontecendo e libera o banco para a interface ler durante a inferência."""
        self._session.add(
            EventLogModel(
                project_id=run.project_id,
                run_id=run.id,
                task_id=task.id if task is not None else None,
                event_type="agent.thought",
                payload_json={"phase": phase, "text": text[:400], "task": task.title if task is not None else None},
            )
        )
        self._session.commit()

    def _save_requested_memory(self, project: ProjectModel, task: TaskModel, args: dict) -> dict:
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

    def _capture_outcome_memory(self, project: ProjectModel, root: TaskModel) -> None:
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

    async def _step_body(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        if run.status in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}:
            return {"action": "run_terminal", "status": run.status}

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
        profile = _profile_from_config(config, self._settings)

        root = self._tasks.get_task(run.root_task_id)
        work_root = self._work_root(project, root)
        revised = replan_under(self._session, root.id)
        if revised:
            self._note_thought(run, root, str(revised.get("thought") or "Replanejei o que ainda falta."))
            return revised
        task = self._pick_next_task(run.root_task_id)
        if task is None:
            ensure_global_verification_task(self._session, project.id, root)
            if self._all_terminal_under(root.id):
                ok, reason = evaluate_global_acceptance(self._session, root.id)
                if not ok:
                    reopened = reopen_verification_gaps(self._session, root.id)
                    if reopened:
                        return {"action": "global_verify_reopen", "reopened": [str(x) for x in reopened]}
                    return {"action": "global_verify_failed", "reason": reason}
                run.status = RunStatus.COMPLETED.value
                self._ensure_final_message(root)
                self._capture_outcome_memory(project, root)
                return {"action": "run_completed", "run_id": str(run_id)}
            return {"action": "waiting", "run_id": str(run_id)}

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
            return {"action": "started_planning", "task_id": str(task.id)}

        if status == TaskStatus.PLANNING:
            kids = children_of(self._session, task.id)
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
            if not kids and (self._same_title_above(task) or self._depth(task) >= 6):
                return self._run_as_leaf(
                    run,
                    task,
                    note=f"«{task.title}» repetiu o mesmo plano. Vou executar esta etapa, sem dividir de novo.",
                )
            if not kids:
                attempts = self._attempts.count_attempts(task.id)
                if meta.get("atomize") or (
                    attempts >= 2
                    and should_decompose_further(
                        objective=task.objective,
                        metadata=meta,
                        kind=task.kind,
                        attempt_count=attempts,
                        has_children=False,
                    )
                ):
                    plan = micro_decompose_operation(task.objective)
                    source = "atomizer-micro"
                else:
                    self._note_thought(run, task, f"Pensando em como dividir «{task.title}».")
                    plan, source = await resolve_decomposition_plan(
                        settings=self._settings,
                        run_config=config,
                        objective=task.objective,
                        project_root=work_root,
                        provider=provider
                        if (config.get("provider") or self._settings.default_provider) in {"ollama", "llamacpp"}
                        else None,
                    )
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
                apply_decomposition(self._session, project.id, task.id, plan)
                titles = ", ".join(spec.title for spec in plan.subtasks[:6])
                return {
                    "action": "decomposed",
                    "task_id": str(task.id),
                    "count": len(plan.subtasks),
                    "source": source,
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
            result = await self._execute_task(run, project, task, config, work_root)
            return result

        if status == TaskStatus.VERIFYING:
            return await self._finalize_verification(run, project, task, work_root)

        if status == TaskStatus.RETRY_PENDING:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
            return {"action": "retry_ready", "task_id": str(task.id)}

        return {"action": "noop", "task_id": str(task.id), "status": task.status}

    async def run_until_idle(self, run_id: uuid.UUID, max_steps: int = 50) -> list[dict]:
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
                "global_verify_failed",
            }:
                break
            if out.get("action") == "waiting":
                if len(log) >= 2 and log[-1] == log[-2]:
                    break
        return log

    def _pick_next_task(self, root_id: uuid.UUID) -> TaskModel | None:
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
                        if kids and not all(TaskStatus(c.status) == TaskStatus.COMPLETED for c in kids):
                            continue
                    return t
        return None

    def _subtree_ids(self, root_id: uuid.UUID, tasks: list[TaskModel]) -> set[uuid.UUID]:
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
        stmt = select(TaskModel)
        tasks = list(self._session.scalars(stmt).all())
        subtree = self._subtree_ids(root_id, tasks)
        for t in tasks:
            if t.id in subtree and TaskStatus(t.status) not in {
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
            }:
                return False
        return True

    async def _execute_task(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        config: dict,
        work_root: str | None = None,
    ) -> dict[str, Any]:
        root_path = work_root or self._work_root(project, task)
        if self._attempts.attempts_exhausted(task.id):
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="limite de tentativas"),
            )
            return {"action": "blocked_attempts", "task_id": str(task.id)}

        meta = task.metadata_json or {}
        ctx = ToolContext(
            project_root=root_path,
            run_id=str(run.id),
            task_id=str(task.id),
            memory_saver=lambda args, task=task, project=project: self._save_requested_memory(
                project, task, args
            ),
            browser_mode=str(config.get("browser_mode") or "off"),
        )
        approved = bool(config.get("approve_risky_tools") or meta.get("approved"))

        if meta.get("mcp_tool"):
            from agent.mcp.manager import McpManager

            mgr = McpManager(self._settings.mcp_config_path or self._settings.data_dir / "mcp.json")
            out = await mgr.call_tool(meta["mcp_tool"], meta.get("mcp_args") or {})
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.TOOL,
                provider="mcp",
                request=meta,
                response=out,
                success=bool(out.get("success")),
                project_id=project.id,
            )
            task.consolidated_result_json = {"mcp": meta["mcp_tool"], "result": out}
            if out.get("success"):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self._finalize_verification(run, project, task, root_path)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "mcp_tool", "task_id": str(task.id), "success": False}

        if meta.get("final_answer"):
            return await self._write_final_answer(run, project, task, config)

        if meta.get("model_operation"):
            provider = _select_provider(self._settings, config)
            profile = _profile_from_config(config, self._settings)
            from agent.providers.base import ChatCompletionRequest
            from agent.util.json_parse import parse_json_object

            builder = OperationContextBuilder(self._session)
            budget, snap = builder.build_for_task(
                project_id=project.id,
                root_path=root_path,
                task=task,
                profile=profile,
                run_id=run.id,
            )
            self._note_thought(run, task, f"Pensando na alteração «{task.title}».")
            resp = await provider.chat(
                ChatCompletionRequest(messages=budget.messages, profile=profile)
            )
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.MODEL,
                provider=provider.name,
                request={"context_snapshot_id": str(snap.id), "tokens_est": budget.estimated_tokens},
                response={"content_preview": resp.content[:500]},
                success=True,
                project_id=project.id,
            )
            excerpt = " ".join((resp.content or "").split())[:280]
            data, err = parse_json_object(resp.content)
            if err or not data or "path" not in data:
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
                return {
                    "action": "model_operation_invalid",
                    "task_id": str(task.id),
                    "error": err,
                    "thought": excerpt,
                }
            old = data.get("old_string", data.get("old"))
            new = data["new_string"] if "new_string" in data else data.get("new")
            if isinstance(old, str) and isinstance(new, str):
                tool_name = "edit_file"
                payload = {"path": data["path"], "old_string": old, "new_string": new}
            else:
                tool_name = "write_file"
                payload = {"path": data["path"], "content": data.get("content", "")}
            out = await self._tools.execute(tool_name, ctx, payload, approved=approved)
            task.consolidated_result_json = {
                "model_operation": True,
                "tool": tool_name,
                "write": out,
                "context_snapshot_id": str(snap.id),
            }
            if out.get("success") and isinstance(data.get("path"), str):
                KnowledgeGraphService(self._session).touch_file(project.id, root_path, data["path"])
            if out.get("success"):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                done = await self._finalize_verification(run, project, task, root_path)
                if excerpt:
                    done["thought"] = excerpt
                return done
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "model_operation_failed", "task_id": str(task.id), "thought": excerpt}

        if meta.get("tool"):
            from agent.tools.registry import canonical_tool_id

            tool_id = canonical_tool_id(meta["tool"])
            args = meta.get("tool_args") or {}
            target = args.get("path") or args.get("pattern") or args.get("command") or ""
            where = f" em {target}" if isinstance(target, str) and target else ""
            self._note_thought(run, task, f"Usando {tool_id}{where}.", phase="tool")
            out = await self._tools.execute(tool_id, ctx, args, approved=approved)
            fp = AttemptService.fingerprint(out)
            if self._attempts.repeated_output_detected(task.id, fp):
                self._tasks.update_status(
                    task.id,
                    TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="loop detectado"),
                )
                return {"action": "blocked_loop", "task_id": str(task.id)}
            self._attempts.record(
                run_id=run.id,
                task_id=task.id,
                kind=AttemptKind.TOOL,
                provider=tool_id,
                request=args,
                response=out,
                success=bool(out.get("success")),
                project_id=project.id,
            )
            task.consolidated_result_json = {"tool": tool_id, "result": out}
            if out.get("success") and tool_id in {"write_file", "edit_file", "move_file"}:
                p = args.get("path") or args.get("to") or args.get("dest")
                if isinstance(p, str):
                    KnowledgeGraphService(self._session).touch_file(project.id, root_path, p)
            if out.get("success"):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self._finalize_verification(run, project, task, root_path)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "tool_executed", "task_id": str(task.id), "success": False}

        if meta.get("verification"):
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            return await self._finalize_verification(run, project, task, root_path)

        kids = children_of(self._session, task.id)
        if kids:
            consolidate_parent(self._session, task.id)
            return {"action": "consolidated_parent", "task_id": str(task.id)}

        if TaskKind(task.kind) == TaskKind.OPERATION and not meta:
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="operação sem metadata"),
            )
            return {"action": "blocked_no_metadata", "task_id": str(task.id)}

        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        return {"action": "skipped_to_verify", "task_id": str(task.id)}

    def _ensure_final_message(self, root: TaskModel) -> None:
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
        from agent.orchestrator.closing import compose_final_markdown

        stages = [
            {"title": child.title, "status": child.status, "sources": []}
            for child in children_of(self._session, root.id)
        ]
        report["final_answer"] = compose_final_markdown(objective=root.objective or root.title, stages=stages)
        root.consolidated_result_json = report

    def _work_root(self, project: ProjectModel, task: TaskModel | None) -> str:
        conversation = None
        if task is not None and task.conversation_id:
            conversation = self._session.get(ConversationModel, task.conversation_id)
        return effective_root(project, conversation)

    async def _write_final_answer(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        config: dict,
    ) -> dict[str, Any]:
        from agent.guides.discover import capability_line
        from agent.orchestrator.closing import (
            compose_final_markdown,
            extract_sources,
            local_now_line,
            usable_reply,
        )
        from agent.providers.base import ChatCompletionRequest, ChatMessage

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
        provider = _select_provider(self._settings, config)
        profile = _profile_from_config(config, self._settings)
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
            self._note_thought(run, task, "Escrevendo a resposta final.")
            resp = await provider.chat(
                ChatCompletionRequest(
                    messages=[ChatMessage(role="user", content=prompt)],
                    profile=profile,
                )
            )
            model_text = (resp.content or "").strip()
        except Exception:
            model_text = ""
        markdown = model_text if usable_reply(model_text) else compose_final_markdown(
            objective=objective,
            stages=stages,
            model_text=model_text,
        )
        sources = extract_sources(markdown, *[str(stage.get("sources")) for stage in stages])
        task.consolidated_result_json = {"final_answer": True, "markdown": markdown, "sources": sources}
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
        if task.parent_id:
            consolidate_parent(self._session, task.parent_id)
        return {"action": "final_answer", "task_id": str(task.id), "thought": markdown[:280]}

    async def _finalize_verification(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
        work_root: str | None = None,
    ) -> dict[str, Any]:
        root_path = work_root or self._work_root(project, task)
        meta = task.metadata_json or {}
        spec = meta.get("verification")
        if not spec:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            consolidate_parent(self._session, task.parent_id) if task.parent_id else None
            return {"action": "completed_without_verification", "task_id": str(task.id)}

        config = self._run_config(run)
        approved = bool(config.get("approve_risky_tools"))
        vresult = await run_verification(
            project_root=root_path,
            spec=spec,
            approved=approved,
        )
        self._session.add(
            EvidenceModel(
                task_id=task.id,
                verifier=vresult.verifier,
                passed=vresult.passed,
                summary=vresult.summary,
                detail_json=vresult.detail,
            )
        )
        self._attempts.record(
            run_id=run.id,
            task_id=task.id,
            kind=AttemptKind.VERIFICATION,
            provider=vresult.verifier,
            request=spec,
            response={"passed": vresult.passed, "summary": vresult.summary},
            success=bool(vresult.passed),
            project_id=project.id,
        )

        if vresult.passed is True:
            task.consolidated_result_json = {
                "verified": True,
                "summary": vresult.summary,
            }
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            if task.parent_id:
                parent = self._tasks.get_task(task.parent_id)
                kids = children_of(self._session, parent.id)
                if kids and all(k.status == TaskStatus.COMPLETED.value for k in kids):
                    consolidate_parent(self._session, parent.id)
            return {"action": "verified_ok", "task_id": str(task.id)}

        if vresult.passed is False:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "verify_failed", "task_id": str(task.id)}

        self._tasks.update_status(
            task.id,
            TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="verificação inconclusiva"),
        )
        return {"action": "verify_inconclusive", "task_id": str(task.id)}
