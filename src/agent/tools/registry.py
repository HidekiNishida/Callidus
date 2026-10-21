"""
Arquivo: src/agent/tools/registry.py
Nome: registry.py
Propósito: manter o registro central das ferramentas do agente e executá-las com contrato uniforme.
Responsabilidade: camada de aplicação — catálogo de ferramentas, aliases e despacho das chamadas.
Componentes: ToolSpec, ToolContext, ToolRegistry, canonical_tool_id, current_call_id, build_default_registry, TOOL_ALIASES.
Dependências: agent.observability, agent.tools.availability, agent.tools.contracts, agent.tools.policy, pydantic.
Observações: ferramentas que exigem aprovação recusam a execução quando ela não foi concedida.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from agent.observability import emit
from agent.tools.arguments import validate_arguments
from agent.tools.availability import check_tool
from agent.tools.contracts import ExecutionMode, ToolFamily, ToolRisk
from agent.tools.policy import PermissionPolicy, redact


class ToolSpec(BaseModel):
    """Contrato de uma ferramenta exposta ao modelo.

    Atributos:
        id: identificador da ferramenta, como o modelo a chama.
        description: descrição enviada ao modelo.
        input_schema: schema JSON dos argumentos aceitos.
        requires_approval: quando `True`, a execução exige aprovação explícita.
        timeout_seconds: tempo limite sugerido para a execução.
        hard_timeout_seconds: tempo limite **imposto** pelo registro; `None` desliga o corte.
        family: família funcional da ferramenta (unidade habilitada/desabilitada em conjunto).
        risk: nível de risco declarado, do mais seguro ao mais perigoso.
        permissions: permissões exigidas, em texto livre (`fs.write`, `process.spawn`, ...).
        platforms: sistemas operacionais suportados; lista vazia significa "todos".
        requires: pré-requisitos verificáveis (`binary:git`, `module:playwright`, `os:macos`).
        execution: modo de execução (foreground, background, interactive, non_interactive).
        side_effects: quando `True`, a ferramenta altera o ambiente fora do workspace.
        output_schema: schema do resultado devolvido.
        verify: como o resultado pode ser conferido de forma independente.
    """

    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    timeout_seconds: float = 60.0
    hard_timeout_seconds: float | None = None
    family: str = ToolFamily.FILE.value
    risk: str = ToolRisk.READ.value
    permissions: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    execution: str = ExecutionMode.FOREGROUND.value
    side_effects: bool = False
    output_schema: dict[str, Any] = Field(default_factory=dict)
    verify: str = ""


@dataclass
class ToolContext:
    """Contexto handed a uma ferramenta durante a execução.

    Atributos:
        project_root: raiz autorizada do projeto.
        run_id: run em curso, quando houver.
        task_id: tarefa em execução, quando houver.
        memory_saver: callback opcional para gravar memória.
        browser_mode: modo do navegador (`off` por padrão).
        remote: configuração do computador remoto, quando o projeto roda em outro servidor.
        session: sessão do banco da execução, quando a ferramenta precisar do estado persistente.
        project_id: projeto da conversa, para as ferramentas que pertencem a um projeto.
        conversation_id: conversa em curso, para as ferramentas que pertencem a uma conversa.
        settings: configurações do processo, para as ferramentas que dependem delas.
        policy: política de permissões da sessão, quando houver.
        cancel_event: evento de cancelamento cooperativo, para tarefas longas.
    """

    project_root: str
    run_id: str | None = None
    task_id: str | None = None
    memory_saver: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    browser_mode: str = "off"
    # Configuração do computador remoto (quando o projeto roda em outro servidor).
    remote: Any = None
    # Sessão do banco da execução: as ferramentas que consultam o estado persistente
    # (as automações) usam os serviços, e não HTTP contra a própria API.
    session: Any = None
    project_id: str | None = None
    conversation_id: str | None = None
    settings: Any = None
    # Política de permissões da sessão: o registro consulta antes de executar.
    policy: PermissionPolicy | None = None
    # Cancelamento cooperativo: as ferramentas longas consultam `cancelled` durante o trabalho.
    cancel_event: asyncio.Event | None = None
    # Estado livre para ferramentas que precisam compartilhar memória entre chamadas.
    scratch: dict[str, Any] = field(default_factory=dict)

    @property
    def cancelled(self) -> bool:
        """Indica se o cancelamento cooperativo foi pedido para esta execução."""
        return bool(self.cancel_event is not None and self.cancel_event.is_set())



ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

# Nomes que o modelo costuma inventar → ferramenta real.
TOOL_ALIASES: dict[str, str] = {
    "ls": "list_dir",
    "list_files": "list_dir",
    "list_directory": "list_dir",
    "dir": "list_dir",
    "glob": "glob_files",
    "find_files": "glob_files",
    "find": "glob_files",
    "grep": "search_grep",
    "search": "search_grep",
    "str_replace": "edit_file",
    "search_replace": "edit_file",
    "apply_patch": "edit_file",
    "replace_in_file": "edit_file",
    "edit": "edit_file",
    "delete": "delete_file",
    "remove_file": "delete_file",
    "rm": "delete_file",
    "shell": "run_command",
    "bash": "run_command",
    "exec": "run_command",
    "python": "run_script",
    "pytest": "run_pytest",
    "mkdir": "make_dir",
    "create_directory": "make_dir",
    "mv": "move_file",
    "rename": "move_file",
    "git": "git_status",
    "browse": "browser",
    "web": "browser",
    "open_url": "browser",
    "sysinfo": "system_info",
    "os_info": "system_info",
    "whoami": "system_info",
}


def canonical_tool_id(tool_id: str) -> str:
    """Resolve o alias de uma ferramenta para o identificador real.

    Args:
        tool_id: nome pedido pelo modelo.

    Returns:
        O identificador canônico; o próprio nome quando não há alias.
    """
    return TOOL_ALIASES.get(tool_id, tool_id)


class ToolRegistry:
    """Catálogo de ferramentas do agente: specs, handlers e execução uniformizada.

    A execução passa sempre pelas mesmas quatro etapas — disponibilidade, política,
    prazo e cancelamento — antes de chegar ao handler. Nenhuma ferramenta é executada
    por fora deste caminho.

    Atributos:
        _specs: especificações registradas, indexadas pelo identificador.
        _handlers: handlers registrados, indexados pelo identificador.
    """

    def __init__(self) -> None:
        """Cria um registro vazio."""
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        """Registra uma ferramenta e seu handler.

        Args:
            spec: contrato da ferramenta.
            handler: função assíncrona que executa a ferramenta.
        """
        self._specs[spec.id] = spec
        self._handlers[spec.id] = handler

    def get_spec(self, tool_id: str) -> ToolSpec:
        """Especificação de uma ferramenta.

        Args:
            tool_id: identificador da ferramenta.

        Returns:
            A `ToolSpec` correspondente.

        Raises:
            KeyError: quando a ferramenta não está registrada.
        """
        if tool_id not in self._specs:
            raise KeyError(tool_id)
        return self._specs[tool_id]

    def list_specs(self) -> list[ToolSpec]:
        """Todas as especificações registradas.

        Returns:
            Uma cópia da lista de specs.
        """
        return list(self._specs.values())

    def ids(self) -> list[str]:
        """Identificadores de todas as ferramentas registradas.

        Returns:
            A lista de identificadores, em ordem alfabética.
        """
        return sorted(self._specs)

    def specs_of_family(self, family: str) -> list[ToolSpec]:
        """Ferramentas de uma família.

        Args:
            family: identificador da família (`file`, `system`, `desktop`, ...).

        Returns:
            As specs da família, em ordem alfabética.
        """
        return [spec for spec in self._specs.values() if spec.family == family]

    def compact_catalog(self, families: list[str] | None = None) -> str:
        """Catálogo compacto: o texto que cabe no prompt sem estourar o contexto.

        O catálogo completo fica fora do prompt; o modelo recebe o identificador, a
        descrição em uma linha e os argumentos principais. O detalhe vem sob demanda,
        pela ferramenta `tool_help`.

        Args:
            families: famílias a incluir; `None` inclui todas.

        Returns:
            O catálogo em texto, pronto para o prompt.
        """
        wanted = set(families) if families else None
        rows: list[str] = []
        for tool_id in self.ids():
            spec = self._specs[tool_id]
            if wanted is not None and spec.family not in wanted:
                continue
            args = ", ".join(sorted(spec.input_schema))
            row = f"- {tool_id}: {spec.description}"
            if args:
                row += f" (args: {args})"
            if spec.requires_approval:
                row += " [aprovação]"
            rows.append(row)
        if not rows:
            return "Nenhuma ferramenta disponível."
        return "\n".join(rows)

    def describe(self, tool_id: str) -> dict[str, Any]:
        """Detalhe completo de uma ferramenta, para carregar sob demanda.

        Args:
            tool_id: identificador (alias aceito).

        Returns:
            Um dicionário com o contrato da ferramenta e o resultado da verificação
            de pré-requisitos.
        """
        resolved = canonical_tool_id(tool_id)
        if resolved not in self._specs:
            return {"success": False, "error": f"ferramenta desconhecida: {tool_id}"}
        spec = self._specs[resolved]
        availability = check_tool(spec)
        return {
            "success": True,
            "tool": resolved,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
            "risk": spec.risk,
            "family": spec.family,
            "execution": spec.execution,
            "side_effects": spec.side_effects,
            "permissions": spec.permissions,
            "requires_approval": spec.requires_approval,
            "platforms": spec.platforms or ["todas"],
            "requires": spec.requires,
            "verify": spec.verify,
            "available": availability.available,
            "missing": availability.missing,
            "hints": availability.hints,
        }

    def availability_report(self) -> list[dict[str, Any]]:
        """Situação de disponibilidade de todas as ferramentas registradas.

        Returns:
            Uma lista com o identificador, a família e o que falta para cada ferramenta.
        """
        report: list[dict[str, Any]] = []
        for tool_id in self.ids():
            spec = self._specs[tool_id]
            availability = check_tool(spec)
            report.append(
                {
                    "tool": tool_id,
                    "family": spec.family,
                    "available": availability.available,
                    "missing": availability.missing,
                    "hints": availability.hints,
                }
            )
        return report

    async def execute(
        self,
        tool_id: str,
        ctx: ToolContext,
        args: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Executa uma ferramenta e emite os eventos de início e de desfecho.

        A ordem é fixa: alias → argumentos → disponibilidade → política → aprovação →
        cancelamento → prazo → handler. Cada recusa devolve um dicionário com `success`
        falso e um `error` estável, para que o agente consiga reagir sem interpretar texto livre.

        Args:
            tool_id: nome pedido pelo modelo; aliases são resolvidos.
            ctx: contexto handed à ferramenta.
            args: argumentos da chamada.
            approved: quando `True`, ferramentas que exigem aprovação são executadas mesmo assim.

        Returns:
            O resultado da ferramenta; em caso de recusa ou erro, um dicionário com `success` falso.

        Raises:
            Exception: qualquer erro levantado pelo handler é propagado após o evento de falha.
        """
        tool_id = canonical_tool_id(tool_id)
        if tool_id not in self._specs:
            known = ", ".join(sorted(self._specs))
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "ferramenta desconhecida", "executed": False},
            )
            return {"success": False, "error": f"ferramenta desconhecida: {tool_id}", "known": known}
        spec = self.get_spec(tool_id)
        argument_error = validate_arguments(spec.input_schema, args)
        if argument_error:
            emit(
                "tool.failed",
                {
                    "call_id": uuid.uuid4().hex[:12],
                    "tool": tool_id,
                    "error": argument_error,
                    "executed": False,
                    "code": "invalid_arguments",
                },
            )
            return {
                "success": False,
                "error": argument_error,
                "code": "invalid_arguments",
                "tool": tool_id,
            }

        availability = check_tool(spec)
        if not availability.available:
            emit(
                "tool.failed",
                {
                    "call_id": uuid.uuid4().hex[:12],
                    "tool": tool_id,
                    "error": "requisitos ausentes",
                    "executed": False,
                    "missing": availability.missing,
                },
            )
            return {
                "success": False,
                "error": "requisitos ausentes",
                "tool": tool_id,
                "missing": availability.missing,
                "hints": availability.hints,
            }

        policy = ctx.policy
        if policy is not None:
            risk = ToolRisk(spec.risk) if spec.risk in {item.value for item in ToolRisk} else ToolRisk.READ
            decision = policy.decide(tool_id, risk=risk, family=spec.family, approved=approved)
            if not decision.allowed:
                emit(
                    "tool.failed",
                    {
                        "call_id": uuid.uuid4().hex[:12],
                        "tool": tool_id,
                        "error": decision.reason,
                        "executed": False,
                    },
                )
                return {"success": False, "error": "bloqueado pela política", "tool": tool_id, "reason": decision.reason}
            if (spec.requires_approval or decision.requires_approval) and not approved:
                emit(
                    "tool.failed",
                    {
                        "call_id": uuid.uuid4().hex[:12],
                        "tool": tool_id,
                        "error": "approval_required",
                        "executed": False,
                        "reason": decision.reason,
                    },
                )
                return {
                    "success": False,
                    "error": "approval_required",
                    "tool": tool_id,
                    "reason": decision.reason,
                    "risk": spec.risk,
                }
        elif spec.requires_approval and not approved:
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "approval_required", "executed": False},
            )
            return {
                "success": False,
                "error": "approval_required",
                "tool": tool_id,
            }
        if ctx.cancelled:
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "cancelado", "executed": False},
            )
            return {"success": False, "error": "cancelado", "tool": tool_id}

        handler = self._handlers[tool_id]
        call_id = uuid.uuid4().hex[:12]
        token = _CALL_ID.set(call_id)
        started = time.monotonic()
        emit(
            "tool.started",
            {
                "call_id": call_id,
                "tool": tool_id,
                "args": _args_preview(redact(args)),
                "risk": spec.risk,
                "family": spec.family,
            },
            commit=True,
        )
        try:
            if spec.hard_timeout_seconds:
                result = await asyncio.wait_for(
                    handler(ctx, args), timeout=spec.hard_timeout_seconds
                )
            else:
                result = await handler(ctx, args)
        except asyncio.TimeoutError:
            emit(
                "tool.failed",
                {
                    "call_id": call_id,
                    "tool": tool_id,
                    "error": "tempo limite excedido",
                    "duration_ms": _ms(started),
                },
            )
            return {
                "success": False,
                "error": "tempo limite excedido",
                "tool": tool_id,
                "timeout_seconds": spec.hard_timeout_seconds,
            }
        except asyncio.CancelledError:
            emit(
                "tool.failed",
                {"call_id": call_id, "tool": tool_id, "error": "cancelado", "duration_ms": _ms(started)},
            )
            raise
        except Exception as exc:
            emit(
                "tool.failed",
                {"call_id": call_id, "tool": tool_id, "error": f"{type(exc).__name__}: {exc}", "duration_ms": _ms(started)},
            )
            raise
        finally:
            _CALL_ID.reset(token)
        result = redact(result) if isinstance(result, dict) else result
        if isinstance(result, dict):
            result.setdefault("tool", tool_id)
        if isinstance(result, dict) and result.get("success"):
            emit("tool.completed", {"call_id": call_id, "tool": tool_id, "duration_ms": _ms(started), "summary": _summary(result)})
        else:
            emit(
                "tool.failed",
                {
                    "call_id": call_id,
                    "tool": tool_id,
                    "error": str((result or {}).get("error") or "falhou"),
                    "duration_ms": _ms(started),
                    "summary": _summary(result or {}),
                },
            )
        return result



_CALL_ID: ContextVar[str | None] = ContextVar("tool_call_id", default=None)
_PREVIEW_KEYS = ("content", "new_string", "old_string", "new", "old", "replace", "replacement")


def current_call_id() -> str | None:
    """Id da chamada de ferramenta em andamento (comandos e arquivos usam o mesmo para se ligar a ela)."""
    return _CALL_ID.get()


def _ms(started: float) -> int:
    """Duração em milissegundos desde o instante informado.

    Args:
        started: instante de início, medido com `time.monotonic`.

    Returns:
        Os milissegundos decorridos.
    """
    return int((time.monotonic() - started) * 1000)


def _args_preview(args: dict[str, Any]) -> dict[str, Any]:
    """Argumentos para exibição: conteúdo de arquivo vira tamanho (o diff real sai em `file.*`)."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key in _PREVIEW_KEYS and isinstance(value, str) and len(value) > 200:
            out[key] = f"[{len(value)} caracteres]"
        else:
            out[key] = value
    return out


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """Campos do resultado que valem a pena exibir no evento de desfecho.

    Args:
        result: resultado devolvido pela ferramenta.

    Returns:
        Um dicionário apenas com os campos presentes entre os conhecidos.
    """
    keep = ("path", "exit_code", "count", "bytes", "added", "removed", "replacements", "total_lines", "truncated", "category")
    return {k: result[k] for k in keep if k in result}


def build_default_registry() -> ToolRegistry:
    """Monta o registro com todas as ferramentas embutidas.

    Returns:
        O registro pronto para uso, com as ferramentas de `agent.tools.builtins`,
        `agent.tools.automations`, `agent.tools.system_tools`, `agent.tools.desktop_tools`,
        `agent.tools.devtools` e `agent.tools.skill_tools` cadastradas.
    """
    from agent.tools import automations as automation_tools
    from agent.tools import builtins as built
    from agent.tools import desktop_tools as desktop
    from agent.tools import devtools as engineering
    from agent.tools import skill_tools as skills
    from agent.tools import system_tools as system

    reg = ToolRegistry()
    built.register_all(reg)
    automation_tools.register_all(reg)
    system.register_all(reg)
    desktop.register_all(reg)
    engineering.register_all(reg)
    skills.register_all(reg)
    reg.register(
        ToolSpec(
            id="tool_catalog",
            description="Lista as ferramentas disponíveis; passe family para filtrar",
            input_schema={"family": "str?"},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        _tool_catalog,
    )
    reg.register(
        ToolSpec(
            id="tool_help",
            description="Detalha uma ferramenta: argumentos, permissões, riscos e pré-requisitos",
            input_schema={"tool": "str"},
            family=ToolFamily.FILE.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'available'",
        ),
        _tool_help,
    )
    return reg


_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """Registro padrão do processo, montado uma vez.

    Returns:
        O registro com todas as ferramentas embutidas.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


async def _tool_catalog(ctx: ToolContext, args: dict) -> dict:
    """Entrega o catálogo compacto das ferramentas registradas.

    O modelo recebe aqui a lista sob demanda, em vez de carregá-la em cada prompt.

    Args:
        ctx: contexto da ferramenta, com o registro em `ctx.scratch["registry"]`.
        args: argumentos da chamada (`family` opcional).

    Returns:
        Um dicionário com as ferramentas e o resumo em texto.
    """
    registry = ctx.scratch.get("registry")
    if not isinstance(registry, ToolRegistry):
        return {"success": False, "error": "registro de ferramentas indisponível neste contexto"}
    family = args.get("family")
    families = [str(family)] if family else None
    specs = registry.specs_of_family(str(family)) if family else registry.list_specs()
    return {
        "success": True,
        "count": len(specs),
        "tools": [
            {
                "id": spec.id,
                "description": spec.description,
                "args": sorted(spec.input_schema),
                "risk": spec.risk,
                "family": spec.family,
                "requires_approval": spec.requires_approval,
            }
            for spec in sorted(specs, key=lambda item: item.id)
        ],
        "catalog": registry.compact_catalog(families),
    }


async def _tool_help(ctx: ToolContext, args: dict) -> dict:
    """Detalha uma ferramenta sob demanda.

    Args:
        ctx: contexto da ferramenta, com o registro em `ctx.scratch["registry"]`.
        args: argumentos da chamada (`tool`).

    Returns:
        Um dicionário com o contrato completo da ferramenta.
    """
    registry = ctx.scratch.get("registry")
    if not isinstance(registry, ToolRegistry):
        return {"success": False, "error": "registro de ferramentas indisponível neste contexto"}
    tool_id = str(args.get("tool") or args.get("name") or "")
    if not tool_id:
        return {"success": False, "error": "informe o identificador da ferramenta"}
    return registry.describe(tool_id)
