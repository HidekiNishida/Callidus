# src/agent/orchestrator/runner.py — ciclo completo de execução
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.enums import AttemptKind, RunStatus, TaskKind, TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.orchestrator.consolidation import children_of, consolidate_parent
from agent.orchestrator.atomizer import micro_decompose_operation, should_decompose_further
from agent.orchestrator.decomposition import apply_decomposition, resolve_decomposition_plan
from agent.orchestrator.planner import ensure_canonical_memory_for_objective
from agent.context.operation_builder import OperationContextBuilder
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.persistence.models import (
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    ProjectModel,
    TaskModel,
)
from agent.providers.base import LLMProvider, ModelProfile
from agent.providers.mock import MockProvider
from agent.providers.ollama import OllamaProvider
from agent.services.attempt_service import AttemptService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolContext, build_default_registry
from agent.verification.runner import run_verification


class RunBlockedError(RuntimeError):
    pass


def _select_provider(settings: Settings, run_config: dict) -> LLMProvider:
    name = run_config.get("provider") or settings.default_provider
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url)
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

    async def step(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = self._session.get(ExecutionRunModel, run_id)
        if run is None:
            raise LookupError(str(run_id))
        if run.status in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}:
            return {"action": "run_terminal", "status": run.status}

        project = self._session.get(ProjectModel, run.project_id)
        if project is None:
            raise LookupError("project")

        config = self._run_config(run)
        provider = _select_provider(self._settings, config)
        profile = _profile_from_config(config, self._settings)

        root = self._tasks.get_task(run.root_task_id)
        task = self._pick_next_task(run.root_task_id)
        if task is None:
            if self._all_terminal_under(root.id):
                run.status = RunStatus.COMPLETED.value
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
            if not kids and (meta.get("tool") or meta.get("verification")):
                if self._tasks.dependencies_satisfied(task.id):
                    self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
                    return {"action": "operation_ready", "task_id": str(task.id)}
                return {"action": "operation_wait_deps", "task_id": str(task.id)}
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
                    plan, source = await resolve_decomposition_plan(
                        settings=self._settings,
                        run_config=config,
                        objective=task.objective,
                        project_root=project.root_path,
                        provider=provider
                        if (config.get("provider") or self._settings.default_provider) == "ollama"
                        else None,
                    )
                if plan is None or not plan.subtasks:
                    self._tasks.update_status(
                        task.id,
                        TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="decomposição falhou"),
                    )
                    return {"action": "blocked_decompose", "task_id": str(task.id)}
                apply_decomposition(self._session, project.id, task.id, plan)
                return {
                    "action": "decomposed",
                    "task_id": str(task.id),
                    "count": len(plan.subtasks),
                    "source": source,
                }

            if self._tasks.dependencies_satisfied(task.id):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.READY))
            return {"action": "planning_wait_children", "task_id": str(task.id)}

        promoted = self._tasks.promote_ready_if_dependencies_met(task.id)
        if promoted:
            return {"action": "promoted_ready", "task_id": str(task.id)}

        if status == TaskStatus.READY:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RUNNING))
            status = TaskStatus.RUNNING

        if status == TaskStatus.RUNNING:
            result = await self._execute_task(run, project, task, config)
            return result

        if status == TaskStatus.VERIFYING:
            return await self._finalize_verification(run, project, task)

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
    ) -> dict[str, Any]:
        if self._attempts.attempts_exhausted(task.id):
            self._tasks.update_status(
                task.id,
                TaskStatusUpdate(status=TaskStatus.BLOCKED, reason="limite de tentativas"),
            )
            return {"action": "blocked_attempts", "task_id": str(task.id)}

        meta = task.metadata_json or {}
        ctx = ToolContext(project_root=project.root_path, run_id=str(run.id), task_id=str(task.id))
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
                return await self._finalize_verification(run, project, task)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "mcp_tool", "task_id": str(task.id), "success": False}

        if meta.get("model_operation"):
            provider = _select_provider(self._settings, config)
            profile = _profile_from_config(config, self._settings)
            from agent.providers.base import ChatCompletionRequest
            from agent.util.json_parse import parse_json_object

            builder = OperationContextBuilder(self._session)
            budget, snap = builder.build_for_task(
                project_id=project.id,
                root_path=project.root_path,
                task=task,
                profile=profile,
                run_id=run.id,
            )
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
            data, err = parse_json_object(resp.content)
            if err or not data or "path" not in data:
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
                return {"action": "model_operation_invalid", "task_id": str(task.id), "error": err}
            out = await self._tools.execute(
                "write_file",
                ctx,
                {"path": data["path"], "content": data.get("content", "")},
                approved=approved,
            )
            task.consolidated_result_json = {"model_operation": True, "write": out, "context_snapshot_id": str(snap.id)}
            if out.get("success") and data.get("path"):
                KnowledgeGraphService(self._session).touch_file(project.id, project.root_path, data["path"])
            if out.get("success"):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self._finalize_verification(run, project, task)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "model_operation_failed", "task_id": str(task.id)}

        if meta.get("tool"):
            tool_id = meta["tool"]
            args = meta.get("tool_args") or {}
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
            if out.get("success") and tool_id == "write_file":
                p = args.get("path")
                if isinstance(p, str):
                    KnowledgeGraphService(self._session).touch_file(project.id, project.root_path, p)
            if out.get("success"):
                self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
                return await self._finalize_verification(run, project, task)
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.RETRY_PENDING))
            return {"action": "tool_executed", "task_id": str(task.id), "success": False}

        if meta.get("verification"):
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
            return await self._finalize_verification(run, project, task)

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

    async def _finalize_verification(
        self,
        run: ExecutionRunModel,
        project: ProjectModel,
        task: TaskModel,
    ) -> dict[str, Any]:
        meta = task.metadata_json or {}
        spec = meta.get("verification")
        if not spec:
            self._tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.COMPLETED))
            consolidate_parent(self._session, task.parent_id) if task.parent_id else None
            return {"action": "completed_without_verification", "task_id": str(task.id)}

        config = self._run_config(run)
        approved = bool(config.get("approve_risky_tools"))
        vresult = await run_verification(
            project_root=project.root_path,
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
