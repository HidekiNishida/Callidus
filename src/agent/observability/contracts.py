"""
Arquivo: src/agent/observability/contracts.py
Nome: contracts.py
Propósito: definir o contrato tipado dos eventos de execução e o envelope único de entrega.
Responsabilidade: camada de aplicação — catálogo de eventos, validação de payload e normalização do envelope.
Componentes: SCHEMA_VERSION, EventSpec, EVENT_SPECS, LEGACY_TYPES, EPHEMERAL_TYPES, UnknownEventType, InvalidEventPayload, EventEnvelope, spec_for, validate_payload, as_utc, envelope_from_row.
Dependências: pydantic, dataclasses.
Observações: o envelope é contrato público da API e do SSE; mudar seu formato quebra os assinantes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class UnknownEventType(ValueError):
    """Tipo de evento fora do catálogo tipado."""


class InvalidEventPayload(ValueError):
    """Payload de evento que não satisfaz o contrato do tipo."""


@dataclass(frozen=True)
class EventSpec:
    """Especificação de um tipo de evento: categoria, persistência e campos obrigatórios.

    Atributos:
        type: identificador completo do evento (ex.: `task.completed`).
        category: prefixo do tipo, usado para agrupar eventos.
        persist: quando `False`, o evento só existe em memória (fragmentos).
        required: chaves obrigatórias do payload.
        description: descrição curta do significado do evento.
    """

    type: str
    category: str
    persist: bool = True
    required: tuple[str, ...] = ()
    description: str = ""


def _spec(type_: str, required: tuple[str, ...] = (), *, persist: bool = True, description: str = "") -> EventSpec:
    """Cria a especificação de um evento, deduzindo a categoria pelo prefixo do tipo.

    Args:
        type_: identificador completo do evento.
        required: chaves obrigatórias do payload.
        persist: quando `False`, o evento é efêmero (não vai para o banco).
        description: descrição curta do evento.

    Returns:
        A `EventSpec` correspondente.
    """
    return EventSpec(type_, type_.split(".", 1)[0], persist, required, description)


# Fragmentos (`persist=False`) só existem em memória: o fato final correspondente é persistido
# (`agent.output.completed`, `command.completed`, `tool.completed`).
EVENT_SPECS: dict[str, EventSpec] = {
    s.type: s
    for s in (
        _spec("run.started", description="execução iniciada"),
        _spec("run.progress", ("state",), description="estado de progresso mudou"),
        _spec("run.completed", description="execução concluída com aceite"),
        _spec("run.failed", ("reason",), description="execução encerrada sem concluir"),
        _spec("run.cancelled", description="execução cancelada"),
        _spec("run.paused", description="execução pausada com diagnóstico"),
        _spec("run.resumed", description="execução retomada"),
        _spec("plan.started", description="decomposição de uma tarefa começou"),
        _spec("plan.updated", ("tasks",), description="subtarefas criadas a partir do plano"),
        _spec("task.created", description="tarefa criada"),
        _spec("task.started", ("from", "to"), description="tarefa passou a executar"),
        _spec("task.progress", ("from", "to"), description="tarefa mudou de etapa"),
        _spec("task.blocked", ("from", "to"), description="tarefa bloqueada"),
        _spec("task.replanned", ("reason",), description="tarefa replanejada"),
        _spec("task.completed", ("from", "to"), description="tarefa concluída"),
        _spec("task.failed", ("from", "to"), description="tarefa falhou"),
        _spec("task.cancelled", ("from", "to"), description="tarefa cancelada"),
        _spec("agent.started", ("output_id", "provider", "model", "streaming"), description="chamada ao modelo"),
        _spec("agent.status", ("output_id", "status"), persist=False, description="estado da chamada"),
        _spec("agent.output.delta", ("output_id", "text", "offset"), persist=False, description="fragmento"),
        _spec("agent.output.completed", ("output_id", "content"), description="resposta final"),
        _spec("agent.output.failed", ("output_id", "error"), description="chamada ao modelo falhou"),
        _spec("agent.narration.started", ("narration_id", "output_id"), description="o agente começou a falar com a pessoa"),
        _spec(
            "agent.narration.delta",
            ("narration_id", "text", "offset"),
            persist=False,
            description="trecho novo da narração, na ordem em que o modelo gerou",
        ),
        _spec(
            "agent.narration.completed",
            ("narration_id", "content", "status"),
            description="narração encerrada (concluída, interrompida ou com falha) com o texto recebido",
        ),
        _spec("tool.started", ("call_id", "tool"), description="ferramenta iniciada"),
        _spec("tool.output", ("call_id", "text"), persist=False, description="saída parcial"),
        _spec("tool.completed", ("call_id", "tool"), description="ferramenta concluída"),
        _spec("tool.failed", ("call_id", "tool", "error"), description="ferramenta falhou"),
        _spec("model.tool_call", ("tool",), description="o modelo pediu uma ferramenta durante a operação"),
        _spec("command.started", ("call_id", "command"), description="comando iniciado"),
        _spec("command.output", ("call_id", "stream", "text"), persist=False, description="saída parcial"),
        _spec("command.completed", ("call_id", "exit_code"), description="comando terminou com código 0"),
        _spec("command.failed", ("call_id", "error"), description="comando falhou ou expirou"),
        # `launch_app` emitia este tipo fora do catálogo: dentro de um run o emissor recusava o
        # evento e o passo caía com exceção.
        _spec("app.launched", ("app",), description="aplicativo aberto"),
        _spec("file.read", ("path",), description="arquivo lido"),
        _spec("file.created", ("path",), description="arquivo criado"),
        _spec("file.changed", ("path",), description="arquivo alterado"),
        _spec("file.deleted", ("path",), description="arquivo removido"),
        _spec("test.started", ("call_id",), description="testes iniciados"),
        _spec("test.output", ("call_id", "text"), persist=False, description="saída parcial"),
        _spec("test.completed", ("call_id",), description="testes passaram"),
        _spec("test.failed", ("call_id",), description="testes falharam"),
        _spec("verification.started", ("verifier",), description="verificação iniciada"),
        _spec("verification.passed", ("verifier",), description="verificação aprovada"),
        _spec("verification.failed", ("verifier",), description="verificação reprovada"),
        _spec("verification.inconclusive", ("verifier",), description="verificação sem veredito (nunca aprova)"),
        _spec("strategy.formulated", description="abordagem profissional formulada"),
        _spec("skill.selected", description="skills selecionadas para a tarefa"),
        _spec("automation.chat_tool", ("tool", "success"), description="ferramenta de automação chamada pela conversa"),
        _spec("automation.chat_result", ("action",), description="desfecho da operação de automação pedida na conversa"),
        _spec("decomposition.recursive", ("depth", "source"), description="decomposição recursiva da etapa interna"),
        _spec("work.explained", ("category", "text"), description="explicação fiel de uma decisão ou resultado"),
        _spec("budget.pressure", ("level", "purpose"), description="o consumo da execução entrou na faixa de redução"),
        _spec("budget.granted", ("tokens", "reason"), description="autorização explícita de mais tokens para a execução"),
        _spec("verification.recovery_planned", ("cause", "action"), description="recuperação da verificação planejada"),
        _spec(
            "verification.alternative",
            ("verifier", "primary_verifier", "passed"),
            description="verificador alternativo rodou depois que o principal reprovou",
        ),
        _spec(
            "verification.skipped",
            ("reason",),
            description="etapa concluída sem verificador automático; a limitação fica registrada, não vira aprovação",
        ),
        _spec("approval.requested", ("approval_id", "tool"), description="operação arriscada aguarda aprovação"),
        _spec("approval.decided", ("approval_id", "status"), description="aprovação concedida ou negada para uma operação"),
        _spec(
            "context.history_compacted",
            ("purpose", "results"),
            description="resultados antigos do ciclo de ferramentas resumidos para a conversa caber na janela do modelo",
        ),
        # Telemetria de transições do orquestrador (etapa do ciclo).
        _spec("orchestrator.step.started", description="início de um passo do orquestrador"),
        _spec(
            "orchestrator.step.completed",
            ("action", "duration_ms"),
            description="término de um passo do orquestrador com a ação executada",
        ),
        # Transição de estado de tarefa (distinta de task.started/task.completed).
        _spec(
            "task.state.transitioned",
            ("from", "to", "reason"),
            description="mudança de estado de uma tarefa com motivo",
        ),
        # Compactação de contexto com antes/depois de tokens.
        _spec(
            "context.compacted",
            ("before_tokens", "after_tokens", "purpose"),
            description="compactação do contexto com redução de tokens",
        ),
        # Recuperação de memória e skills selecionadas.
        _spec(
            "memory.recovered",
            ("skills", "sources", "tokens"),
            description="informações recuperadas da memória e skills para o contexto",
        ),
        # Amostra de consumo de recursos do hardware.
        _spec(
            "resources.sampled",
            ("cpu_percent", "ram_mb", "vram_mb"),
            description="amostra de consumo de CPU, RAM e VRAM",
        ),
        # Tentativa de verificação (distinta de verification.passed/failed).
        _spec(
            "verification.attempt.started",
            ("verifier",),
            description="início de uma tentativa de verificação",
        ),
        _spec(
            "verification.attempt.completed",
            ("verifier", "passed", "duration_ms"),
            description="término de uma tentativa de verificação com resultado",
        ),
        # Chamada ao provedor com métricas detalhadas (distinta de agent.*).
        _spec(
            "provider.inference.started",
            ("provider", "model", "purpose"),
            description="início de uma chamada ao provedor de inferência",
        ),
        _spec(
            "provider.inference.completed",
            ("provider", "model", "duration_ms", "prompt_tokens", "completion_tokens"),
            description="término de uma chamada ao provedor com métricas de tokens",
        ),
    )
}

# Tipos gravados antes do contrato tipado; continuam aceitos e recebem `seq`, mas não têm validação de campos.
LEGACY_TYPES: frozenset[str] = frozenset(
    {
        "orchestrator.action",
        "orchestrator.step",
        "agent.thought",
        "attempt.recorded",
        "plan.validated",
        "run.stagnation",
        "task.dependency_added",
        "task.status_changed",
    }
)

EPHEMERAL_TYPES: frozenset[str] = frozenset(t for t, s in EVENT_SPECS.items() if not s.persist)


def spec_for(event_type: str) -> EventSpec:
    """Especificação de um tipo de evento.

    Args:
        event_type: identificador do evento procurado no catálogo.

    Returns:
        A `EventSpec` correspondente.

    Raises:
        UnknownEventType: quando o tipo não existe no catálogo tipado.
    """
    spec = EVENT_SPECS.get(event_type)
    if spec is None:
        raise UnknownEventType(event_type)
    return spec


def validate_payload(event_type: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """Valida o payload de um evento contra o contrato do seu tipo.

    Args:
        event_type: identificador do evento.
        data: payload a validar; `None` é tratado como payload vazio.

    Returns:
        Uma cópia do payload validado.

    Raises:
        UnknownEventType: quando o tipo não existe no catálogo tipado.
        InvalidEventPayload: quando faltam campos obrigatórios ou o payload não é serializável.
    """
    spec = spec_for(event_type)
    data = dict(data or {})
    missing = [k for k in spec.required if k not in data]
    if missing:
        raise InvalidEventPayload(f"{event_type}: faltam {', '.join(missing)}")
    try:
        json.dumps(data, default=str)
    except (TypeError, ValueError) as exc:
        raise InvalidEventPayload(f"{event_type}: payload não serializável ({exc})") from exc
    return data


class EventEnvelope(BaseModel):
    """Formato único entregue à API, ao SSE e à interface."""

    id: str
    run_id: str
    project_id: str | None = None
    task_id: str | None = None
    parent_task_id: str | None = None
    agent: str | None = None
    type: str
    seq: int
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)
    persisted: bool = True
    schema_version: int = SCHEMA_VERSION


def _s(value: Any) -> str | None:
    """Converte um identificador para texto, preservando `None`."""
    return None if value is None else str(value)


def as_utc(value: datetime | None) -> datetime | None:
    """O SQLite devolve datas sem fuso; elas foram gravadas em UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def envelope_from_row(row: Any) -> dict[str, Any]:
    """Converte uma linha de `event_logs` no envelope entregue ao cliente.

    Args:
        row: linha do modelo de evento persistido.

    Returns:
        O envelope em forma de dicionário serializável.
    """
    return EventEnvelope(
        id=str(row.id),
        run_id=str(row.run_id),
        project_id=_s(row.project_id),
        task_id=_s(row.task_id),
        parent_task_id=_s(row.parent_task_id),
        agent=row.agent,
        type=row.event_type,
        seq=row.seq or 0,
        ts=as_utc(row.created_at),
        data=row.payload_json or {},
        persisted=True,
        schema_version=row.schema_version or SCHEMA_VERSION,
    ).model_dump(mode="json")
