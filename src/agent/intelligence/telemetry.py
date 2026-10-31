"""
Arquivo: src/agent/intelligence/telemetry.py
Nome: telemetry.py
Propósito: serviço de telemetria centralizada com contrato tipado e versionado para eventos de execução.
Responsabilidade: camada de aplicação — grava eventos de telemetria (orquestrador, provedores, contexto, ferramentas, verificação, recursos) com correlação consistente entre run, tarefa, tentativa e evento pai.
Componentes: TelemetryService.
Dependências: agent.observability (emit, observe, current, EventEnvelope, EVENT_SPECS, SCHEMA_VERSION), agent.persistence.models (EventLogModel), sqlalchemy, uuid, datetime.
Observações: falhas de telemetria nunca bloqueiam a execução; eventos sensíveis são sanitizados pelo emissor existente.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.observability import (
    EVENT_SPECS,
    SCHEMA_VERSION,
    EventEnvelope,
    emit,
    current,
)
from agent.persistence.models import EventLogModel

TELEMETRY_SCHEMA_VERSION = 2


@dataclass
class TelemetryEvent:
    """Evento de telemetria com campos de correlação e metadados de qualidade.

    Atributos:
        event_type: tipo do evento (ex.: `orchestrator.step.started`).
        data: payload do evento.
        run_id: identificador da run (obrigatório para telemetria persistida).
        task_id: identificador da tarefa, quando aplicável.
        attempt_id: identificador da tentativa, quando aplicável.
        parent_event_id: identificador do evento pai na cadeia de correlação.
        component: componente emissor (orchestrator, provider, context, tool, verification, resources).
        operation: operação executada pelo componente.
        status: status da operação (started, completed, failed, skipped, retrying, blocked).
        duration_ms: duração da operação em milissegundos.
        measurement_quality: origem do dado (provider_reported, locally_counted, estimated, unavailable).
        commit: quando `True`, persiste no banco além de publicar no barramento.
    """

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    attempt_id: uuid.UUID | None = None
    parent_event_id: uuid.UUID | None = None
    component: str = "orchestrator"
    operation: str = ""
    status: str = "started"
    duration_ms: int | None = None
    measurement_quality: str = "unavailable"
    commit: bool = True

    def to_emit_data(self) -> dict[str, Any]:
        """Converte o evento no dicionário de dados para `emit`."""
        data = dict(self.data)
        data.update(
            {
                "component": self.component,
                "operation": self.operation,
                "status": self.status,
                "schema_version": TELEMETRY_SCHEMA_VERSION,
            }
        )
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.measurement_quality:
            data["measurement_quality"] = self.measurement_quality
        if self.attempt_id is not None:
            data["attempt_id"] = str(self.attempt_id)
        if self.parent_event_id is not None:
            data["parent_event_id"] = str(self.parent_event_id)
        return data


class TelemetryService:
    """Serviço de telemetria centralizada.

    Atributos:
        session: sessão SQLAlchemy para persistência de eventos.
        _current_event_id: identificador do último evento emitido neste contexto (para correlação).
    """

    def __init__(self, session: Any) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada para persistir eventos de telemetria.
        """
        self._session = session
        self._current_event_id: uuid.UUID | None = None

    def _emit_telemetry(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        task_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        component: str = "orchestrator",
        operation: str = "",
        status: str = "started",
        duration_ms: int | None = None,
        measurement_quality: str = "unavailable",
        parent_event_id: uuid.UUID | None = None,
        attempt_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> Any:
        """Emite um evento de telemetria através do emissor existente.

        Args:
            event_type: tipo do evento.
            data: payload adicional.
            task_id: tarefa associada (sobrescreve o contexto atual).
            run_id: run associada (sobrescreve o contexto atual).
            component: componente emissor.
            operation: operação executada.
            status: status da operação.
            duration_ms: duração em milissegundos.
            measurement_quality: origem do dado.
            parent_event_id: evento pai para correlação.
            attempt_id: tentativa associada.
            commit: quando `True`, persiste no banco.

        Returns:
            O resultado de `emit` (linha do banco ou envelope em memória).
        """
        obs = current()
        effective_run_id = run_id if run_id is not None else (obs.run_id if obs else None)
        effective_task_id = task_id if task_id is not None else (obs.task_id if obs else None)
        effective_parent = parent_event_id or self._current_event_id

        event = TelemetryEvent(
            event_type=event_type,
            data=data or {},
            run_id=effective_run_id,
            task_id=effective_task_id,
            attempt_id=attempt_id,
            parent_event_id=effective_parent,
            component=component,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            measurement_quality=measurement_quality,
            commit=commit,
        )

        try:
            result = emit(
                event_type,
                event.to_emit_data(),
                task_id=effective_task_id,
                commit=commit,
            )
        except Exception:
            # Telemetria nunca bloqueia a execução.
            return None

        # Quando não há contexto de observação (fora de uma run), `emit` não persiste.
        # Gravamos diretamente o EventLogModel para não perder o evento.
        if result is None and commit and effective_run_id is not None:
            from agent.persistence.models import EventLogModel
            from datetime import UTC, datetime
            row = EventLogModel(
                project_id=None,
                run_id=effective_run_id,
                task_id=effective_task_id,
                event_type=event_type,
                payload_json=event.to_emit_data(),
                agent=component,
            )
            try:
                self._session.add(row)
                self._session.flush()
                if hasattr(row, "id"):
                    self._current_event_id = row.id
                result = row
            except Exception:
                return None

        if commit and hasattr(result, "id"):
            self._current_event_id = result.id
        return result

    # ── Orchestrator ──────────────────────────────────────────────────────

    def step_started(
        self,
        *,
        step_index: int,
        run_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o início de um passo do orquestrador."""
        return self._emit_telemetry(
            "orchestrator.step.started",
            {"step_index": step_index},
            component="orchestrator",
            operation="step",
            status="started",
            parent_event_id=parent_event_id,
        )

    def step_completed(
        self,
        *,
        step_index: int,
        action: str,
        duration_ms: int,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o término de um passo do orquestrador."""
        return self._emit_telemetry(
            "orchestrator.step.completed",
            {"step_index": step_index, "action": action, "duration_ms": duration_ms},
            component="orchestrator",
            operation="step",
            status="completed",
            duration_ms=duration_ms,
            parent_event_id=parent_event_id,
        )

    def state_transitioned(
        self,
        *,
        task_id: uuid.UUID,
        from_status: str,
        to_status: str,
        reason: str | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra uma transição de estado de tarefa."""
        return self._emit_telemetry(
            "task.state.transitioned",
            {"from": from_status, "to": to_status, "reason": reason or ""},
            task_id=task_id,
            component="orchestrator",
            operation="state_transition",
            status="completed",
            parent_event_id=parent_event_id,
        )

    # ── Context ───────────────────────────────────────────────────────────

    def context_compacted(
        self,
        *,
        before_tokens: int,
        after_tokens: int,
        purpose: str,
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra uma compactação de contexto com antes/depois de tokens."""
        return self._emit_telemetry(
            "context.compacted",
            {
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "purpose": purpose,
                "tokens_removed": max(0, before_tokens - after_tokens),
            },
            task_id=task_id,
            component="context",
            operation="compact",
            status="completed",
            parent_event_id=parent_event_id,
        )

    def memory_recovered(
        self,
        *,
        skills: list[str] | None = None,
        sources: list[str] | None = None,
        tokens: int | None = None,
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra recuperação de memória e skills selecionadas."""
        return self._emit_telemetry(
            "memory.recovered",
            {
                "skills": skills or [],
                "sources": sources or [],
                "tokens": tokens,
            },
            task_id=task_id,
            component="context",
            operation="recover",
            status="completed",
            parent_event_id=parent_event_id,
        )

    # ── Provider ──────────────────────────────────────────────────────────

    def provider_inference_started(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o início de uma chamada ao provedor de inferência."""
        return self._emit_telemetry(
            "provider.inference.started",
            {"provider": provider, "model": model, "purpose": purpose},
            task_id=task_id,
            component="provider",
            operation="inference",
            status="started",
            parent_event_id=parent_event_id,
        )

    def provider_inference_completed(
        self,
        *,
        provider: str,
        model: str,
        duration_ms: int,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        measurement_quality: str = "unavailable",
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o término de uma chamada ao provedor com métricas de tokens."""
        return self._emit_telemetry(
            "provider.inference.completed",
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            task_id=task_id,
            component="provider",
            operation="inference",
            status="completed",
            duration_ms=duration_ms,
            measurement_quality=measurement_quality,
            parent_event_id=parent_event_id,
        )

    # ── Resources ─────────────────────────────────────────────────────────

    def resources_sampled(
        self,
        *,
        cpu_percent: float | None = None,
        ram_mb: float | None = None,
        vram_mb: float | None = None,
        run_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra uma amostra de consumo de recursos do hardware."""
        return self._emit_telemetry(
            "resources.sampled",
            {
                "cpu_percent": cpu_percent,
                "ram_mb": ram_mb,
                "vram_mb": vram_mb,
            },
            run_id=run_id,
            component="resources",
            operation="sample",
            status="completed",
        )

    # ── Verification ──────────────────────────────────────────────────────

    def verification_attempt_started(
        self,
        *,
        verifier: str,
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o início de uma tentativa de verificação."""
        return self._emit_telemetry(
            "verification.attempt.started",
            {"verifier": verifier},
            task_id=task_id,
            component="verification",
            operation="verify",
            status="started",
            parent_event_id=parent_event_id,
        )

    def verification_attempt_completed(
        self,
        *,
        verifier: str,
        passed: bool | None,
        duration_ms: int,
        task_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
    ) -> Any:
        """Registra o término de uma tentativa de verificação."""
        return self._emit_telemetry(
            "verification.attempt.completed",
            {"verifier": verifier, "passed": passed, "duration_ms": duration_ms},
            task_id=task_id,
            component="verification",
            operation="verify",
            status="completed",
            duration_ms=duration_ms,
            parent_event_id=parent_event_id,
        )
