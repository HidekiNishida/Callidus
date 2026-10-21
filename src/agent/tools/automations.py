"""
Arquivo: src/agent/tools/automations.py
Nome: automations.py
Propósito: expor ao modelo as operações de automação como ferramentas do chat.
Responsabilidade: camada de apresentação — handlers que traduzem argumentos do modelo em chamadas do serviço de automações.
Componentes: register_all, os handlers `automation_*` e o catálogo de ferramentas.
Dependências: agent.automation.chat_service, agent.tools.registry.
Observações: as ferramentas chamam os serviços do Callidus; o modelo nunca fala com a API HTTP do próprio Callidus.

As tarefas agendadas, pela conversa.

O modelo recebe uma ferramenta por operação, com argumentos tipados e resultado
estruturado. Cada handler chama o `AutomationChatService` — o mesmo serviço que
os contratos do runtime usam — e devolve o estado **real** da automação: o que
foi criado, com que identificador, quando vai rodar e o que ainda falta.

Duas proteções moram aqui, e não no prompt:

- **A criação não ativa.** `automation_create` devolve a definição desabilitada e
  um token de confirmação; `automation_enable` só aceita o token da definição
  apresentada.
- **O teste não dispara.** `automation_test` verifica a prontidão; só executa a
  ação quando o pedido do usuário é explicitamente um teste com efeito real.
"""
from __future__ import annotations

import inspect
from typing import Any

from agent.automation.chat_service import AutomationChatError, AutomationChatService
from agent.tools.contracts import ToolFamily
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec

# Texto que o modelo recebe junto das ferramentas: o que existe e o que cada uma faz.
AUTOMATION_TOOL_CATALOG = (
    "Ferramentas de automação (use exatamente estes ids): "
    "automation_create, automation_list, automation_get, automation_update, "
    "automation_enable, automation_suspend, automation_disable, automation_run_now, "
    "automation_test, automation_history, automation_cancel, automation_delete, "
    "automation_supervisor_status. "
    "automation_create cria a tarefa agendada; ela nasce DESABILITADA e devolve um "
    "confirmation_token. Só chame automation_enable depois que o usuário confirmar, "
    "repassando esse token. "
    "O campo schedule aceita a hora em português (ex.: «todos os dias às 9h», "
    "«toda segunda-feira às 8h30», «amanhã às 14h», «a cada 4 horas»); não escreva cron. "
    "Em automation_create, action_kind é «callidus» (padrão) salvo quando o usuário "
    "pedir para executar um comando — nesse caso, «script» com command. "
    "automation_list e automation_get mostram o que existe; use o id retornado. "
    "automation_run_now executa na hora; automation_test só verifica a prontidão, "
    "a menos que o pedido seja um teste com efeito real. "
    "automation_delete exige confirm=true. "
    "Não invente identificadores: sempre consulte antes."
)


def _service(ctx: ToolContext) -> AutomationChatService:
    """Serviço de automações ligado ao contexto da ferramenta.

    Args:
        ctx: contexto da execução.

    Returns:
        O serviço pronto para uso.

    Raises:
        AutomationChatError: quando a conversa não tem banco nem projeto.
    """
    if ctx.session is None:
        raise AutomationChatError(
            "esta ferramenta precisa de um projeto do Callidus; ela não está disponível "
            "neste contexto"
        )
    return AutomationChatService(
        ctx.session,
        ctx.settings,
        project_id=ctx.project_id,
        conversation_id=ctx.conversation_id,
    )


def _fail(exc: AutomationChatError) -> dict[str, Any]:
    """Transforma um erro de negócio no resultado que o modelo recebe.

    Args:
        exc: erro levantado pelo serviço.

    Returns:
        Dicionário com `success` falso e o detalhe do erro.
    """
    payload: dict[str, Any] = {"success": False, "error": exc.message}
    payload.update(exc.payload)
    return payload


async def _call(ctx: ToolContext, func, *args, **kwargs) -> dict[str, Any]:
    """Executa uma operação do serviço e devolve o resultado no formato da ferramenta.

    Args:
        ctx: contexto da execução.
        func: operação do serviço.
        args: argumentos posicionais.
        kwargs: argumentos nomeados.

    Returns:
        O resultado da operação, com `content` legível pelo modelo.
    """
    try:
        result = func(ctx, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
    except AutomationChatError as exc:
        return _fail(exc)
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    return _with_content(result)


def _with_content(result: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta ao resultado o texto que o modelo lê.

    Args:
        result: resultado do serviço.

    Returns:
        O mesmo resultado, com `content` (texto) e `summary` (uma linha).
    """
    if not isinstance(result, dict):
        return {"success": True, "content": str(result)}
    result["content"] = render_result(result)
    result.setdefault("summary", _one_line(result))
    return result


def _one_line(result: dict[str, Any]) -> str:
    """Resumo de uma linha do resultado.

    Args:
        result: resultado do serviço.

    Returns:
        Uma linha resumindo a operação.
    """
    message = result.get("message")
    if message:
        return str(message)[:200]
    automation = result.get("automation") or {}
    if isinstance(automation, dict) and automation.get("name"):
        return f"{automation.get('name')} ({automation.get('state')})"
    if "count" in result:
        return f"{result.get('count')} automação(ões)"
    return "ok"


def render_result(result: dict[str, Any]) -> str:
    """Texto que o modelo lê: os fatos da operação, sem ruído.

    Args:
        result: resultado do serviço.

    Returns:
        Texto multilinha com o estado real — ou o erro, quando a operação falhou.
    """
    if not isinstance(result, dict):
        return str(result)
    if result.get("success") is False:
        content = str(result.get("error") or "falhou")
        if result.get("field"):
            content = f"{content} (campo: {result['field']})"
        if result.get("question"):
            content = f"{content}\nPergunte ao usuário: {result['question']}"
        if result.get("candidates"):
            items = ", ".join(
                f"`{item.get('id')}` «{item.get('name')}»" for item in result["candidates"]
            )
            content = f"{content}\nCorrespondências: {items}"
        return content
    lines: list[str] = []
    automation = result.get("automation")
    if isinstance(automation, dict):
        lines.append(_render_automation(automation))
    if "automations" in result:
        items = result.get("automations") or []
        lines.append(f"Automações encontradas: {len(items)}")
        for item in items:
            if isinstance(item, dict):
                lines.append(
                    f"- id={item.get('id')} | {item.get('name')} | estado={item.get('state')} | "
                    f"agenda={((item.get('schedule') or {}).get('summary'))} | "
                    f"próximo={item.get('planned_next_run_at_local') or item.get('next_run_at_local')}"
                )
    if "firings" in result:
        firings = result.get("firings") or []
        lines.append(f"Disparos: {len(firings)}")
        for firing in firings:
            if isinstance(firing, dict):
                lines.append(
                    f"- {firing.get('scheduled_for')} | {firing.get('state')} | "
                    f"tentativa {firing.get('attempt')}/{firing.get('max_attempts')} | "
                    f"run={firing.get('run_id')} | erro={firing.get('error') or '—'}"
                )
    if "outcome" in result:
        outcome = result.get("outcome") or {}
        lines.append(
            f"Desfecho da execução: estado={outcome.get('state')} ok={outcome.get('ok')} "
            f"detalhe={outcome.get('detail')}"
        )
    if "readiness" in result:
        readiness = result.get("readiness") or {}
        blocking = readiness.get("blocking") or []
        lines.append(
            "Prontidão: " + ("ok" if readiness.get("ok") else f"bloqueada por {blocking}")
        )
    if "runtime" in result:
        runtime = result.get("runtime") or {}
        lines.append(f"Runtime de automações: {runtime.get('mode')}")
        for limitation in runtime.get("limitations") or []:
            lines.append(f"  * {limitation}")
    if "diagnostics" in result:
        for line in str(result["diagnostics"]).splitlines():
            lines.append(line)
    message = result.get("message")
    if message:
        lines.append(str(message))
    return "\n".join(line for line in lines if line is not None)


def _render_automation(automation: dict[str, Any]) -> str:
    """Texto de uma automação.

    Args:
        automation: resumo da automação.

    Returns:
        Linhas com nome, estado, agenda, ação e próximo disparo.
    """
    schedule = automation.get("schedule") or {}
    action = automation.get("action") or {}
    summary = str(schedule.get("summary") or "")
    timezone = automation.get("timezone")
    if timezone and f"({timezone})" not in summary:
        summary = f"{summary} (fuso {timezone})"
    lines = [
        f"Automação id={automation.get('id')} | nome=«{automation.get('name')}» | "
        f"estado={automation.get('state')}",
        f"Agenda: {summary}",
    ]
    if action.get("kind") == "script":
        lines.append(f"Ação: script {action.get('command') or action.get('script')}")
    else:
        lines.append(f"Ação: tarefa do Callidus — objetivo: {action.get('objective')}")
    lines.append(
        "Próximo disparo previsto: "
        + str(
            automation.get("planned_next_run_at_local")
            or automation.get("next_run_at_local")
            or "—"
        )
    )
    if automation.get("confirmation_token"):
        lines.append(f"confirmation_token: {automation['confirmation_token']}")
    if automation.get("needs_confirmation"):
        lines.append("A automação ainda NÃO está ativa: falta a confirmação do usuário.")
    return "\n".join(lines)


# ------------------------------------------------------------------ handlers


async def _create(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Cria uma automação desabilitada, a partir de um pedido em linguagem natural.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo da automação criada, com a prévia e o token de confirmação.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).create(**kwargs),
        name=str(args.get("name") or ""),
        objective=str(args.get("objective") or ""),
        schedule=_opt_text(args.get("schedule")),
        cron=_opt_text(args.get("cron")),
        run_at=_opt_text(args.get("run_at")),
        interval_seconds=_opt_int(args.get("interval_seconds")),
        action_kind=str(args.get("action_kind") or "callidus"),
        command=_opt_list(args.get("command")),
        script=_opt_text(args.get("script")),
        timezone=_opt_text(args.get("timezone")),
        description=_opt_text(args.get("description")),
        dependencies=_opt_objects(args.get("dependencies")),
        allow_scripts=bool(args.get("allow_scripts")),
        allowed_commands=_opt_list(args.get("allowed_commands")),
        allowed_paths=_opt_list(args.get("allowed_paths")),
        conversation_id=_opt_text(args.get("conversation_id")),
        model_id=_opt_text(args.get("model_id")),
        provider=_opt_text(args.get("provider")),
    )


async def _list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Lista as automações do projeto.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        A lista resumida das automações.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).list(**kwargs),
        state=_opt_text(args.get("state")),
        query=_opt_text(args.get("query")),
        limit=_opt_int(args.get("limit")) or 50,
    )


async def _get(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Detalha uma automação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo detalhado da automação.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).get(**kwargs),
        automation_id=_opt_text(args.get("automation_id")),
        query=_opt_text(args.get("query")),
    )


async def _update(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Altera uma automação existente.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo da automação alterada.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).update(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        name=_opt_text(args.get("name")),
        description=_opt_text(args.get("description")),
        objective=_opt_text(args.get("objective")),
        schedule=_opt_text(args.get("schedule")),
        cron=_opt_text(args.get("cron")),
        run_at=_opt_text(args.get("run_at")),
        interval_seconds=_opt_int(args.get("interval_seconds")),
        timezone=_opt_text(args.get("timezone")),
        dependencies=_opt_objects(args.get("dependencies")),
        confirm=bool(args.get("confirm")),
    )


async def _enable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Ativa uma automação, exigindo o token da prévia confirmada.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo da automação ativada.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).set_state(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        state="enabled",
        confirmation_token=_opt_text(args.get("confirmation_token")),
    )


async def _suspend(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Suspende uma automação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo da automação suspensa.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).set_state(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        state="suspended",
    )


async def _disable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Desativa uma automação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo da automação desativada.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).set_state(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        state="disabled",
    )


async def _run_now(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Executa a automação imediatamente.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O resumo do disparo manual registrado.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).run_now(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        wait=bool(args.get("wait")),
    )


async def _test(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Verifica a prontidão de uma automação (e só executa quando pedido).

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        O relatório de prontidão (e o desfecho, quando o teste executou).
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).test(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        execute=bool(args.get("execute")),
    )


async def _history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Lista os disparos de uma automação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        A lista de disparos com estado, horário e run associado.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).history(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        limit=_opt_int(args.get("limit")) or 20,
    )


async def _cancel(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Cancela os disparos pendentes de uma automação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        A quantidade de disparos cancelados.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).cancel_pending(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
    )


async def _delete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Remove uma automação, exigindo confirmação.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada.

    Returns:
        A confirmação da remoção.
    """
    return await _call(
        ctx,
        lambda c, **kwargs: _service(c).delete(**kwargs),
        automation_id=str(args.get("automation_id") or ""),
        confirm=bool(args.get("confirm")),
    )


async def _supervisor_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Estado do runtime de automações e diagnóstico do supervisor.

    Args:
        ctx: contexto da execução.
        args: argumentos da chamada (`diagnose` pede o relatório detalhado).

    Returns:
        O estado do runtime (e o diagnóstico, quando pedido).
    """
    service = _service(ctx)
    try:
        status = service.runtime_status()
    except AutomationChatError as exc:
        return _fail(exc)
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    result: dict[str, Any] = {
        "success": True,
        "runtime": status,
        "automation_stats": status.get("automations"),
    }
    if bool(args.get("diagnose")):
        try:
            report = service.diagnose()
        except Exception as exc:
            report = {"error": str(exc)}
        result["diagnostics"] = _render_diagnostics(report)
    result["message"] = (
        "Runtime de automações: " + str(status.get("mode"))
    )
    return _with_content(result)


def _render_diagnostics(report: dict[str, Any]) -> str:
    """Texto do diagnóstico do supervisor.

    Args:
        report: diagnóstico do supervisor.

    Returns:
        Texto multilinha com as automações e os disparos pendentes.
    """
    lines: list[str] = []
    for automation in report.get("automations") or []:
        if not isinstance(automation, dict):
            continue
        lines.append(
            f"- {automation.get('name')} | id={automation.get('id')} | "
            f"estado={automation.get('state')} | fuso={automation.get('timezone')} | "
            f"próximo={automation.get('next_run_at')} | gravado={automation.get('stored_next_run_at')}"
        )
    pending = report.get("pending_firings") or []
    lines.append(f"Disparos pendentes: {len(pending)}")
    for firing in pending:
        if isinstance(firing, dict):
            lines.append(
                f"- {firing.get('id')} | {firing.get('state')} | tentativa {firing.get('attempt')} | "
                f"erro={firing.get('error') or '—'}"
            )
    if report.get("error"):
        lines.append(f"Erro: {report['error']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ argumentos


def _opt_text(value: Any) -> str | None:
    """Texto de um argumento, ignorando valores vazios.

    Args:
        value: valor recebido.

    Returns:
        O texto, ou `None` quando o argumento não foi informado.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    """Inteiro de um argumento, ignorando valores vazios.

    Args:
        value: valor recebido.

    Returns:
        O inteiro, ou `None` quando o argumento não foi informado.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_list(value: Any) -> list[str] | None:
    """Lista de textos de um argumento.

    Args:
        value: valor recebido (lista ou texto separado por espaços).

    Returns:
        A lista, ou `None` quando o argumento não foi informado.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return None
    return text.split()


def _opt_objects(value: Any) -> list[dict[str, Any]] | None:
    """Lista de objetos de um argumento.

    Args:
        value: valor recebido.

    Returns:
        A lista de dicionários, ou `None` quando o argumento não foi informado.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return None


# ------------------------------------------------------------------- registro


def _schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Monta um JSON Schema de objeto para o argumento de uma ferramenta.

    Args:
        properties: propriedades do objeto.
        required: nomes obrigatórios.

    Returns:
        O esquema JSON.
    """
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_ID = {"type": "string", "description": "Identificador da automação (id)."}
_SCHEDULE = {
    "type": "string",
    "description": (
        "Horário em português: «todos os dias às 9h», «toda segunda-feira às 8h30», "
        "«amanhã às 14h», «a cada 4 horas», «no último dia de cada mês às 23h»."
    ),
}


def register_all(registry: ToolRegistry) -> None:
    """Registra no registro as ferramentas de automação.

    Args:
        registry: registro onde as specs e os handlers são cadastrados.
    """
    specs = [
        ToolSpec(
            id="automation_create",
            description=(
                "Cria uma tarefa agendada (automação). Recebe o objetivo e o horário em "
                "português; a automação nasce desabilitada e devolve um "
                "confirmation_token para ativar depois da confirmação do usuário."
            ),
            input_schema=_schema(
                {
                    "name": {"type": "string", "description": "Nome curto da automação."},
                    "objective": {
                        "type": "string",
                        "description": "O que a automação deve fazer a cada disparo.",
                    },
                    "schedule": _SCHEDULE,
                    "action_kind": {
                        "type": "string",
                        "enum": ["callidus", "script"],
                        "description": (
                            "«callidus» para um trabalho do agente (é o padrão; use sempre "
                            "que o pedido for verificar, analisar, preparar, testar ou "
                            "avisar). «script» apenas quando o usuário pedir para executar "
                            "um comando do sistema."
                        ),
                    },
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Comando do script, quando action_kind=script.",
                    },
                    "script": {"type": "string", "description": "Caminho do script."},
                    "cron": {
                        "type": "string",
                        "description": "Expressão cron, só quando o pedido for explícito.",
                    },
                    "run_at": {
                        "type": "string",
                        "description": "Instante único (AAAA-MM-DD HH:MM).",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Intervalo fixo em segundos.",
                    },
                    "timezone": {"type": "string", "description": "Fuso (ex.: America/Sao_Paulo)."},
                    "description": {"type": "string", "description": "Descrição livre."},
                    "allow_scripts": {
                        "type": "boolean",
                        "description": "Autoriza executar scripts (exige o pedido do usuário).",
                    },
                    "allowed_commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Executáveis autorizados.",
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Dependências a verificar antes do disparo.",
                    },
                },
                required=["name", "objective", "schedule"],
            ),
            timeout_seconds=60.0,
        ),
        ToolSpec(
            id="automation_list",
            description="Lista as tarefas agendadas do projeto, com estado e próximo disparo.",
            input_schema=_schema(
                {
                    "state": {
                        "type": "string",
                        "enum": ["enabled", "suspended", "disabled"],
                        "description": "Filtra por estado.",
                    },
                    "query": {"type": "string", "description": "Filtra por nome."},
                    "limit": {"type": "integer", "description": "Máximo de itens (padrão 50)."},
                }
            ),
        ),
        ToolSpec(
            id="automation_get",
            description="Detalha uma tarefa agendada, com o objetivo, a agenda e o próximo disparo.",
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "query": {
                        "type": "string",
                        "description": "Nome citado pelo usuário, quando não há id.",
                    },
                }
            ),
        ),
        ToolSpec(
            id="automation_update",
            description=(
                "Altera uma tarefa agendada (horário, recorrência, objetivo ou nome). "
                "Mudança material exige nova confirmação do usuário."
            ),
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "objective": {"type": "string"},
                    "schedule": _SCHEDULE,
                    "cron": {"type": "string"},
                    "run_at": {"type": "string"},
                    "interval_seconds": {"type": "integer"},
                    "timezone": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                    "confirm": {
                        "type": "boolean",
                        "description": "O usuário confirmou a alteração material.",
                    },
                },
                required=["automation_id"],
            ),
        ),
        ToolSpec(
            id="automation_enable",
            description=(
                "Ativa uma tarefa agendada. Exige o confirmation_token devolvido pela "
                "criação ou pela consulta — a confirmação vale para a definição mostrada."
            ),
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "confirmation_token": {
                        "type": "string",
                        "description": "Token da prévia que o usuário confirmou.",
                    },
                },
                required=["automation_id", "confirmation_token"],
            ),
        ),
        ToolSpec(
            id="automation_suspend",
            description="Suspende uma tarefa agendada (pausa os disparos futuros).",
            input_schema=_schema({"automation_id": _ID}, required=["automation_id"]),
        ),
        ToolSpec(
            id="automation_disable",
            description="Desativa uma tarefa agendada.",
            input_schema=_schema({"automation_id": _ID}, required=["automation_id"]),
        ),
        ToolSpec(
            id="automation_run_now",
            description=(
                "Executa a tarefa agendada agora, sem esperar o próximo horário. "
                "O disparo registrado ainda não é um run concluído."
            ),
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "wait": {
                        "type": "boolean",
                        "description": "Espera a execução terminar (padrão: não espera).",
                    },
                },
                required=["automation_id"],
            ),
            timeout_seconds=120.0,
        ),
        ToolSpec(
            id="automation_test",
            description=(
                "Verifica se a tarefa agendada está pronta (dependências e destino) sem "
                "executar nada. Use execute=true só quando o pedido for um teste com efeito real."
            ),
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "execute": {
                        "type": "boolean",
                        "description": "Executa a ação de verdade (padrão: não).",
                    },
                },
                required=["automation_id"],
            ),
            timeout_seconds=120.0,
        ),
        ToolSpec(
            id="automation_history",
            description="Mostra o histórico de disparos de uma tarefa agendada, com erros e runs.",
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "limit": {"type": "integer", "description": "Máximo de disparos (padrão 20)."},
                },
                required=["automation_id"],
            ),
        ),
        ToolSpec(
            id="automation_cancel",
            description="Cancela os disparos pendentes de uma tarefa agendada.",
            input_schema=_schema({"automation_id": _ID}, required=["automation_id"]),
        ),
        ToolSpec(
            id="automation_delete",
            description=(
                "Remove definitivamente uma tarefa agendada. Exige confirm=true, depois "
                "da confirmação do usuário."
            ),
            input_schema=_schema(
                {
                    "automation_id": _ID,
                    "confirm": {
                        "type": "boolean",
                        "description": "O usuário confirmou a remoção.",
                    },
                },
                required=["automation_id", "confirm"],
            ),
        ),
        ToolSpec(
            id="automation_supervisor_status",
            description=(
                "Estado do runtime de automações (se está rodando, quais as limitações) e, "
                "com diagnose=true, o diagnóstico do supervisor."
            ),
            input_schema=_schema(
                {
                    "diagnose": {
                        "type": "boolean",
                        "description": "Inclui o diagnóstico detalhado.",
                    }
                }
            ),
        ),
    ]
    handlers = {
        "automation_create": _create,
        "automation_list": _list,
        "automation_get": _get,
        "automation_update": _update,
        "automation_enable": _enable,
        "automation_suspend": _suspend,
        "automation_disable": _disable,
        "automation_run_now": _run_now,
        "automation_test": _test,
        "automation_history": _history,
        "automation_cancel": _cancel,
        "automation_delete": _delete,
        "automation_supervisor_status": _supervisor_status,
    }
    for spec in specs:
        # As ferramentas de automação formam uma família própria: elas podem ser
        # desligadas em conjunto sem afetar as ferramentas de arquivo ou de sistema.
        spec.family = ToolFamily.AUTOMATION.value
        registry.register(spec, handlers[spec.id])


__all__ = ["AUTOMATION_TOOL_CATALOG", "register_all", "render_result"]
