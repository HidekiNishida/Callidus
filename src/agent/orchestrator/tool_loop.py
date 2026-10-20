# src/agent/orchestrator/tool_loop.py — operação do modelo com inspeção por ferramentas
"""Ciclo de operação em que o modelo inspeciona o projeto antes de responder.

Por que existe: modelos treinados para ferramentas (o `gpt-oss:20b` é um deles) respondem a uma
tarefa de programação chamando ferramentas de leitura — `read_file`, `list_dir`. Quando o pedido
chega sem ferramentas declaradas, o servidor devolve `content` vazio (o modelo pediu a ferramenta e
não havia para onde pedir). O Callidus tratava isso como "resposta vazia", repetia o mesmo pedido e
parava em estagnação: a falha não era do modelo, era do contrato.

O ciclo aqui é explícito e limitado: o modelo recebe as ferramentas de **inspeção**, chama o que
precisa, recebe o resultado e só então devolve a alteração no formato JSON já existente. A escrita
continua passando pelo caminho único do agente (JSON → `edit_file`/`write_file` → verificação), o
que mantém uma só origem para a mutação do disco.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent.providers.base import ChatCompletionRequest, ChatMessage, LLMProvider, ModelProfile
from agent.tools.registry import ToolContext, ToolRegistry

# Ferramentas de leitura oferecidas durante a operação.
INSPECTION_TOOLS: tuple[str, ...] = (
    "list_dir",
    "glob_files",
    "read_file",
    "search_grep",
    "git_status",
    "git_diff",
)

# Ferramentas que mudam o disco. Continuam passando pelo registro de ferramentas (mesma
# validação de caminho, aprovação e diff do caminho JSON), mas o gatilho é o modelo chamando
# a ferramenta — é assim que um modelo como o `gpt-oss:20b` espera trabalhar.
MUTATION_TOOLS: tuple[str, ...] = ("edit_file", "write_file")

OPERATION_TOOLS: tuple[str, ...] = INSPECTION_TOOLS + MUTATION_TOOLS

_TYPE_BY_KIND = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "list": "array",
    "array": "array",
    "dict": "object",
    "object": "object",
}

_RESULT_CHARS = 2000


@dataclass
class ToolLoopOutcome:
    """Resultado do ciclo: o que o modelo respondeu e o que ele pediu no caminho."""

    content: str = ""
    iterations: int = 0
    # `final`: o modelo respondeu (com ou sem JSON). `max_iterations`: gastou o ciclo sem responder.
    # `no_output`: respondeu vazio.
    stop_reason: str = "final"
    reasoning: str = ""
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    # Alteração já aplicada pelo modelo durante o ciclo (quando ele chamou write_file/edit_file).
    applied_tool: str | None = None
    applied_args: dict[str, Any] = field(default_factory=dict)
    applied_result: dict[str, Any] = field(default_factory=dict)

    @property
    def asked_tools(self) -> list[str]:
        return [str(item.get("tool")) for item in self.tool_log]

    @property
    def applied(self) -> bool:
        return bool(self.applied_tool and self.applied_result.get("success"))


def json_schema_for(spec) -> dict[str, Any]:
    """Traduz o `input_schema` da ferramenta (forma simplificada do Callidus) para JSON Schema."""
    raw = spec.input_schema or {}
    if raw.get("type") == "object" and isinstance(raw.get("properties"), dict):
        return raw
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, kind in raw.items():
        optional = isinstance(kind, str) and kind.endswith("?")
        base = kind[:-1] if isinstance(kind, str) and optional else kind
        properties[name] = {"type": _TYPE_BY_KIND.get(str(base), "string")}
        if not optional:
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def tool_schemas(registry: ToolRegistry, tool_ids: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """Esquemas no formato de função (OpenAI/Ollama) para as ferramentas pedidas."""
    schemas: list[dict[str, Any]] = []
    for tool_id in tool_ids:
        try:
            spec = registry.get_spec(tool_id)
        except KeyError:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": spec.id,
                    "description": spec.description,
                    "parameters": json_schema_for(spec),
                },
            }
        )
    return schemas


def tool_result_text(result: dict[str, Any], limit: int = _RESULT_CHARS) -> str:
    """Resultado da ferramenta como texto para o modelo (curto e sem metadados internos)."""
    if not isinstance(result, dict):
        return str(result)[:limit]
    if result.get("success"):
        body = result.get("content")
        if not isinstance(body, str):
            body = result.get("summary") or result.get("stdout")
        if not isinstance(body, str):
            import json

            body = json.dumps(result, ensure_ascii=False, default=str)
    else:
        body = str(result.get("error") or result.get("stderr") or "falhou")
    body = body.strip()
    if len(body) > limit:
        body = body[:limit] + f"\n… (resultado com {len(body)} caracteres; leia o arquivo para o resto)"
    return body or "(vazio)"


async def run_tool_loop(
    *,
    provider: LLMProvider,
    messages: list[ChatMessage],
    profile: ModelProfile,
    registry: ToolRegistry,
    ctx: ToolContext,
    approved: bool = False,
    tool_ids: tuple[str, ...] | list[str] = OPERATION_TOOLS,
    max_iterations: int = 6,
    max_tool_calls: int = 12,
    final_tools: tuple[str, ...] | list[str] | None = None,
    final_tools_after: tuple[str, ...] | list[str] | None = None,
    final_instruction: str = (
        "Você já inspecionou o que era preciso. Faça a alteração agora "
        "(use write_file ou edit_file) e pare. Se não houver o que alterar, "
        "responda com o resumo do que já está feito."
    ),
    final_instruction_after: str = "",
    purpose: str = "operation",
    stream: bool = True,
    chat: Callable[..., Awaitable[Any]] | None = None,
    on_tool_call: Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]] | None = None,
) -> ToolLoopOutcome:
    """Chama o modelo em ciclo: ele pede ferramentas, o agente as executa, o modelo prossegue.

    O orçamento é duplo: rodadas (`max_iterations`) e chamadas de ferramenta (`max_tool_calls`).
    Um modelo que pede muitas leituras por rodada esgota o ciclo sem decidir; o orçamento de
    chamadas é o que fecha essa porta.
    """
    from agent.providers.observed import observed_chat

    call = chat or observed_chat
    schemas = tool_schemas(registry, tool_ids)
    mutations = {name for name in tool_ids if name in MUTATION_TOOLS}
    final_names = list(final_tools) if final_tools is not None else [name for name in tool_ids if name in mutations]
    final_schemas = tool_schemas(registry, final_names)
    after_names = list(final_tools_after) if final_tools_after is not None else final_names
    final_after_schemas = tool_schemas(registry, after_names)
    history = list(messages)
    log: list[dict[str, Any]] = []
    seen: set[str] = set()
    reasoning = ""
    limit = max(1, max_iterations)
    call_budget = max(1, max_tool_calls)

    async def _execute(call_item) -> tuple[dict[str, Any], dict[str, Any]]:
        args = call_item.arguments if isinstance(call_item.arguments, dict) else {}
        try:
            result = await registry.execute(call_item.name, ctx, args, approved=approved)
        except Exception as exc:  # a ferramenta quebrou: o modelo precisa saber, o ciclo continua
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        entry = {
            "tool": call_item.name,
            "args": args,
            "success": bool(result.get("success")),
            "summary": tool_result_text(result, limit=400),
            # Conteúdo da leitura (até 1200 caracteres): é o que permite à próxima tentativa
            # continuar de onde esta parou, em vez de reler os mesmos arquivos.
            "content": tool_result_text(result, limit=1200) if call_item.name == "read_file" else "",
        }
        log.append(entry)
        if on_tool_call is not None:
            await on_tool_call(entry, result)
        return entry, result

    def _budget_note() -> str:
        restantes = call_budget - len(log)
        if restantes <= 0:
            return ""
        return f"\n(restam {restantes} leituras; depois disso, faça a alteração.)"

    for iteration in range(1, limit + 1):
        request = ChatCompletionRequest(messages=history, profile=profile, tools=schemas or None)
        response = await call(provider, request, purpose=purpose, stream=stream)
        reasoning = getattr(response, "reasoning", None) or reasoning
        calls = list(getattr(response, "tool_calls", None) or [])
        if not calls:
            return ToolLoopOutcome(
                content=response.content or "",
                iterations=iteration,
                stop_reason="final",
                reasoning=reasoning,
                tool_log=log,
            )
        history.append(
            ChatMessage(
                role="assistant",
                content=response.content or "",
                tool_calls=[item.model_dump() for item in calls],
            )
        )
        for call_item in calls:
            if len(log) >= call_budget:
                break
            entry, result = await _execute(call_item)
            if entry["tool"] in mutations and entry["success"]:
                # A alteração foi aplicada pelo modelo: o ciclo termina aqui e a etapa vai
                # para a verificação (mesmo caminho de evidência do JSON).
                return ToolLoopOutcome(
                    content=response.content or "",
                    iterations=iteration,
                    stop_reason="applied",
                    reasoning=reasoning,
                    tool_log=log,
                    applied_tool=entry["tool"],
                    applied_args=entry["args"],
                    applied_result=result,
                )
            body = tool_result_text(result)
            key = f"{call_item.name}:{sorted(entry['args'].items())}"
            if key in seen:
                # Repetir a mesma consulta não traz informação nova: o modelo precisa do próximo passo.
                body = f"{body}\n(você já consultou isto; use a informação que já tem.)"
            seen.add(key)
            history.append(
                ChatMessage(
                    role="tool",
                    content=body + _budget_note(),
                    tool_call_id=call_item.id,
                )
            )
    # O orçamento de inspeção acabou: a fase final. A primeira chamada oferece as ferramentas
    # de fecho (`final_tools`); se o modelo ainda pedir ferramenta, a leitura é atendida e há
    # mais uma chamada, agora com `final_tools_after` (no plano, sem ferramenta nenhuma: o
    # modelo precisa entregar o JSON).
    history.append(ChatMessage(role="user", content=final_instruction))
    final = await call(
        provider,
        ChatCompletionRequest(messages=history, profile=profile, tools=final_schemas or None),
        purpose=purpose,
        stream=stream,
    )
    reasoning = getattr(final, "reasoning", None) or reasoning
    final_calls = list(getattr(final, "tool_calls", None) or [])
    if not final_calls:
        return ToolLoopOutcome(
            content=final.content or "",
            iterations=limit + 1,
            stop_reason="final",
            reasoning=reasoning,
            tool_log=log,
        )
    history.append(
        ChatMessage(
            role="assistant",
            content=final.content or "",
            tool_calls=[item.model_dump() for item in final_calls],
        )
    )
    applied = None
    for call_item in final_calls:
        entry, result = await _execute(call_item)
        if entry["tool"] in mutations and entry["success"]:
            applied = (entry, result)
            break
    if applied is not None:
        entry, result = applied
        return ToolLoopOutcome(
            content=final.content or "",
            iterations=limit + 1,
            stop_reason="applied",
            reasoning=reasoning,
            tool_log=log,
            applied_tool=entry["tool"],
            applied_args=entry["args"],
            applied_result=result,
        )
    if not final_tools_after:
        return ToolLoopOutcome(
            content="",
            iterations=limit + 1,
            stop_reason="max_iterations",
            reasoning=reasoning,
            tool_log=log,
        )
    history.append(
        ChatMessage(
            role="user",
            content=final_instruction_after
            or "Agora responda. Não peça mais ferramentas: entregue a resposta no formato pedido.",
        )
    )
    last = await call(
        provider,
        ChatCompletionRequest(messages=history, profile=profile, tools=final_after_schemas or None),
        purpose=purpose,
        stream=stream,
    )
    reasoning = getattr(last, "reasoning", None) or reasoning
    last_calls = list(getattr(last, "tool_calls", None) or [])
    if not last_calls:
        return ToolLoopOutcome(
            content=last.content or "",
            iterations=limit + 2,
            stop_reason="final",
            reasoning=reasoning,
            tool_log=log,
        )
    history.append(
        ChatMessage(
            role="assistant",
            content=last.content or "",
            tool_calls=[item.model_dump() for item in last_calls],
        )
    )
    for call_item in last_calls:
        entry, result = await _execute(call_item)
        if entry["tool"] in mutations and entry["success"]:
            return ToolLoopOutcome(
                content=last.content or "",
                iterations=limit + 2,
                stop_reason="applied",
                reasoning=reasoning,
                tool_log=log,
                applied_tool=entry["tool"],
                applied_args=entry["args"],
                applied_result=result,
            )
    return ToolLoopOutcome(
        content="",
        iterations=limit + 2,
        stop_reason="max_iterations",
        reasoning=reasoning,
        tool_log=log,
    )
